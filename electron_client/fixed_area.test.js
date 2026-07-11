'use strict';

const test = require('node:test');
const assert = require('node:assert/strict');
const { FixedAreaChangeTracker, rectanglesOverlap } = require('./fixed_area');

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
