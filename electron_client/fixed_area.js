'use strict';

// Calibrated on real typewriter-style subtitles: small enough to catch added
// letters while still ignoring isolated pixel noise and identical frames.
const DEFAULT_FRAME_DIFFERENCE_THRESHOLD = 0.003;

class AdaptiveCaptureCadence {
    constructor(options = {}) {
        this.activeIntervalMs = positiveNumber(options.activeIntervalMs, 240);
        this.idleIntervalMs = Math.max(
            this.activeIntervalMs,
            positiveNumber(options.idleIntervalMs, 400)
        );
        this.quietFrameThreshold = Math.max(
            1,
            Math.floor(positiveNumber(options.quietFrameThreshold, 5))
        );
        this.reset();
    }

    reset() {
        this.quietFrames = 0;
    }

    noteChanged() {
        this.quietFrames = 0;
    }

    noteUnchanged() {
        this.quietFrames = Math.min(
            this.quietFrameThreshold,
            this.quietFrames + 1
        );
    }

    noteError() {
        this.quietFrames = this.quietFrameThreshold;
    }

    currentInterval() {
        return this.quietFrames >= this.quietFrameThreshold
            ? this.idleIntervalMs
            : this.activeIntervalMs;
    }

    delayAfter(elapsedMs, immediate = false) {
        if (immediate) {
            return 0;
        }
        const elapsed = Number(elapsedMs);
        const normalizedElapsed = Number.isFinite(elapsed) && elapsed > 0
            ? elapsed
            : 0;
        return Math.max(0, Math.round(this.currentInterval() - normalizedElapsed));
    }
}

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
        this.lastFrameSignature = null;
        this.lastFrameDifference = 1;
        this.forceNextFrame = false;
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

    updateFrameSignature(
        signature,
        differenceThreshold = DEFAULT_FRAME_DIFFERENCE_THRESHOLD
    ) {
        const normalized = normalizedSignature(signature);
        if (!normalized) {
            this.lastFrameDifference = 1;
            return true;
        }

        if (this.forceNextFrame) {
            this.forceNextFrame = false;
            this.lastFrameDifference = this.lastFrameSignature
                ? perceptualFrameDifference(this.lastFrameSignature, normalized)
                : 1;
            this.lastFrameSignature = normalized;
            return true;
        }
        if (!this.lastFrameSignature) {
            this.lastFrameSignature = normalized;
            this.lastFrameDifference = 1;
            return true;
        }

        const difference = perceptualFrameDifference(
            this.lastFrameSignature,
            normalized
        );
        this.lastFrameDifference = difference;
        const numericThreshold = Number(differenceThreshold);
        const threshold = Number.isFinite(numericThreshold)
            ? Math.max(0, Math.min(1, numericThreshold))
            : DEFAULT_FRAME_DIFFERENCE_THRESHOLD;
        if (difference < threshold) {
            return false;
        }

        this.lastFrameSignature = normalized;
        return true;
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
        this.forceNextFrame = true;
    }
}

function createPerceptualSignature(bitmap) {
    if (!(bitmap instanceof Uint8Array) || bitmap.length < 4) {
        return new Uint8Array();
    }

    const pixelCount = Math.floor(bitmap.length / 4);
    const signature = new Uint8Array(pixelCount);
    for (let pixel = 0; pixel < pixelCount; pixel += 1) {
        const offset = pixel * 4;
        const blue = bitmap[offset];
        const green = bitmap[offset + 1];
        const red = bitmap[offset + 2];
        signature[pixel] = Math.round((red * 77 + green * 150 + blue * 29) / 256);
    }
    return signature;
}

function perceptualFrameDifference(left, right) {
    const first = normalizedSignature(left);
    const second = normalizedSignature(right);
    if (!first || !second || first.length !== second.length) {
        return 1;
    }

    let absoluteDifference = 0;
    let substantiallyChanged = 0;
    for (let index = 0; index < first.length; index += 1) {
        const difference = Math.abs(first[index] - second[index]);
        absoluteDifference += difference;
        if (difference >= 24) {
            substantiallyChanged += 1;
        }
    }

    const meanDifference = absoluteDifference / (first.length * 255);
    const changedPixelRatio = substantiallyChanged / first.length;
    return Math.max(meanDifference, changedPixelRatio * 0.45);
}

function normalizedSignature(value) {
    if (!(value instanceof Uint8Array) || value.length === 0) {
        return null;
    }
    return Uint8Array.from(value);
}

function positiveNumber(value, fallback) {
    const number = Number(value);
    return Number.isFinite(number) && number > 0 ? number : fallback;
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
    AdaptiveCaptureCadence,
    FixedAreaChangeTracker,
    createPerceptualSignature,
    normalizeTemporalText,
    perceptualFrameDifference,
    rectanglesOverlap,
    temporalTextSimilarity,
    toastSizeForFixedArea
};
