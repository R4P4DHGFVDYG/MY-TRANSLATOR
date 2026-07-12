const test = require('node:test');
const assert = require('node:assert/strict');
const { resolveOcrEngines } = require('./ocr_profile');

test('automatic profile combines complementary OCR engines', () => {
    assert.deepEqual(resolveOcrEngines('auto'), ['tesseract', 'paddleocr']);
});

test('individual OCR profiles request only their selected engine', () => {
    assert.deepEqual(resolveOcrEngines('easyocr'), ['easyocr']);
    assert.deepEqual(resolveOcrEngines('unknown'), ['tesseract']);
});
