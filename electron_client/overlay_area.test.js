'use strict';

const test = require('node:test');
const assert = require('node:assert/strict');
const {
    MIN_OVERLAY_HEIGHT,
    MIN_OVERLAY_WIDTH,
    initialOverlayEditorLayout,
    parseOverlayRegion,
    regionFromWindowBounds,
    resolveOverlayRegion,
    serializeOverlayRegion
} = require('./overlay_area');

const displays = [
    {
        id: 1,
        scaleFactor: 1,
        bounds: { x: 0, y: 0, width: 1920, height: 1080 },
        workArea: { x: 0, y: 0, width: 1920, height: 1040 }
    },
    {
        id: 2,
        scaleFactor: 1.5,
        bounds: { x: -1707, y: -120, width: 1707, height: 960 },
        workArea: { x: -1707, y: -120, width: 1707, height: 920 }
    }
];

function region(displayId, selection, displayBounds) {
    return {
        displayId,
        ...(displayBounds ? { displayBounds } : {}),
        selection
    };
}

test('configured overlay can be smaller than the capture area', () => {
    const overlay = region(1, { x: 100, y: 80, width: 420, height: 120 });
    const capture = region(1, { x: 20, y: 20, width: 1200, height: 360 });
    const layout = initialOverlayEditorLayout({
        overlayRegion: overlay,
        captureRegion: capture,
        displays
    });

    assert.equal(layout.source, 'overlay');
    assert.deepEqual(layout.bounds, { x: 100, y: 80, width: 420, height: 120 });
});

test('configured overlay can be larger than the capture area', () => {
    const overlay = region(1, { x: 40, y: 60, width: 1500, height: 500 });
    const capture = region(1, { x: 100, y: 100, width: 500, height: 120 });
    const layout = initialOverlayEditorLayout({
        overlayRegion: overlay,
        captureRegion: capture,
        displays
    });

    assert.equal(layout.source, 'overlay');
    assert.deepEqual(layout.bounds, { x: 40, y: 60, width: 1500, height: 500 });
});

test('capture area remains the fallback when no overlay was configured', () => {
    const capture = region(1, { x: 240, y: 700, width: 960, height: 180 });
    const layout = initialOverlayEditorLayout({ captureRegion: capture, displays });

    assert.equal(layout.source, 'capture');
    assert.deepEqual(layout.bounds, { x: 240, y: 700, width: 960, height: 180 });
});

test('overlay on a secondary monitor preserves negative DIP coordinates', () => {
    const overlay = region(2, { x: 107, y: 120, width: 900, height: 200 });
    const resolved = resolveOverlayRegion(overlay, displays);

    assert.equal(resolved.display.id, 2);
    assert.deepEqual(resolved.bounds, { x: -1600, y: 0, width: 900, height: 200 });
    assert.equal(resolved.bounds.width, 900, 'scaleFactor must not be applied to window bounds');
});

test('saved region is clamped after a display resolution change', () => {
    const overlay = region(
        2,
        { x: 1300, y: 760, width: 900, height: 300 },
        displays[1].bounds
    );
    const resizedDisplay = {
        id: 2,
        scaleFactor: 2,
        bounds: { x: -1280, y: 0, width: 1280, height: 720 },
        workArea: { x: -1280, y: 0, width: 1280, height: 680 }
    };
    const resolved = resolveOverlayRegion(overlay, [displays[0], resizedDisplay]);

    assert.deepEqual(resolved.bounds, { x: -900, y: 420, width: 900, height: 300 });
});

test('saved bounds remap to the closest display when its id changes', () => {
    const savedBounds = { x: -1707, y: -120, width: 1707, height: 960 };
    const overlay = region(99, { x: 100, y: 100, width: 600, height: 160 }, savedBounds);
    const resolved = resolveOverlayRegion(overlay, displays);

    assert.equal(resolved.display.id, 2);
    assert.deepEqual(resolved.bounds, { x: -1607, y: -20, width: 600, height: 160 });
});

test('window bounds are stored relative to their monitor in DIP', () => {
    const stored = regionFromWindowBounds(
        { x: -1500, y: 20, width: 640, height: 170 },
        displays[1]
    );

    assert.deepEqual(stored.selection, { x: 207, y: 140, width: 640, height: 170 });
    assert.equal(stored.displayId, 2);
});

test('minimum editor size remains visible and usable', () => {
    const stored = regionFromWindowBounds(
        { x: 20, y: 20, width: 20, height: 20 },
        displays[0]
    );

    assert.equal(stored.selection.width, MIN_OVERLAY_WIDTH);
    assert.equal(stored.selection.height, MIN_OVERLAY_HEIGHT);
});

test('serialized overlay survives restart and invalid data is ignored', () => {
    const original = region(
        2,
        { x: 207, y: 140, width: 640, height: 170 },
        displays[1].bounds
    );

    assert.deepEqual(parseOverlayRegion(serializeOverlayRegion(original)), original);
    assert.equal(parseOverlayRegion('{not-json'), null);
    assert.equal(parseOverlayRegion(JSON.stringify({ displayId: 1, selection: { width: -1 } })), null);
});
