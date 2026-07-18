'use strict';

const test = require('node:test');
const assert = require('node:assert/strict');
const { EventEmitter } = require('node:events');
const {
    ScreenCaptureLifecycleError,
    ScreenCaptureRuntime,
    displayCaptureKey,
    isScreenCaptureLifecycleError,
    selectDisplaySource,
    workerInvocation
} = require('./screen_capture');

class FakeSession {
    setDisplayMediaRequestHandler(handler) {
        this.displayMediaHandler = handler;
    }
}

class FakeWebContents extends EventEmitter {
    constructor() {
        super();
        this.session = new FakeSession();
        this.calls = [];
        this.snapshotCounter = 0;
    }

    setWindowOpenHandler(handler) {
        this.windowOpenHandler = handler;
    }

    isDestroyed() {
        return false;
    }

    async executeJavaScript(source, userGesture) {
        this.calls.push({ source, userGesture });
        if (source.includes('"start"')) {
            return { width: 1920, height: 1080, frameRate: 8 };
        }
        if (source.includes('"capture"')) {
            this.snapshotCounter += 1;
            return {
                snapshotId: `snapshot-${this.snapshotCounter}`,
                width: 640,
                height: 180,
                signature: [10, 20, 30, 40],
                captureMs: 2.5,
                signatureMs: 0.5,
                cropPixels: 115200
            };
        }
        if (source.includes('"encode"')) {
            return {
                dataUrl: 'data:image/png;base64,AAAA',
                digest: 'a'.repeat(64),
                encodedBytes: 4,
                encodeMs: 3,
                width: 640,
                height: 180
            };
        }
        return true;
    }
}

class FakeBrowserWindow extends EventEmitter {
    static instances = [];

    constructor(options) {
        super();
        this.options = options;
        this.webContents = new FakeWebContents();
        this.destroyed = false;
        FakeBrowserWindow.instances.push(this);
    }

    isDestroyed() {
        return this.destroyed;
    }

    async loadFile(filePath) {
        this.filePath = filePath;
    }

    destroy() {
        this.destroyed = true;
        this.emit('closed');
    }
}

class DeferredBrowserWindow extends FakeBrowserWindow {
    static resolveLoad = null;

    async loadFile(filePath) {
        this.filePath = filePath;
        await new Promise(resolve => {
            DeferredBrowserWindow.resolveLoad = resolve;
        });
    }
}

class SequencedDeferredBrowserWindow extends FakeBrowserWindow {
    static pendingLoads = [];

    async loadFile(filePath) {
        this.filePath = filePath;
        await new Promise(resolve => {
            SequencedDeferredBrowserWindow.pendingLoads.push({
                window: this,
                resolve
            });
        });
    }
}

class DeferredCaptureWebContents extends FakeWebContents {
    async executeJavaScript(source, userGesture) {
        if (!source.includes('"capture"')) {
            return super.executeJavaScript(source, userGesture);
        }
        this.calls.push({ source, userGesture });
        return new Promise(resolve => {
            DeferredFirstCaptureBrowserWindow.resolveCapture = () => resolve({
                snapshotId: 'delayed-snapshot',
                width: 640,
                height: 180,
                signature: [10, 20, 30, 40],
                captureMs: 2.5,
                signatureMs: 0.5,
                cropPixels: 115200
            });
        });
    }
}

class DeferredFirstCaptureBrowserWindow extends FakeBrowserWindow {
    static resolveCapture = null;

    constructor(options) {
        super(options);
        if (FakeBrowserWindow.instances.length === 1) {
            this.webContents = new DeferredCaptureWebContents();
        }
    }
}

async function waitFor(predicate, message = 'Timed out waiting for test state.') {
    for (let attempt = 0; attempt < 100; attempt += 1) {
        if (predicate()) {
            return;
        }
        await new Promise(resolve => setImmediate(resolve));
    }
    assert.fail(message);
}

function createRuntime(overrides = {}) {
    const sources = [
        { id: 'screen:1:0', display_id: '1' },
        { id: 'screen:2:0', display_id: '2' }
    ];
    const desktopCapturer = {
        calls: [],
        async getSources(options) {
            this.calls.push(options);
            return sources;
        }
    };
    const displays = [
        { id: 1, bounds: { x: 0, y: 0, width: 1920, height: 1080 }, scaleFactor: 1 },
        { id: 2, bounds: { x: 1920, y: 0, width: 1920, height: 1080 }, scaleFactor: 1 }
    ];
    const runtime = new ScreenCaptureRuntime({
        BrowserWindow: FakeBrowserWindow,
        desktopCapturer,
        getDisplays: () => displays,
        logger: { info() {}, warn() {} },
        ...overrides
    });
    return { desktopCapturer, displays, runtime, sources };
}

