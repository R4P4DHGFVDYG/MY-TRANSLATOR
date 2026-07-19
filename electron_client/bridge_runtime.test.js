'use strict';

const test = require('node:test');
const assert = require('node:assert/strict');
const { EventEmitter } = require('node:events');
const path = require('node:path');
const {
    BridgeRuntime,
    resolveBridgeLaunch,
    terminateOwnedProcess
} = require('./bridge_runtime');

const silentLogger = {
    info() {},
    warn() {},
    error() {}
};

function developmentLayout() {
    const baseDir = path.join('C:\\repo', 'electron_client');
    const bridgeDir = path.resolve(baseDir, '..', 'bridge');
    const python = path.join(bridgeDir, '.venv', 'Scripts', 'python.exe');
    const existing = new Set([
        path.join(bridgeDir, 'hq_ocr_bridge', '__main__.py'),
        python
    ]);
    return {
        baseDir,
        bridgeDir,
        python,
        existsSync: candidate => existing.has(path.normalize(candidate))
    };
}

function readyResponse(ready) {
    return {
        json: async () => ({ ready, warnings: [] })
    };
}

function fakeChild(pid = 4321) {
    const child = new EventEmitter();
    child.pid = pid;
    child.stdout = null;
    child.stderr = null;
    child.killed = false;
    child.kill = () => {
        child.killed = true;
    };
    return child;
}

test('resolves the development bridge virtual environment', () => {
    const layout = developmentLayout();

    const launch = resolveBridgeLaunch({
        baseDir: layout.baseDir,
        resourcesPath: 'C:\\resources',
        env: {},
        platform: 'win32',
        existsSync: layout.existsSync
    });

    assert.equal(launch.command, layout.python);
    assert.equal(launch.cwd, layout.bridgeDir);
    assert.deepEqual(launch.args, ['-m', 'hq_ocr_bridge']);
});

test('resolves the self-contained bridge from packaged resources', () => {
    const baseDir = path.join('C:\\Program Files', 'GRC Translator', 'resources', 'app.asar');
    const resourcesPath = path.join('C:\\Program Files', 'GRC Translator', 'resources');
    const bridgeDir = path.join(resourcesPath, 'bridge');
    const executable = path.join(bridgeDir, 'hq-ocr-bridge.exe');
    const easyOcrModelDir = path.join(bridgeDir, '.EasyOCR', 'model');
    const existing = new Set([executable, easyOcrModelDir].map(path.normalize));

    const launch = resolveBridgeLaunch({
        baseDir,
        resourcesPath,
        env: {},
        platform: 'win32',
        existsSync: candidate => existing.has(path.normalize(candidate))
    });

    assert.equal(launch.command, executable);
    assert.equal(launch.cwd, bridgeDir);
    assert.deepEqual(launch.args, []);
    assert.equal(launch.env.HQ_OCR_EASYOCR_MODEL_DIR, easyOcrModelDir);
});

test('reuses a bridge that is already running without spawning another process', async () => {
    let spawnCalls = 0;
    const runtime = new BridgeRuntime({
        baseDir: 'C:\\repo\\electron_client',
        fetchImpl: async () => readyResponse(true),
        spawnImpl: () => {
            spawnCalls += 1;
        },
        logger: silentLogger
    });

    const status = await runtime.start();

    assert.equal(status.state, 'ready');
    assert.equal(status.source, 'external');
    assert.equal(spawnCalls, 0);
});

test('starts the local bridge and reports warming while its port opens', async () => {
    const layout = developmentLayout();
    const child = fakeChild();
    const spawnCalls = [];
    const terminated = [];
    const runtime = new BridgeRuntime({
        baseDir: layout.baseDir,
        env: { CUSTOM_SETTING: 'kept', HQ_OCR_OWNER_PID: '9999' },
        ownerPid: 2468,
        platform: 'win32',
        existsSync: layout.existsSync,
        fetchImpl: async () => {
            throw new Error('offline');
        },
        spawnImpl: (command, args, options) => {
            spawnCalls.push({ command, args, options });
            return child;
        },
        terminateProcessTree: (processToStop, platform) => {
            terminated.push({ processToStop, platform });
        },
        logger: silentLogger
    });

    const started = await runtime.start();
    const warming = await runtime.checkStatus(10);

    assert.equal(started.state, 'starting');
    assert.equal(started.owned, true);
    assert.equal(warming.state, 'warming');
    assert.equal(spawnCalls.length, 1);
    assert.equal(spawnCalls[0].command, layout.python);
    assert.deepEqual(spawnCalls[0].args, ['-m', 'hq_ocr_bridge']);
    assert.equal(spawnCalls[0].options.cwd, layout.bridgeDir);
    assert.equal(spawnCalls[0].options.shell, false);
    assert.equal(spawnCalls[0].options.windowsHide, true);
    assert.equal(spawnCalls[0].options.env.CUSTOM_SETTING, 'kept');
    assert.equal(spawnCalls[0].options.env.HQ_OCR_OWNER_PID, '2468');
    assert.equal(spawnCalls[0].options.env.PYTHONUNBUFFERED, '1');

    runtime.stop();
    runtime.stop();
    assert.deepEqual(terminated, [{ processToStop: child, platform: 'win32' }]);
});

test('waits for the owned Windows process tree to terminate', () => {
    const child = fakeChild(7654);
    const calls = [];

    terminateOwnedProcess(child, 'win32', (command, args, options) => {
        calls.push({ command, args, options });
        return { status: 0 };
    });

    assert.equal(calls.length, 1);
    assert.equal(calls[0].command, 'taskkill');
    assert.deepEqual(calls[0].args, ['/pid', '7654', '/T', '/F']);
    assert.equal(calls[0].options.shell, false);
    assert.equal(calls[0].options.windowsHide, true);
    assert.equal(calls[0].options.stdio, 'ignore');
    assert.equal(calls[0].options.timeout, 5000);
    assert.equal(child.killed, false);
});

test('falls back to killing the bridge parent when taskkill fails', () => {
    const child = fakeChild(8765);

    terminateOwnedProcess(child, 'win32', () => ({ status: 1 }));

    assert.equal(child.killed, true);
});

test('does not terminate a manually started bridge when Electron exits', async () => {
    let terminateCalls = 0;
    const runtime = new BridgeRuntime({
        baseDir: 'C:\\repo\\electron_client',
        fetchImpl: async () => readyResponse(false),
        terminateProcessTree: () => {
            terminateCalls += 1;
        },
        logger: silentLogger
    });

    const status = await runtime.start();
    runtime.stop();

    assert.equal(status.state, 'warming');
    assert.equal(status.source, 'external');
    assert.equal(terminateCalls, 0);
});
