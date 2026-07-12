'use strict';

const test = require('node:test');
const assert = require('node:assert/strict');
const { FixedAreaChangeTracker, rectanglesOverlap, toastSizeForFixedArea } = require('./fixed_area');

test('fixed area ignores unchanged images and accepts a later change', () => {
    const tracker = new FixedAreaChangeTracker();

    assert.equal(tracker.updateDigest('frame-a'), true);
    assert.equal(tracker.updateDigest('frame-a'), false);
    assert.equal(tracker.updateDigest('frame-b'), true);
});

test('fixed area does not display the same recognized text twice', () => {
    const tracker = new FixedAreaChangeTracker();

    assert.equal(tracker.updateText(' New subtitle '), true);
    assert.equal(tracker.updateText('New subtitle'), false);
    assert.equal(tracker.updateText(''), false);
    assert.equal(tracker.updateText('New subtitle'), true);
});

test('overlap detection distinguishes intersecting and separate windows', () => {
    const monitored = { x: 100, y: 100, width: 300, height: 120 };

    assert.equal(
        rectanglesOverlap(monitored, { x: 350, y: 150, width: 200, height: 100 }),
        true
    );
    assert.equal(
        rectanglesOverlap(monitored, { x: 100, y: 240, width: 200, height: 100 }),
        false
    );
});

test('translation window follows the active fixed-area size', () => {
    const display = { id: 7 };
    const workArea = { width: 1920, height: 1040 };
    const defaultSize = { width: 600, height: 200 };
    const region = {
        displayId: 7,
        selection: { width: 940, height: 180 }
    };

    assert.deepEqual(
        toastSizeForFixedArea(region, display, workArea, defaultSize),
        { width: 940, height: 180 }
    );
    assert.deepEqual(
        toastSizeForFixedArea(null, display, workArea, defaultSize),
        defaultSize
    );
});

test('translation window is limited to the monitor work area', () => {
    const display = { id: 2 };
    const region = {
        displayId: 2,
        selection: { width: 3000, height: 1400 }
    };

    assert.deepEqual(
        toastSizeForFixedArea(region, display, { width: 1366, height: 728 }, { width: 600, height: 200 }),
        { width: 1366, height: 728 }
    );
});
