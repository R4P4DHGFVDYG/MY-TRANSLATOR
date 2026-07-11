const test = require('node:test');
const assert = require('node:assert/strict');
const { normalizeKeyboardAccelerator, normalizeCaptureShortcut } = require('./shortcut');

test('normalizes safe keyboard accelerators', () => {
    assert.equal(normalizeKeyboardAccelerator('Shift+Ctrl+q'), 'Ctrl+Shift+Q');
    assert.equal(normalizeKeyboardAccelerator('F8'), 'F8');
    assert.equal(normalizeKeyboardAccelerator('Alt+Space'), 'Alt+Space');
});

test('rejects unsafe or malformed keyboard accelerators', () => {
    assert.equal(normalizeKeyboardAccelerator('Q'), null);
    assert.equal(normalizeKeyboardAccelerator('Ctrl'), null);
    assert.equal(normalizeKeyboardAccelerator('Ctrl+Shift+Q+R'), null);
    assert.equal(normalizeKeyboardAccelerator('Ctrl+Escape'), null);
});

test('accepts only supported mouse buttons', () => {
    assert.deepEqual(normalizeCaptureShortcut('mouse', 'MBUTTON'), { type: 'mouse', value: 'MBUTTON' });
    assert.deepEqual(normalizeCaptureShortcut('mouse', 'XBUTTON2'), { type: 'mouse', value: 'XBUTTON2' });
    assert.equal(normalizeCaptureShortcut('mouse', 'LBUTTON'), null);
});
