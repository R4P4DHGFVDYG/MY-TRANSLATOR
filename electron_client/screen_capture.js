'use strict';

const path = require('node:path');

const CAPTURE_PARTITION = 'grc-capture-worker';
const DEFAULT_MAX_FRAME_RATE = 6;
const CAPTURE_LIFECYCLE_ERROR_CODE = 'ERR_SCREEN_CAPTURE_LIFECYCLE';

class ScreenCaptureLifecycleError extends Error {
    constructor(message, options = {}) {
        super(message, options);
        this.name = 'ScreenCaptureLifecycleError';
        this.code = CAPTURE_LIFECYCLE_ERROR_CODE;
    }
}

function isScreenCaptureLifecycleError(error) {
    return Boolean(error) && error.code === CAPTURE_LIFECYCLE_ERROR_CODE;
}

function isWindowAlive(window) {
    return Boolean(window) && !window.isDestroyed();
}

function displayCaptureKey(display) {
    const bounds = display?.bounds || {};
    return [
        Number(display?.id),
        Number(bounds.x),
        Number(bounds.y),
        Number(bounds.width),
        Number(bounds.height),
        Number(display?.scaleFactor)
    ].join(':');
}

function selectDisplaySource(sources, display, displays = []) {
    const availableSources = Array.isArray(sources) ? sources : [];
    const displayId = String(display?.id ?? '');
    const exact = availableSources.find(source => String(source?.display_id) === displayId);
    if (exact) {
        return exact;
    }
    const displayIndex = Array.isArray(displays)
        ? displays.findIndex(item => Number(item?.id) === Number(display?.id))
        : -1;
    return availableSources[displayIndex >= 0 ? displayIndex : 0] || null;
}

function workerInvocation(method, payload = {}) {
    const allowedMethods = new Set(['capture', 'encode', 'release', 'start', 'stop']);
    if (!allowedMethods.has(method)) {
        throw new TypeError('Unsupported screen capture worker method.');
    }
    return `window.captureWorker.invoke(${JSON.stringify(method)}, ${JSON.stringify(payload)})`;
}

function finitePerformanceValue(value) {
    const numeric = Number(value);
    return Number.isFinite(numeric) && numeric >= 0
        ? Number(numeric.toFixed(2))
        : 0;
}

class ScreenCaptureRuntime {
    constructor(options = {}) {
        if (typeof options.BrowserWindow !== 'function') {
            throw new TypeError('ScreenCaptureRuntime requires BrowserWindow.');
        }
        if (!options.desktopCapturer || typeof options.desktopCapturer.getSources !== 'function') {
            throw new TypeError('ScreenCaptureRuntime requires desktopCapturer.');
        }
        this.BrowserWindow = options.BrowserWindow;
        this.desktopCapturer = options.desktopCapturer;
        this.baseDir = options.baseDir || __dirname;
        this.getDisplays = typeof options.getDisplays === 'function'
            ? options.getDisplays
            : () => [];
        this.logger = options.logger || console;
        this.maxFrameRate = Math.max(
            1,
            Math.min(15, Math.round(Number(options.maxFrameRate) || DEFAULT_MAX_FRAME_RATE))
        );
        this.window = null;
        this.captureKey = '';
        this.requestedDisplay = null;
        this.starting = null;
        this.stopping = null;
        this.generation = 0;
        this.lifecycleId = 0;
    }

    async capture(selection, display, options = {}) {
        const startedAt = performance.now();
        const worker = await this._ensureWorker(display);
        const { window: currentWindow, generation: captureGeneration } = worker;
        if (!this._isWorkerActive(worker)) {
            throw new ScreenCaptureLifecycleError(
                'The persistent screen capture changed before reading a frame.'
            );
        }
        let result;
        try {
            result = await this._invoke(currentWindow, 'capture', {
                selection,
                displayBounds: display.bounds,
                maxPixels: options.maxPixels,
                signatureWidth: options.signatureWidth,
                signatureHeight: options.signatureHeight
            });
        } catch (error) {
            if (!this._isWorkerActive(worker)) {
                throw new ScreenCaptureLifecycleError(
                    'The persistent screen capture changed while reading a frame.',
                    { cause: error }
                );
            }
            throw error;
        }
        if (!this._isWorkerActive(worker)) {
            if (typeof result?.snapshotId === 'string') {
                try {
                    await this._invoke(currentWindow, 'release', {
                        snapshotId: result.snapshotId
                    });
                } catch {
                    // A stopped worker releases all of its snapshots during shutdown.
                }
            }
            throw new ScreenCaptureLifecycleError(
                'The persistent screen capture changed while reading a frame.'
            );
        }
        if (
            !result
            || typeof result.snapshotId !== 'string'
            || !Array.isArray(result.signature)
            || !Number.isFinite(Number(result.width))
            || !Number.isFinite(Number(result.height))
        ) {
            throw new Error('The persistent capture worker returned an invalid frame.');
        }
        return {
            captureBackend: 'stream',
            captureGeneration,
            snapshotId: result.snapshotId,
            frameSignature: Uint8Array.from(result.signature),
            width: Math.round(Number(result.width)),
            height: Math.round(Number(result.height)),
            startedAt,
            performance: {
                captureMs: finitePerformanceValue(result.captureMs),
                cropMs: 0,
                signatureMs: finitePerformanceValue(result.signatureMs),
                cropPixels: Math.max(0, Math.round(Number(result.cropPixels) || 0)),
                backend: 'persistent-stream'
            }
        };
    }

