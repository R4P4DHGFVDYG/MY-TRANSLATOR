'use strict';

const test = require('node:test');
const assert = require('node:assert/strict');
const {
    FixedAreaChangeTracker,
    rectanglesOverlap,
    temporalTextSimilarity,
    toastSizeForFixedArea
} = require('./fixed_area');

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

test('fixed area confirms a low-confidence OCR result before displaying it', () => {
    const tracker = new FixedAreaChangeTracker();

    assert.deepEqual(tracker.evaluateText('Possibly wrong', 0.55), {
        display: false,
        retry: true
    });
    tracker.updateDigest('frame-a');
    tracker.retryCurrentFrame();
    assert.equal(tracker.updateDigest('frame-a'), true);
    assert.deepEqual(tracker.evaluateText('Possibly wrong', 0.55), {
        display: true,
        retry: false
    });
});

test('fixed area displays a strong OCR result immediately', () => {
    const tracker = new FixedAreaChangeTracker();

    assert.deepEqual(tracker.evaluateText('Reliable subtitle', 0.9), {
        display: true,
        retry: false
    });
});

test('fixed area accepts similar low-confidence readings as temporal consensus', () => {
    const tracker = new FixedAreaChangeTracker();

    assert.deepEqual(tracker.evaluateText('So what, dumbass? Follow her.', 0.55), {
        display: false,
        retry: true
    });
    assert.deepEqual(tracker.evaluateText('S0 what, dumbass? Follow her.', 0.58), {
        display: true,
        retry: false
    });
});

test('fixed area requires consecutive consensus for unrelated weak readings', () => {
    const tracker = new FixedAreaChangeTracker();

    assert.deepEqual(tracker.evaluateText('First uncertain subtitle', 0.5), {
        display: false,
        retry: true
    });
    assert.deepEqual(tracker.evaluateText('Completely different reading', 0.5), {
        display: false,
        retry: true
    });
    assert.deepEqual(tracker.evaluateText('First uncertain subtitle', 0.5), {
        display: false,
        retry: true
    });
});

test('fixed area clears a pending candidate when the displayed text returns', () => {
    const tracker = new FixedAreaChangeTracker();

    tracker.evaluateText('Current subtitle', 0.9);
    tracker.evaluateText('Possible next subtitle', 0.5);
    assert.deepEqual(tracker.evaluateText('CURRENT SUBTITLE!', 0.5), {
        display: false,
        retry: false
    });
    assert.deepEqual(tracker.evaluateText('Possible next subtitle', 0.5), {
        display: false,
        retry: true
    });
});

test('temporal similarity tolerates isolated OCR substitutions', () => {
    assert.ok(temporalTextSimilarity('subtitle text here', 'subtit1e text here') >= 0.86);
    assert.ok(temporalTextSimilarity('subtitle text here', 'different sentence') < 0.86);
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
