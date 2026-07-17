const test = require('node:test');
const assert = require('node:assert/strict');
const fs = require('node:fs');
const path = require('node:path');
const vm = require('node:vm');

test('sandboxed preload exposes the API without requiring local modules', async () => {
    const invocations = [];
    const sends = [];
    const listeners = new Map();
    const removedListeners = [];
    let exposedApi = null;
    const electron = {
        contextBridge: {
            exposeInMainWorld(name, api) {
                assert.equal(name, 'ocrDesktop');
                exposedApi = api;
            }
        },
        ipcRenderer: {
            invoke(channel, payload) {
                invocations.push([channel, payload]);
                return Promise.resolve([]);
            },
            on(channel, listener) {
                listeners.set(channel, listener);
            },
            removeListener(channel, listener) {
                removedListeners.push([channel, listener]);
                if (listeners.get(channel) === listener) {
                    listeners.delete(channel);
                }
            },
            send(channel, payload) {
                sends.push([channel, payload]);
            }
        }
    };
    const preloadSource = fs.readFileSync(path.join(__dirname, 'preload.js'), 'utf8');

    vm.runInNewContext(preloadSource, {
        require(moduleName) {
            assert.equal(moduleName, 'electron');
            return electron;
        }
    });

    assert.ok(exposedApi);
    assert.equal(typeof exposedApi.settings.getLanguages, 'function');
    await exposedApi.settings.getLanguages();
    await exposedApi.settings.getOverlayAreaState();
    exposedApi.settings.editOverlayArea();
    exposedApi.settings.resetOverlayArea();
    exposedApi.overlayEditor.save();
    exposedApi.overlayEditor.cancel();
    exposedApi.overlayEditor.reset();

    assert.deepEqual(invocations, [
        ['languages', undefined],
        ['overlay-area-state', undefined]
    ]);
    assert.deepEqual(sends, [
        ['edit-overlay-area', undefined],
        ['reset-overlay-area', undefined],
        ['overlay-editor-save', undefined],
        ['overlay-editor-cancel', undefined],
        ['overlay-editor-reset', undefined]
    ]);

    let receivedBounds = null;
    const unsubscribeBounds = exposedApi.overlayEditor.onBounds(bounds => {
        receivedBounds = bounds;
    });
    const boundsListener = listeners.get('overlay-editor-bounds');
    assert.equal(typeof boundsListener, 'function');
    boundsListener({}, { x: -800, y: 40, width: 420, height: 150 });
    assert.deepEqual(receivedBounds, { x: -800, y: 40, width: 420, height: 150 });
    unsubscribeBounds();
    assert.equal(listeners.has('overlay-editor-bounds'), false);
    assert.deepEqual(removedListeners, [['overlay-editor-bounds', boundsListener]]);

    let settingsError = null;
    const unsubscribeSettingsError = exposedApi.settings.onOverlayAreaError(message => {
        settingsError = message;
    });
    listeners.get('overlay-area-error')({}, 'Falha ao salvar');
    assert.equal(settingsError, 'Falha ao salvar');
    unsubscribeSettingsError();
});