    async encode(frame, options = {}) {
        if (!this.owns(frame)) {
            throw new ScreenCaptureLifecycleError(
                'The screen snapshot belongs to an inactive capture stream.'
            );
        }
        const worker = {
            window: this.window,
            generation: frame.captureGeneration
        };
        let result;
        try {
            result = await this._invoke(worker.window, 'encode', {
                snapshotId: frame.snapshotId,
                maxBytes: options.maxBytes
            });
        } catch (error) {
            if (!this._isWorkerActive(worker)) {
                throw new ScreenCaptureLifecycleError(
                    'The persistent screen capture changed while encoding a frame.',
                    { cause: error }
                );
            }
            throw error;
        }
        if (!this._isWorkerActive(worker)) {
            throw new ScreenCaptureLifecycleError(
                'The persistent screen capture changed while encoding a frame.'
            );
        }
        if (
            !result
            || typeof result.dataUrl !== 'string'
            || !result.dataUrl.startsWith('data:image/png;base64,')
            || !/^[0-9a-f]{64}$/i.test(String(result.digest || ''))
        ) {
            throw new Error('The persistent capture worker returned an invalid PNG.');
        }
        return {
            base64: result.dataUrl,
            digest: result.digest,
            width: Math.round(Number(result.width) || frame.width),
            height: Math.round(Number(result.height) || frame.height),
            performance: {
                ...frame.performance,
                encodeMs: finitePerformanceValue(result.encodeMs),
                totalMs: finitePerformanceValue(performance.now() - frame.startedAt),
                encodedBytes: Math.max(0, Math.round(Number(result.encodedBytes) || 0))
            }
        };
    }

    owns(frame) {
        return Boolean(
            frame
            && frame.captureBackend === 'stream'
            && frame.captureGeneration === this.generation
            && typeof frame.snapshotId === 'string'
            && isWindowAlive(this.window)
        );
    }

    _isWorkerActive(worker) {
        return Boolean(
            worker
            && worker.window === this.window
            && worker.generation === this.generation
            && isWindowAlive(worker.window)
            && !worker.window.webContents.isDestroyed()
        );
    }

    release(frame) {
        if (!this.owns(frame)) {
            return false;
        }
        void this._invoke(this.window, 'release', { snapshotId: frame.snapshotId })
            .catch(error => this.logger.warn('[capture] Could not release a snapshot:', error));
        return true;
    }

    stop() {
        this.lifecycleId += 1;
        return this._stopWorker();
    }

    async _stopWorker() {
        if (this.stopping) {
            return this.stopping;
        }
        const stopping = this._stopCurrentWorker();
        this.stopping = stopping;
        try {
            await stopping;
        } finally {
            if (this.stopping === stopping) {
                this.stopping = null;
            }
        }
    }

    async _stopCurrentWorker() {
        const currentWindow = this.window;
        this.window = null;
        this.captureKey = '';
        this.requestedDisplay = null;
        this.generation += 1;
        if (!isWindowAlive(currentWindow)) {
            return;
        }
        const captureSession = currentWindow.webContents?.session;
        try {
            await this._invoke(currentWindow, 'stop');
        } catch {
            // The renderer may already be gone during shutdown.
        }
        if (captureSession?.setDisplayMediaRequestHandler) {
            captureSession.setDisplayMediaRequestHandler(null);
        }
        if (isWindowAlive(currentWindow)) {
            currentWindow.destroy();
        }
    }

    async _ensureWorker(display) {
        const requestedKey = displayCaptureKey(display);
        while (true) {
            if (isWindowAlive(this.window) && this.captureKey === requestedKey) {
                return {
                    window: this.window,
                    generation: this.generation
                };
            }

            const activeStartup = this.starting;
            if (activeStartup) {
                await activeStartup.promise;
                continue;
            }

            const lifecycleId = ++this.lifecycleId;
            const startup = {
                captureKey: requestedKey,
                lifecycleId,
                promise: null
            };
            startup.promise = this._startWorker(display, requestedKey, lifecycleId);
            this.starting = startup;
            try {
                await startup.promise;
            } finally {
                if (this.starting === startup) {
                    this.starting = null;
                }
            }

            if (lifecycleId !== this.lifecycleId) {
                throw new ScreenCaptureLifecycleError(
                    'The persistent screen capture start was cancelled.'
                );
            }
        }
    }

