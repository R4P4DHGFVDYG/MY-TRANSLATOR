'use strict';

const MIN_OVERLAY_WIDTH = 180;
const MIN_OVERLAY_HEIGHT = 90;
const MAX_OVERLAY_DIMENSION = 32_768;

function isPlainObject(value) {
    return Boolean(value) && typeof value === 'object' && !Array.isArray(value);
}

function normalizeRectangle(value, options = {}) {
    if (!isPlainObject(value)) {
        return null;
    }
    const x = Number(value.x);
    const y = Number(value.y);
    const width = Number(value.width);
    const height = Number(value.height);
    if (
        ![x, y, width, height].every(Number.isFinite)
        || width <= 0
        || height <= 0
        || width > (options.maxDimension || MAX_OVERLAY_DIMENSION)
        || height > (options.maxDimension || MAX_OVERLAY_DIMENSION)
    ) {
        return null;
    }
    return {
        x: Math.round(x),
        y: Math.round(y),
        width: Math.max(1, Math.round(width)),
        height: Math.max(1, Math.round(height))
    };
}

function normalizeOverlayRegion(value) {
    if (!isPlainObject(value)) {
        return null;
    }
    const displayId = Number(value.displayId);
    const selection = normalizeRectangle(value.selection);
    if (!Number.isFinite(displayId) || !selection) {
        return null;
    }
    const displayBounds = value.displayBounds === undefined
        ? null
        : normalizeRectangle(value.displayBounds);
    if (value.displayBounds !== undefined && !displayBounds) {
        return null;
    }
    return {
        displayId: Math.trunc(displayId),
        ...(displayBounds ? { displayBounds } : {}),
        selection
    };
}

function clampRectangleToBounds(rectangle, container, options = {}) {
    const source = normalizeRectangle(rectangle);
    const bounds = normalizeRectangle(container);
    if (!source || !bounds) {
        return null;
    }
    const minimumWidth = Math.min(
        bounds.width,
        Math.max(1, Math.round(Number(options.minWidth) || 1))
    );
    const minimumHeight = Math.min(
        bounds.height,
        Math.max(1, Math.round(Number(options.minHeight) || 1))
    );
    const width = Math.min(bounds.width, Math.max(minimumWidth, source.width));
    const height = Math.min(bounds.height, Math.max(minimumHeight, source.height));
    const maxX = bounds.x + bounds.width - width;
    const maxY = bounds.y + bounds.height - height;
    return {
        x: Math.min(Math.max(source.x, bounds.x), maxX),
        y: Math.min(Math.max(source.y, bounds.y), maxY),
        width,
        height
    };
}

function overlapArea(left, right) {
    const overlapWidth = Math.max(
        0,
        Math.min(left.x + left.width, right.x + right.width) - Math.max(left.x, right.x)
    );
    const overlapHeight = Math.max(
        0,
        Math.min(left.y + left.height, right.y + right.height) - Math.max(left.y, right.y)
    );
    return overlapWidth * overlapHeight;
}

function displayDistanceSquared(display, rectangle) {
    const displayCenterX = display.bounds.x + (display.bounds.width / 2);
    const displayCenterY = display.bounds.y + (display.bounds.height / 2);
    const rectangleCenterX = rectangle.x + (rectangle.width / 2);
    const rectangleCenterY = rectangle.y + (rectangle.height / 2);
    return ((displayCenterX - rectangleCenterX) ** 2)
        + ((displayCenterY - rectangleCenterY) ** 2);
}

function matchingDisplay(displays, rectangle) {
    const candidates = Array.isArray(displays)
        ? displays.filter(display => normalizeRectangle(display?.bounds))
        : [];
    if (candidates.length === 0) {
        return null;
    }
    return candidates.reduce((best, display) => {
        const area = overlapArea(display.bounds, rectangle);
        const distance = displayDistanceSquared(display, rectangle);
        if (!best || area > best.area || (area === best.area && distance < best.distance)) {
            return { display, area, distance };
        }
        return best;
    }, null).display;
}

