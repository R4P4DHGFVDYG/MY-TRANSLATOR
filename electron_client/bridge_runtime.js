'use strict';

const fs = require('fs');
const path = require('path');
const { spawn: spawnProcess } = require('child_process');

const DEFAULT_READY_URL = 'http://127.0.0.1:8765/ready';
const STARTUP_PROBE_TIMEOUT_MS = 650;
const MAX_BUFFERED_LOG_CHARS = 8192;

function resolveBridgeLaunch(options = {}) {
    const baseDir = options.baseDir;
    const resourcesPath = options.resourcesPath || '';
    const env = options.env || process.env;
    const platform = options.platform || process.platform;
    const existsSync = options.existsSync || fs.existsSync;
    if (!baseDir) {
        throw new Error('Electron base directory is required to locate the OCR Bridge');
    }

    const explicitBridgeDir = String(env.HQ_OCR_BRIDGE_DIR || '').trim();
    const bridgeCandidates = uniquePaths([
        explicitBridgeDir ? path.resolve(explicitBridgeDir) : '',
        path.resolve(baseDir, '..', 'bridge'),
        resourcesPath ? path.join(resourcesPath, 'bridge') : ''
    ]);
    const packagedExecutableName = platform === 'win32'
        ? 'hq-ocr-bridge.exe'
        : 'hq-ocr-bridge';
    const bridgeLayout = bridgeCandidates
        .map(bridgeDir => ({
            bridgeDir,
            packagedExecutable: path.join(bridgeDir, packagedExecutableName),
            sourceEntrypoint: path.join(bridgeDir, 'hq_ocr_bridge', '__main__.py')
        }))
        .find(layout => (
            existsSync(layout.packagedExecutable)
            || existsSync(layout.sourceEntrypoint)
        ));
    if (!bridgeLayout) {
        throw new Error('OCR Bridge files were not found beside the Electron application');
    }

    const { bridgeDir } = bridgeLayout;
    if (existsSync(bridgeLayout.packagedExecutable)) {
        const bundledEasyOcrModelDir = path.join(bridgeDir, '.EasyOCR', 'model');
        const launchEnv = {};
        if (
            !String(env.HQ_OCR_EASYOCR_MODEL_DIR || '').trim()
            && existsSync(bundledEasyOcrModelDir)
        ) {
            launchEnv.HQ_OCR_EASYOCR_MODEL_DIR = bundledEasyOcrModelDir;
        }
        return {
            command: bridgeLayout.packagedExecutable,
            args: [],
            cwd: bridgeDir,
            env: launchEnv
        };
    }

    const explicitPython = String(env.HQ_OCR_BRIDGE_PYTHON || '').trim();
    let command = '';
    if (explicitPython) {
        command = resolveExplicitCommand(explicitPython, bridgeDir, existsSync);
    } else {
        const virtualEnvironmentPython = platform === 'win32'
            ? path.join(bridgeDir, '.venv', 'Scripts', 'python.exe')
            : path.join(bridgeDir, '.venv', 'bin', 'python');
        const bundledPython = resourcesPath
            ? path.join(
                resourcesPath,
                'python',
                platform === 'win32' ? 'python.exe' : 'bin/python3'
            )
            : '';
        command = [virtualEnvironmentPython, bundledPython]
            .find(candidate => candidate && existsSync(candidate))
            || (platform === 'win32' ? 'python' : 'python3');
    }

    return {
        command,
        args: ['-m', 'hq_ocr_bridge'],
        cwd: bridgeDir
    };
}

function resolveExplicitCommand(value, bridgeDir, existsSync) {
    const pathLike = path.isAbsolute(value) || value.includes('/') || value.includes('\\');
    if (!pathLike) {
        return value;
    }

    const resolved = path.isAbsolute(value) ? value : path.resolve(bridgeDir, value);
    if (!existsSync(resolved)) {
        throw new Error(`Configured Python executable was not found: ${resolved}`);
    }
    return resolved;
}

function uniquePaths(values) {
    return [...new Set(values.filter(Boolean).map(value => path.normalize(value)))];
}

