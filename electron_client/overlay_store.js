'use strict';

const fs = require('fs');
const path = require('path');
const { randomUUID } = require('crypto');
const { parseOverlayRegion, serializeOverlayRegion } = require('./overlay_area');

const MAX_OVERLAY_FILE_BYTES = 16_384;

function readOverlayRegion(filePath, fileSystem = fs) {
    const stats = fileSystem.statSync(filePath);
    if (stats.size > MAX_OVERLAY_FILE_BYTES) {
        throw new Error('The saved overlay area is unexpectedly large.');
    }
    return parseOverlayRegion(fileSystem.readFileSync(filePath, 'utf8'));
}

function writeOverlayRegion(filePath, region, fileSystem = fs) {
    if (!region) {
        fileSystem.rmSync(filePath, { force: true });
        return;
    }

    const serialized = serializeOverlayRegion(region);
    if (!serialized) {
        throw new TypeError('The overlay area is invalid and cannot be saved.');
    }

    fileSystem.mkdirSync(path.dirname(filePath), { recursive: true });
    const temporaryPath = `${filePath}.${process.pid}.${randomUUID()}.tmp`;
    try {
        fileSystem.writeFileSync(temporaryPath, `${serialized}\n`, 'utf8');
        fileSystem.renameSync(temporaryPath, filePath);
    } finally {
        fileSystem.rmSync(temporaryPath, { force: true });
    }
}

module.exports = {
    MAX_OVERLAY_FILE_BYTES,
    readOverlayRegion,
    writeOverlayRegion
};
