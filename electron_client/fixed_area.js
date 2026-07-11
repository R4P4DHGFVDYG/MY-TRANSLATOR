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

module.exports = { FixedAreaChangeTracker, rectanglesOverlap };