class BridgeRuntime {
    constructor(options = {}) {
        this.baseDir = options.baseDir;
        this.resourcesPath = options.resourcesPath || '';
        this.readyUrl = options.readyUrl || DEFAULT_READY_URL;
        this.env = options.env || process.env;
        this.platform = options.platform || process.platform;
        this.existsSync = options.existsSync || fs.existsSync;
        this.fetchImpl = options.fetchImpl || globalThis.fetch;
        this.spawnImpl = options.spawnImpl || spawnProcess;
        this.terminateProcessTree = options.terminateProcessTree
            || terminateOwnedProcess;
        this.logger = options.logger || console;
        this.child = null;
        this.source = 'none';
        this.state = 'idle';
        this.lastError = '';
        this.warnings = [];
        this.startPromise = null;
        this.stopping = false;
    }

    async start() {
        if (this.stopping || this.child) {
            return this.snapshot();
        }
        if (this.source === 'external' && ['ready', 'warming'].includes(this.state)) {
            return this.snapshot();
        }
        if (this.startPromise) {
            return this.startPromise;
        }

        this.startPromise = this._startOnce();
        try {
            return await this.startPromise;
        } finally {
            this.startPromise = null;
        }
    }

    async _startOnce() {
        this.state = 'probing';
        const existing = await this._probe(STARTUP_PROBE_TIMEOUT_MS);
        if (this.stopping) {
            return this.snapshot();
        }
        if (existing.reachable) {
            this.source = 'external';
            this.state = existing.ready ? 'ready' : 'warming';
            this.warnings = existing.warnings;
            this.lastError = '';
            this._log('info', '[bridge] Reusing OCR Bridge already running.');
            return this.snapshot();
        }

        let launch;
        try {
            launch = resolveBridgeLaunch({
                baseDir: this.baseDir,
                resourcesPath: this.resourcesPath,
                env: this.env,
                platform: this.platform,
                existsSync: this.existsSync
            });
        } catch (error) {
            this.state = 'offline';
            this.lastError = error instanceof Error ? error.message : String(error);
            this._log('error', `[bridge] ${this.lastError}`);
            return this.snapshot();
        }

        let child = null;
        try {
            child = this.spawnImpl(launch.command, launch.args, {
                cwd: launch.cwd,
                env: {
                    ...this.env,
                    ...(launch.env || {}),
                    PYTHONUNBUFFERED: '1'
                },
                shell: false,
                windowsHide: true,
                stdio: ['ignore', 'pipe', 'pipe']
            });
            if (!child || typeof child.once !== 'function') {
                throw new Error('Python process did not start correctly');
            }
            this.child = child;
            this.source = 'owned';
            this.state = 'starting';
            this.lastError = '';
            this.warnings = [];
            this._observeChild(child, launch);
        } catch (error) {
            this.child = null;
            this.state = 'offline';
            this.source = 'none';
            this.lastError = error instanceof Error ? error.message : String(error);
            this._log('error', `[bridge] Failed to start OCR Bridge: ${this.lastError}`);
            safeKill(child);
        }
        return this.snapshot();
    }

    async checkStatus(timeoutMs = 1500) {
        const status = await this._probe(timeoutMs);
        if (status.reachable) {
            if (this.source === 'none') {
                this.source = 'external';
            }
            this.state = status.ready ? 'ready' : 'warming';
            this.warnings = status.warnings;
            this.lastError = '';
            return this.snapshot();
        }

        if (this.child) {
            this.state = 'warming';
            return this.snapshot();
        }

        if (!this.stopping) {
            this.source = 'none';
            this.state = 'offline';
        }
        return this.snapshot();
    }

    stop() {
        this.stopping = true;
        const ownedChild = this.source === 'owned' ? this.child : null;
        this.child = null;
        this.source = 'none';
        this.state = 'stopped';
        if (!ownedChild) {
            return;
        }

        try {
            this.terminateProcessTree(ownedChild, this.platform);
        } catch (error) {
            this._log('warn', `[bridge] Could not stop OCR Bridge cleanly: ${error}`);
            safeKill(ownedChild);
        }
    }

