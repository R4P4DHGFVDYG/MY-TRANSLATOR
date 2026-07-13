'use strict';

class FixedAreaChangeTracker {
    constructor() {
        this.reset();
    }

    reset() {
        this.lastDigest = '';
        this.lastText = '';
        this.lastTextKey = '';
        this.pendingText = '';
        this.pendingTextKey = '';
    }

    updateDigest(digest) {
        const normalized = typeof digest === 'string' ? digest : '';
        if (!normalized || normalized === this.lastDigest) {
            return false;
        }
        this.lastDigest = normalized;
        return true;
    }

    updateText(text) {
        return this.evaluateText(text, 1).display;
    }

    evaluateText(
        text,
        score,
        confidenceThreshold = 0.72,
        temporalSimilarityThreshold = 0.86
    ) {
        const normalized = typeof text === 'string' ? text.trim() : '';
        if (!normalized) {
            this.lastText = '';
            this.lastTextKey = '';
            this.pendingText = '';
            this.pendingTextKey = '';
            return { display: false, retry: false };
        }

        const textKey = normalizeTemporalText(normalized);
        if (!textKey) {
            this.pendingText = '';
            this.pendingTextKey = '';
            return { display: false, retry: false };
        }
        if (textKey === this.lastTextKey) {
            this.pendingText = '';
            this.pendingTextKey = '';
            return { display: false, retry: false };
        }

        const numericScore = Number(score);
        const reliable = Number.isFinite(numericScore) && numericScore >= confidenceThreshold;
        const temporallyConfirmed = areTemporalMatches(
            textKey,
            this.pendingTextKey,
            temporalSimilarityThreshold
        );
        if (reliable || temporallyConfirmed) {
            this.lastText = normalized;
            this.lastTextKey = textKey;
            this.pendingText = '';
            this.pendingTextKey = '';
            return { display: true, retry: false };
        }

        this.pendingText = normalized;
        this.pendingTextKey = textKey;
        return { display: false, retry: true };
    }

    retryCurrentFrame() {
        this.lastDigest = '';
    }
}

function normalizeTemporalText(text) {
    return String(text || '')
        .normalize('NFKC')
        .toLocaleLowerCase()
        .replace(/[^\p{L}\p{N}]+/gu, ' ')
        .trim()
        .replace(/\s+/g, ' ');
}

function areTemporalMatches(left, right, threshold) {
    if (!left || !right) {
        return false;
    }
    if (left === right) {
        return true;
    }

    const minimumLength = Math.min(Array.from(left).length, Array.from(right).length);
    if (minimumLength < 6) {
        return false;
    }

    const numericThreshold = Number(threshold);
    const requiredSimilarity = Number.isFinite(numericThreshold)
        ? Math.max(0, Math.min(1, numericThreshold))
        : 0.86;
    return temporalTextSimilarity(left, right) >= requiredSimilarity;
}

function temporalTextSimilarity(left, right) {
    const leftChars = Array.from(left).slice(0, 512);
    const rightChars = Array.from(right).slice(0, 512);
    const maximumLength = Math.max(leftChars.length, rightChars.length);
    if (maximumLength === 0) {
        return 1;
    }
    if (Math.abs(leftChars.length - rightChars.length) / maximumLength > 0.5) {
        return 0;
    }

    let previous = Array.from({ length: rightChars.length + 1 }, (_value, index) => index);
    for (let leftIndex = 1; leftIndex <= leftChars.length; leftIndex += 1) {
        const current = [leftIndex];
        for (let rightIndex = 1; rightIndex <= rightChars.length; rightIndex += 1) {
            const substitutionCost = leftChars[leftIndex - 1] === rightChars[rightIndex - 1]
                ? 0
                : 1;
            current[rightIndex] = Math.min(
                current[rightIndex - 1] + 1,
                previous[rightIndex] + 1,
                previous[rightIndex - 1] + substitutionCost
            );
        }
        previous = current;
    }

    return 1 - (previous[rightChars.length] / maximumLength);
}

function rectanglesOverlap(left, right) {
    return left.x < right.x + right.width
        && left.x + left.width > right.x
        && left.y < right.y + right.height
        && left.y + left.height > right.y;
}

function toastSizeForFixedArea(region, display, workArea, defaultSize) {
    const hasMatchingRegion = region
        && display
        && region.displayId === display.id
        && region.selection;
    const requested = hasMatchingRegion ? region.selection : defaultSize;
    return {
        width: Math.max(1, Math.min(workArea.width, Math.floor(requested.width))),
        height: Math.max(1, Math.min(workArea.height, Math.floor(requested.height)))
    };
}

module.exports = {
    FixedAreaChangeTracker,
    normalizeTemporalText,
    rectanglesOverlap,
    temporalTextSimilarity,
    toastSizeForFixedArea
};
