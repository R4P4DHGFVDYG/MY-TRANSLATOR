'use strict';

const test = require('node:test');
const assert = require('node:assert/strict');
const fs = require('node:fs');
const os = require('node:os');
const path = require('node:path');
const {
    MAX_OVERLAY_FILE_BYTES,
    readOverlayRegion,
    writeOverlayRegion
} = require('./overlay_store');

function withTemporaryDirectory(callback) {
    const directory = fs.mkdtempSync(path.join(os.tmpdir(), 'grc-overlay-'));
    try {
        return callback(directory);
    } finally {
        fs.rmSync(directory, { recursive: true, force: true });
    }
}

const savedRegion = {
    displayId: 2,
    displayBounds: { x: -1707, y: -120, width: 1707, height: 960 },
    selection: { x: 207, y: 140, width: 640, height: 170 }
};

test('persists and reloads an overlay area across a simulated restart', () => {
    withTemporaryDirectory(directory => {
        const filePath = path.join(directory, 'nested', 'overlay-area.json');
        writeOverlayRegion(filePath, savedRegion);
        const movedRegion = {
            ...savedRegion,
            selection: { ...savedRegion.selection, x: 320, width: 720 }
        };
        writeOverlayRegion(filePath, movedRegion);
        assert.deepEqual(readOverlayRegion(filePath), movedRegion);
        assert.deepEqual(
            fs.readdirSync(path.dirname(filePath)),
            ['overlay-area.json'],
            'the atomic temporary file must be removed'
        );
    });
});

test('reset removes the persisted overlay area', () => {
    withTemporaryDirectory(directory => {
        const filePath = path.join(directory, 'overlay-area.json');
        writeOverlayRegion(filePath, savedRegion);
        writeOverlayRegion(filePath, null);
        assert.equal(fs.existsSync(filePath), false);
    });
});

test('invalid JSON is ignored and oversized files are rejected before parsing', () => {
    withTemporaryDirectory(directory => {
        const filePath = path.join(directory, 'overlay-area.json');
        fs.writeFileSync(filePath, '{invalid', 'utf8');
        assert.equal(readOverlayRegion(filePath), null);
        fs.writeFileSync(filePath, Buffer.alloc(MAX_OVERLAY_FILE_BYTES + 1));
        assert.throws(() => readOverlayRegion(filePath), /unexpectedly large/);
    });
});
