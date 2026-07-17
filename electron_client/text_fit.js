(function exposeTextFit(root, factory) {
    const api = factory();
    if (typeof module === 'object' && module.exports) {
        module.exports = api;
    }
    if (root) {
        root.ocrTextFit = api;
    }
}(typeof globalThis !== 'undefined' ? globalThis : this, () => {
    function finiteNumber(value, fallback) {
        const number = Number(value);
        return Number.isFinite(number) ? number : fallback;
    }

    function largestFittingFontSize(preferred, minimum, fits, step = 0.5) {
        if (typeof fits !== 'function') {
            throw new TypeError('fits must be a function');
        }

        const safePreferred = Math.max(1, finiteNumber(preferred, 18));
        const safeMinimum = Math.min(safePreferred, Math.max(1, finiteNumber(minimum, 6)));
        const safeStep = Math.max(0.1, finiteNumber(step, 0.5));
        const stepCount = Math.max(0, Math.floor((safePreferred - safeMinimum) / safeStep));

        if (!fits(safeMinimum)) {
            return safeMinimum;
        }

        let low = 0;
        let high = stepCount;
        while (low < high) {
            const middle = Math.ceil((low + high) / 2);
            const candidate = Math.min(safePreferred, safeMinimum + (middle * safeStep));
            if (fits(candidate)) {
                low = middle;
            } else {
                high = middle - 1;
            }
        }

        const steppedResult = Math.min(safePreferred, safeMinimum + (low * safeStep));
        if (safePreferred > steppedResult && fits(safePreferred)) {
            return safePreferred;
        }
        return steppedResult;
    }

    function createLatestFrameScheduler(requestFrame, cancelFrame, callback) {
        if (
            typeof requestFrame !== 'function'
            || typeof cancelFrame !== 'function'
            || typeof callback !== 'function'
        ) {
            throw new TypeError('Frame scheduler functions are required');
        }
        let pendingFrame = null;
        return {
            schedule() {
                if (pendingFrame !== null) {
                    cancelFrame(pendingFrame);
                }
                pendingFrame = requestFrame(() => {
                    pendingFrame = null;
                    callback();
                });
            },
            cancel() {
                if (pendingFrame !== null) {
                    cancelFrame(pendingFrame);
                    pendingFrame = null;
                }
            }
        };
    }

    return { createLatestFrameScheduler, largestFittingFontSize };
}));
