const OCR_ENGINES = new Set(['auto', 'tesseract', 'paddleocr', 'easyocr']);

function resolveOcrEngines(profile) {
    if (profile === 'auto') {
        return ['tesseract', 'paddleocr'];
    }
    return OCR_ENGINES.has(profile) ? [profile] : ['tesseract'];
}

module.exports = { OCR_ENGINES, resolveOcrEngines };