    snapshot() {
        return {
            state: this.state,
            source: this.source,
            ready: this.state === 'ready',
            owned: this.source === 'owned',
            error: this.lastError,
            warnings: [...this.warnings]
        };
    }

    async _probe(timeoutMs) {
        if (typeof this.fetchImpl !== 'function') {
            return { reachable: false, ready: false, warnings: [] };
        }

        const controller = new AbortController();
        const timeoutId = setTimeout(() => controller.abort(), timeoutMs);
        try {
            const response = await this.fetchImpl(this.readyUrl, {
                signal: controller.signal
            });
            const payload = await response.json().catch(() => null);
            if (!payload || typeof payload.ready !== 'boolean') {
                return { reachable: false, ready: false, warnings: [] };
            }
            return {
                reachable: true,
                ready: payload.ready,
                warnings: Array.isArray(payload.warnings) ? payload.warnings : []
            };
        } catch {
            return { reachable: false, ready: false, warnings: [] };
        } finally {
            clearTimeout(timeoutId);
        }
    }

    _observeChild(child, launch) {
        forwardProcessOutput(child.stdout, line => this._log('info', `[bridge] ${line}`));
        forwardProcessOutput(child.stderr, line => this._log('warn', `[bridge] ${line}`));

        child.once('spawn', () => {
            this._log('info', `[bridge] Started with ${launch.command}.`);
        });
        child.once('error', error => {
            if (this.child !== child) {
                return;
            }
            this.child = null;
            this.source = 'none';
            this.state = 'offline';
            this.lastError = error instanceof Error ? error.message : String(error);
            this._log('error', `[bridge] OCR Bridge process error: ${this.lastError}`);
        });
        child.once('exit', (code, signal) => {
            if (this.child !== child) {
                return;
            }
            this.child = null;
            this.source = 'none';
            this.state = this.stopping ? 'stopped' : 'offline';
            if (!this.stopping) {
                this.lastError = `OCR Bridge exited (code ${code}, signal ${signal || 'none'})`;
                this._log('warn', `[bridge] ${this.lastError}`);
            }
        });
    }

    _log(level, message) {
        const method = this.logger?.[level] || this.logger?.log;
        if (typeof method === 'function') {
            method.call(this.logger, message);
        }
    }
}

function forwardProcessOutput(stream, onLine) {
    if (!stream || typeof stream.on !== 'function') {
        return;
    }

    let buffered = '';
    stream.on('data', chunk => {
        buffered += String(chunk);
        if (buffered.length > MAX_BUFFERED_LOG_CHARS) {
            buffered = buffered.slice(-MAX_BUFFERED_LOG_CHARS);
        }
        const lines = buffered.split(/\r?\n/);
        buffered = lines.pop() || '';
        for (const line of lines) {
            if (line.trim()) {
                onLine(line);
            }
        }
    });
    stream.on('end', () => {
        if (buffered.trim()) {
            onLine(buffered);
        }
        buffered = '';
    });
}

function terminateOwnedProcess(child, platform = process.platform) {
    if (platform !== 'win32' || !Number.isInteger(child?.pid)) {
        safeKill(child);
        return;
    }

    let killer;
    try {
        killer = spawnProcess(
            'taskkill',
            ['/pid', String(child.pid), '/T', '/F'],
            {
                shell: false,
                windowsHide: true,
                stdio: 'ignore'
            }
        );
    } catch {
        safeKill(child);
        return;
    }
    killer.once('error', () => safeKill(child));
    killer.once('exit', code => {
        if (code !== 0) {
            safeKill(child);
        }
    });
}

function safeKill(child) {
    if (!child || typeof child.kill !== 'function' || child.killed) {
        return;
    }
    try {
        child.kill();
    } catch {
        // The process may have exited between the status check and termination.
    }
}

module.exports = {
    BridgeRuntime,
    resolveBridgeLaunch,
    terminateOwnedProcess
};
