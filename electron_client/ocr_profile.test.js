const test = require('node:test');
const assert = require('node:assert/strict');
const { resolveOcrEngines, resolveOcrPreprocessing } = require('./ocr_profile');

test('automatic profile combines complementary OCR engines', () => {
    assert.deepEqual(resolveOcrEngines('auto'), ['tesseract', 'windowsocr', 'paddleocr']);
    assert.deepEqual(resolveOcrEngines('auto8bit'), ['tesseract', 'windowsocr', 'paddleocr']);
});

test('8-bit automatic profile forces pixel-art preprocessing', () => {
    assert.equal(resolveOcrPreprocessing('auto'), 'standard');
    assert.equal(resolveOcrPreprocessing('auto8bit'), 'pixel-art');
    assert.equal(resolveOcrPreprocessing('unknown'), 'standard');
});

test('individual OCR profiles request only their selected engine', () => {
    assert.deepEqual(resolveOcrEngines('easyocr'), ['easyocr']);
    assert.deepEqual(resolveOcrEngines('windowsocr'), ['windowsocr']);
    assert.deepEqual(resolveOcrEngines('unknown'), ['tesseract']);
});
