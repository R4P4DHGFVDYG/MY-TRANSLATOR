const TEXT_ALIGNMENTS = new Set(['left', 'center', 'right']);

function normalizeFontFamily(value) {
    if (
        typeof value !== 'string'
        || value.length === 0
        || value.length > 120
        || /[;{}"\\]/.test(value)
    ) {
        return null;
    }
    return value;
}

function normalizeFontSize(value) {
    const fontSize = Number(value);
    if (!Number.isFinite(fontSize)) {
        return null;
    }
    return Math.min(36, Math.max(12, Math.round(fontSize)));
}

function normalizeTextAlign(value) {
    return TEXT_ALIGNMENTS.has(value) ? value : null;
}

module.exports = {
    normalizeFontFamily,
    normalizeFontSize,
    normalizeTextAlign
};
