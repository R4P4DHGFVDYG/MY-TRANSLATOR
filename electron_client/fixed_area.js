'use strict';

class FixedAreaChangeTracker {
    constructor() {
        this.reset();
    }

    reset() {
        this.lastDigest = '';
        this.lastText = '';
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
        const normalized = typeof text === 'string' ? text.trim() : '';
        if (!normalized) {
            this.lastText = '';
            return false;
        }
        if (normalized === this.lastText) {
            return false;
        }
        this.lastText = normalized;
        return true;
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