    async _startWorker(display, requestedKey, lifecycleId) {
        await this._stopWorker();
        if (lifecycleId !== this.lifecycleId) {
            throw new ScreenCaptureLifecycleError(
                'The persistent screen capture start was cancelled.'
            );
        }
        this.requestedDisplay = display;
        const currentWindow = new this.BrowserWindow({
            width: 1,
            height: 1,
            frame: false,
            show: false,
            skipTaskbar: true,
            focusable: false,
            webPreferences: {
                backgroundThrottling: false,
                contextIsolation: true,
                nodeIntegration: false,
                partition: CAPTURE_PARTITION,
                sandbox: true,
                webSecurity: true
            }
        });
        this.window = currentWindow;
        this.generation += 1;
        const workerGeneration = this.generation;
        currentWindow.webContents.setWindowOpenHandler(() => ({ action: 'deny' }));
        currentWindow.webContents.on('will-navigate', event => event.preventDefault());
        currentWindow.webContents.on('render-process-gone', (_event, details) => {
            if (this.window === currentWindow) {
                this.logger.warn('[capture] Worker renderer stopped:', details?.reason || 'unknown');
                const captureSession = currentWindow.webContents?.session;
                this.window = null;
                this.captureKey = '';
                this.requestedDisplay = null;
                this.generation += 1;
                if (captureSession?.setDisplayMediaRequestHandler) {
                    captureSession.setDisplayMediaRequestHandler(null);
                }
                if (isWindowAlive(currentWindow)) {
                    currentWindow.destroy();
                }
            }
        });
        currentWindow.on('closed', () => {
            if (this.window === currentWindow) {
                this.window = null;
                this.captureKey = '';
                this.generation += 1;
            }
        });

        const captureSession = currentWindow.webContents.session;
        captureSession.setDisplayMediaRequestHandler((_request, callback) => {
            void this._resolveRequestedSource(workerGeneration)
                .then(source => callback(source ? { video: source } : {}))
                .catch(error => {
                    this.logger.warn('[capture] Could not resolve the selected display:', error);
                    callback({});
                });
        });

        try {
            await currentWindow.loadFile(path.join(this.baseDir, 'capture_worker.html'));
            if (lifecycleId !== this.lifecycleId) {
                throw new ScreenCaptureLifecycleError(
                    'The persistent screen capture start was cancelled.'
                );
            }
            const streamInfo = await this._invoke(currentWindow, 'start', {
                maxFrameRate: this.maxFrameRate
            }, true);
            if (lifecycleId !== this.lifecycleId || workerGeneration !== this.generation) {
                throw new ScreenCaptureLifecycleError(
                    'The persistent screen capture start was cancelled.'
                );
            }
            if (
                !streamInfo
                || Number(streamInfo.width) <= 0
                || Number(streamInfo.height) <= 0
            ) {
                throw new Error('The selected display stream returned invalid dimensions.');
            }
            this.captureKey = requestedKey;
            this.logger.info('[performance]', JSON.stringify({
                stage: 'capture-stream-ready',
                displayId: display.id,
                width: streamInfo.width,
                height: streamInfo.height,
                frameRate: streamInfo.frameRate
            }));
        } catch (error) {
            if (this.window === currentWindow) {
                await this._stopWorker();
            }
            throw error;
        }
    }

    async _resolveRequestedSource(workerGeneration) {
        if (workerGeneration !== this.generation || !this.requestedDisplay) {
            return null;
        }
        const requestedDisplay = this.requestedDisplay;
        const sources = await this.desktopCapturer.getSources({
            types: ['screen'],
            thumbnailSize: { width: 0, height: 0 }
        });
        if (
            workerGeneration !== this.generation
            || this.requestedDisplay !== requestedDisplay
        ) {
            return null;
        }
        return selectDisplaySource(
            sources,
            requestedDisplay,
            this.getDisplays()
        );
    }

    _invoke(window, method, payload = {}, userGesture = false) {
        if (!isWindowAlive(window) || window.webContents.isDestroyed()) {
            return Promise.reject(new Error('The persistent capture worker is unavailable.'));
        }
        return window.webContents.executeJavaScript(
            workerInvocation(method, payload),
            userGesture
        );
    }
}

module.exports = {
    CAPTURE_LIFECYCLE_ERROR_CODE,
    ScreenCaptureLifecycleError,
    ScreenCaptureRuntime,
    displayCaptureKey,
    isScreenCaptureLifecycleError,
    selectDisplaySource,
    workerInvocation
};
