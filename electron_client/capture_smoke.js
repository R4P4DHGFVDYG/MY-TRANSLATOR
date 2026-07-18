'use strict';

const assert = require('node:assert/strict');
const { app, BrowserWindow, desktopCapturer, screen } = require('electron');
const { ScreenCaptureRuntime } = require('./screen_capture');

async function run() {
    const runtime = new ScreenCaptureRuntime({
        BrowserWindow,
        desktopCapturer,
        baseDir: __dirname,
        getDisplays: () => screen.getAllDisplays(),
        maxFrameRate: 6
    });
    try {
        const display = screen.getPrimaryDisplay();
        const width = Math.min(480, display.bounds.width);
        const height = Math.min(180, display.bounds.height);
        const selection = {
            x: Math.max(0, Math.floor((display.bounds.width - width) / 2)),
            y: Math.max(0, Math.floor((display.bounds.height - height) / 2)),
            width,
            height
        };
        const first = await runtime.capture(selection, display, {
            maxPixels: 12_000_000,
            signatureWidth: 32,
            signatureHeight: 18
        });
        assert.equal(first.frameSignature.length, 32 * 18);
        assert.ok(first.width > 0);
        assert.ok(first.height > 0);

        const encoded = await runtime.encode(first, { maxBytes: 12 * 1024 * 1024 });
        assert.match(encoded.base64, /^data:image\/png;base64,/);
        assert.match(encoded.digest, /^[0-9a-f]{64}$/);
        assert.ok(encoded.performance.encodedBytes > 0);

        const second = await runtime.capture(selection, display, {
            maxPixels: 12_000_000,
            signatureWidth: 32,
            signatureHeight: 18
        });
        assert.equal(second.captureGeneration, first.captureGeneration);
        assert.equal(runtime.release(second), true);
        console.log('Persistent capture smoke test passed.');
    } finally {
        await runtime.stop();
    }
}

app.whenReady()
    .then(run)
    .then(() => app.quit())
    .catch(error => {
        console.error(error);
        app.exit(1);
    });
