const OCR_ENGINES = new Set([
    'auto',
    'auto8bit',
    'windowsocr',
    'tesseract',
    'paddleocr',
    'easyocr'
]);

function resolveOcrEngines(profile) {
    if (profile === 'auto' || profile === 'auto8bit') {
        return ['tesseract', 'windowsocr', 'paddleocr'];
    }
    return OCR_ENGINES.has(profile) ? [profile] : ['tesseract'];
}

function resolveOcrPreprocessing(profile) {
    return profile === 'auto8bit' ? 'pixel-art' : 'standard';
}

module.exports = { OCR_ENGINES, resolveOcrEngines, resolveOcrPreprocessing };
