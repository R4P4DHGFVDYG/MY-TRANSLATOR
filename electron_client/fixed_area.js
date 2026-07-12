'use strict';

class FixedAreaChangeTracker {
    constructor() {
        this.reset();
    }

    reset() {
        this.lastDigest = '';
        this.lastText = '';
        this.pendingText = '';
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

    evaluateText(text, score, confidenceThreshold = 0.72) {
        const normalized = typeof text === 'string' ? text.trim() : '';
        if (!normalized) {
            this.lastText = '';
            this.pendingText = '';
            return { display: false, retry: false };
        }
        if (normalized === this.lastText) {
            return { display: false, retry: false };
        }

        const numericScore = Number(score);
        const reliable = Number.isFinite(numericScore) && numericScore >= confidenceThreshold;
        if (reliable || normalized === this.pendingText) {
            this.lastText = normalized;
            this.pendingText = '';
            return { display: true, retry: false };
        }

        this.pendingText = normalized;
        return { display: false, retry: true };
    }

    retryCurrentFrame() {
        this.lastDigest = '';
    }
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

module.exports = { FixedAreaChangeTracker, rectanglesOverlap, toastSizeForFixedArea };