test.beforeEach(() => {
    FakeBrowserWindow.instances = [];
    DeferredBrowserWindow.resolveLoad = null;
    DeferredFirstCaptureBrowserWindow.resolveCapture = null;
    SequencedDeferredBrowserWindow.pendingLoads = [];
});

test('display source selection prefers the exact Windows display id', () => {
    const sources = [
        { id: 'screen:one', display_id: '100' },
        { id: 'screen:two', display_id: '200' }
    ];
    const displays = [{ id: 100 }, { id: 200 }];
    assert.equal(selectDisplaySource(sources, displays[1], displays), sources[1]);
    assert.equal(selectDisplaySource(sources, { id: 999 }, displays), sources[0]);
    assert.equal(selectDisplaySource([], displays[0], displays), null);
});

test('capture key changes with monitor geometry and DPI', () => {
    const display = {
        id: 7,
        bounds: { x: -1920, y: 0, width: 1920, height: 1080 },
        scaleFactor: 1.25
    };
    assert.equal(displayCaptureKey(display), '7:-1920:0:1920:1080:1.25');
});

test('worker invocation only exposes known operations and serializes payloads', () => {
    assert.equal(
        workerInvocation('release', { snapshotId: 'safe-id' }),
        'window.captureWorker.invoke("release", {"snapshotId":"safe-id"})'
    );
    assert.throws(() => workerInvocation('evaluate'), /Unsupported/);
});

test('lifecycle cancellation errors have a stable public discriminator', () => {
    const lifecycleError = new ScreenCaptureLifecycleError('capture changed');
    assert.equal(isScreenCaptureLifecycleError(lifecycleError), true);
    assert.equal(isScreenCaptureLifecycleError(new Error('capture failed')), false);
    assert.equal(lifecycleError.code, 'ERR_SCREEN_CAPTURE_LIFECYCLE');
});

test('persistent runtime reuses one stream and encodes snapshots outside main', async () => {
    const { desktopCapturer, displays, runtime, sources } = createRuntime();
    const selection = { x: 50, y: 100, width: 640, height: 180 };

    const first = await runtime.capture(selection, displays[0], {
        maxPixels: 12_000_000,
        signatureWidth: 32,
        signatureHeight: 18
    });
    const second = await runtime.capture(selection, displays[0]);

    assert.equal(FakeBrowserWindow.instances.length, 1);
    assert.equal(first.captureBackend, 'stream');
    assert.deepEqual([...first.frameSignature], [10, 20, 30, 40]);
    assert.equal(second.captureGeneration, first.captureGeneration);

    const captureWindow = FakeBrowserWindow.instances[0];
    const selectedSource = await new Promise(resolve => {
        captureWindow.webContents.session.displayMediaHandler({}, streams => resolve(streams.video));
    });
    assert.equal(selectedSource, sources[0]);
    assert.deepEqual(desktopCapturer.calls, [{
        types: ['screen'],
        thumbnailSize: { width: 0, height: 0 }
    }]);

    const encoded = await runtime.encode(first, { maxBytes: 1024 });
    assert.equal(encoded.base64, 'data:image/png;base64,AAAA');
    assert.equal(encoded.digest, 'a'.repeat(64));
    assert.equal(encoded.performance.backend, 'persistent-stream');
    assert.equal(runtime.release(second), true);

    await runtime.stop();
    assert.equal(captureWindow.destroyed, true);
});

test('a crashed capture renderer destroys its hidden window and session handler', async () => {
    const { displays, runtime } = createRuntime();
    const frame = await runtime.capture(
        { x: 0, y: 0, width: 320, height: 100 },
        displays[0]
    );
    const captureWindow = FakeBrowserWindow.instances[0];

    captureWindow.webContents.emit('render-process-gone', {}, { reason: 'crashed' });

    assert.equal(captureWindow.destroyed, true);
    assert.equal(captureWindow.webContents.session.displayMediaHandler, null);
    assert.equal(runtime.window, null);
    assert.equal(runtime.captureKey, '');
    assert.equal(runtime.requestedDisplay, null);
    assert.equal(runtime.owns(frame), false);
    await runtime.stop();
});

