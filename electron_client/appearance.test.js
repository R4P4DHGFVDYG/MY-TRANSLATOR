const test = require('node:test');
const assert = require('node:assert/strict');
const { normalizeFontFamily, normalizeFontSize, normalizeTextAlign } = require('./appearance');

test('accepts safe Windows font family names', () => {
    assert.equal(normalizeFontFamily('Segoe UI'), 'Segoe UI');
    assert.equal(normalizeFontFamily('Arial Nova Cond Light'), 'Arial Nova Cond Light');
});

test('rejects font family values that could escape CSS', () => {
    assert.equal(normalizeFontFamily('Arial; color: red'), null);
    assert.equal(normalizeFontFamily('Font { display: none }'), null);
    assert.equal(normalizeFontFamily(''), null);
});

test('clamps font size and validates text alignment', () => {
    assert.equal(normalizeFontSize(8), 12);
    assert.equal(normalizeFontSize(22.6), 23);
    assert.equal(normalizeFontSize(72), 36);
    assert.equal(normalizeFontSize('invalid'), null);
    assert.equal(normalizeTextAlign('center'), 'center');
    assert.equal(normalizeTextAlign('justify'), null);
});
