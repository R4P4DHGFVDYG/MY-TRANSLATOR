const test = require('node:test');
const assert = require('node:assert/strict');

const { createLatestFrameScheduler, largestFittingFontSize } = require('./text_fit');

test('keeps the preferred font size when the text fits', () => {
    assert.equal(largestFittingFontSize(24, 6, size => size <= 24), 24);
});

test('chooses the largest half-pixel size that fits', () => {
    assert.equal(largestFittingFontSize(24, 6, size => size <= 13.7), 13.5);
});

test('uses the minimum when even the minimum overflows', () => {
    assert.equal(largestFittingFontSize(18, 7, () => false), 7);
});

test('handles invalid sizing values without returning NaN', () => {
    assert.equal(largestFittingFontSize('invalid', 'invalid', size => size <= 12), 12);
});

test('does not test sizes outside the requested range', () => {
    const tested = [];
    const result = largestFittingFontSize(10, 12, size => {
        tested.push(size);
        return true;
    });
    assert.equal(result, 10);
    assert.ok(tested.every(size => size === 10));
});

test('coalesces frequent text updates into the latest animation frame', () => {
    const callbacks = new Map();
    const cancelled = [];
    let nextId = 0;
    let runs = 0;
    const scheduler = createLatestFrameScheduler(
        callback => {
            nextId += 1;
            callbacks.set(nextId, callback);
            return nextId;
        },
        id => {
            cancelled.push(id);
            callbacks.delete(id);
        },
        () => {
            runs += 1;
        }
    );

    scheduler.schedule();
    scheduler.schedule();
    scheduler.schedule();
    assert.deepEqual(cancelled, [1, 2]);
    assert.equal(callbacks.size, 1);
    callbacks.get(3)();
    assert.equal(runs, 1);
});