function regionFromWindowBounds(windowBounds, display) {
    const displayBounds = normalizeRectangle(display?.bounds);
    if (!displayBounds || !Number.isFinite(Number(display?.id))) {
        return null;
    }
    const bounds = clampRectangleToBounds(windowBounds, displayBounds, {
        minWidth: MIN_OVERLAY_WIDTH,
        minHeight: MIN_OVERLAY_HEIGHT
    });
    if (!bounds) {
        return null;
    }
    return {
        displayId: Math.trunc(Number(display.id)),
        displayBounds: { ...displayBounds },
        selection: {
            x: bounds.x - displayBounds.x,
            y: bounds.y - displayBounds.y,
            width: bounds.width,
            height: bounds.height
        }
    };
}

function resolveOverlayRegion(region, displays) {
    const normalized = normalizeOverlayRegion(region);
    const availableDisplays = Array.isArray(displays)
        ? displays.filter(display => normalizeRectangle(display?.bounds))
        : [];
    if (!normalized || availableDisplays.length === 0) {
        return null;
    }

    let display = availableDisplays.find(item => Number(item.id) === normalized.displayId);
    let requestedBounds;
    if (display) {
        requestedBounds = {
            x: display.bounds.x + normalized.selection.x,
            y: display.bounds.y + normalized.selection.y,
            width: normalized.selection.width,
            height: normalized.selection.height
        };
    } else if (normalized.displayBounds) {
        requestedBounds = {
            x: normalized.displayBounds.x + normalized.selection.x,
            y: normalized.displayBounds.y + normalized.selection.y,
            width: normalized.selection.width,
            height: normalized.selection.height
        };
        display = matchingDisplay(availableDisplays, requestedBounds);
    } else {
        return null;
    }
    if (!display) {
        return null;
    }

    const bounds = clampRectangleToBounds(requestedBounds, display.bounds, {
        minWidth: MIN_OVERLAY_WIDTH,
        minHeight: MIN_OVERLAY_HEIGHT
    });
    const remappedRegion = regionFromWindowBounds(bounds, display);
    if (!bounds || !remappedRegion) {
        return null;
    }
    return { display, bounds, region: remappedRegion };
}

function initialOverlayEditorLayout(options = {}) {
    const displays = Array.isArray(options.displays) ? options.displays : [];
    const configured = resolveOverlayRegion(options.overlayRegion, displays);
    if (configured) {
        return { ...configured, source: 'overlay' };
    }

    const capture = resolveOverlayRegion(options.captureRegion, displays);
    if (capture) {
        return { ...capture, source: 'capture' };
    }

    const preferredId = Number(options.preferredDisplay?.id);
    const display = displays.find(item => Number(item.id) === preferredId)
        || options.preferredDisplay
        || displays[0];
    const availableBounds = normalizeRectangle(display?.workArea)
        || normalizeRectangle(display?.bounds);
    if (!display || !availableBounds) {
        return null;
    }
    const defaultWidth = Math.min(
        availableBounds.width,
        Math.max(MIN_OVERLAY_WIDTH, Math.round(Number(options.defaultSize?.width) || 600))
    );
    const defaultHeight = Math.min(
        availableBounds.height,
        Math.max(MIN_OVERLAY_HEIGHT, Math.round(Number(options.defaultSize?.height) || 200))
    );
    const bounds = {
        x: Math.round(availableBounds.x + ((availableBounds.width - defaultWidth) / 2)),
        y: Math.round(availableBounds.y + ((availableBounds.height - defaultHeight) / 2)),
        width: defaultWidth,
        height: defaultHeight
    };
    return {
        display,
        bounds,
        region: regionFromWindowBounds(bounds, display),
        source: 'default'
    };
}

function serializeOverlayRegion(region) {
    const normalized = normalizeOverlayRegion(region);
    return normalized ? JSON.stringify(normalized) : '';
}

function parseOverlayRegion(serialized) {
    if (typeof serialized !== 'string' || serialized.length > 16_384) {
        return null;
    }
    try {
        return normalizeOverlayRegion(JSON.parse(serialized));
    } catch {
        return null;
    }
}

module.exports = {
    MAX_OVERLAY_DIMENSION,
    MIN_OVERLAY_HEIGHT,
    MIN_OVERLAY_WIDTH,
    clampRectangleToBounds,
    initialOverlayEditorLayout,
    matchingDisplay,
    normalizeOverlayRegion,
    parseOverlayRegion,
    regionFromWindowBounds,
    resolveOverlayRegion,
    serializeOverlayRegion
};