test('changing monitor replaces the persistent stream', async () => {
    const { displays, runtime } = createRuntime();
    const selection = { x: 0, y: 0, width: 320, height: 100 };

    const first = await runtime.capture(selection, displays[0]);
    const firstWindow = FakeBrowserWindow.instances[0];
    const second = await runtime.capture(selection, displays[1]);

    assert.equal(firstWindow.destroyed, true);
    assert.equal(FakeBrowserWindow.instances.length, 2);
    assert.notEqual(second.captureGeneration, first.captureGeneration);
    assert.equal(runtime.release(first), false);
    await assert.rejects(
        runtime.encode(first),
        error => isScreenCaptureLifecycleError(error)
    );
    await runtime.stop();
});

test('concurrent captures share a single stream startup', async () => {
    const { displays, runtime } = createRuntime();
    const selection = { x: 0, y: 0, width: 320, height: 100 };

    const [first, second] = await Promise.all([
        runtime.capture(selection, displays[0]),
        runtime.capture(selection, displays[0])
    ]);

    assert.equal(FakeBrowserWindow.instances.length, 1);
    assert.equal(first.captureGeneration, second.captureGeneration);
    runtime.release(first);
    runtime.release(second);
    await runtime.stop();
});

test('startups for concurrent requests on different displays stay serialized', async () => {
    const { displays, runtime } = createRuntime({
        BrowserWindow: SequencedDeferredBrowserWindow
    });
    const thirdDisplay = {
        id: 3,
        bounds: { x: 3840, y: 0, width: 1920, height: 1080 },
        scaleFactor: 1
    };
    const selection = { x: 0, y: 0, width: 320, height: 100 };
    const captures = [
        runtime.capture(selection, displays[0]),
        runtime.capture(selection, displays[1]),
        runtime.capture(selection, thirdDisplay)
    ];
    const settledCaptures = Promise.allSettled(captures);

    await waitFor(() => SequencedDeferredBrowserWindow.pendingLoads.length === 1);
    assert.equal(FakeBrowserWindow.instances.length, 1);
    SequencedDeferredBrowserWindow.pendingLoads.shift().resolve();

    await waitFor(() => SequencedDeferredBrowserWindow.pendingLoads.length >= 1);
    await new Promise(resolve => setImmediate(resolve));
    assert.equal(SequencedDeferredBrowserWindow.pendingLoads.length, 1);
    assert.equal(FakeBrowserWindow.instances.length, 2);
    SequencedDeferredBrowserWindow.pendingLoads.shift().resolve();

    await waitFor(() => SequencedDeferredBrowserWindow.pendingLoads.length >= 1);
    await new Promise(resolve => setImmediate(resolve));
    assert.equal(SequencedDeferredBrowserWindow.pendingLoads.length, 1);
    assert.equal(FakeBrowserWindow.instances.length, 3);
    SequencedDeferredBrowserWindow.pendingLoads.shift().resolve();

    const results = await settledCaptures;
    assert.equal(results[2].status, 'fulfilled');
    for (const result of results) {
        if (result.status === 'rejected') {
            assert.equal(isScreenCaptureLifecycleError(result.reason), true);
        }
    }
    assert.equal(runtime.starting, null);
    await runtime.stop();
});

test('a delayed frame from a replaced worker is rejected as lifecycle data', async () => {
    const { displays, runtime } = createRuntime({
        BrowserWindow: DeferredFirstCaptureBrowserWindow
    });
    const selection = { x: 0, y: 0, width: 320, height: 100 };
    const delayedCapture = runtime.capture(selection, displays[0]);

    await waitFor(() => Boolean(DeferredFirstCaptureBrowserWindow.resolveCapture));
    const currentCapture = await runtime.capture(selection, displays[1]);
    DeferredFirstCaptureBrowserWindow.resolveCapture();

    await assert.rejects(
        delayedCapture,
        error => isScreenCaptureLifecycleError(error)
    );
    assert.equal(runtime.owns(currentCapture), true);
    assert.notEqual(currentCapture.snapshotId, 'delayed-snapshot');
    runtime.release(currentCapture);
    await runtime.stop();
});

test('stopping during startup cannot leave a capture stream running', async () => {
    const { displays, runtime } = createRuntime({ BrowserWindow: DeferredBrowserWindow });
    const selection = { x: 0, y: 0, width: 320, height: 100 };
    const capturePromise = runtime.capture(selection, displays[0]);

    while (!DeferredBrowserWindow.resolveLoad) {
        await new Promise(resolve => setImmediate(resolve));
    }
    const stopPromise = runtime.stop();
    DeferredBrowserWindow.resolveLoad();

    await stopPromise;
    await assert.rejects(
        capturePromise,
        error => isScreenCaptureLifecycleError(error)
    );
    assert.equal(runtime.window, null);
    assert.equal(FakeBrowserWindow.instances.every(window => window.destroyed), true);
});
