const test = require('node:test');
const assert = require('node:assert/strict');
const fs = require('node:fs');
const path = require('node:path');
const vm = require('node:vm');

test('sandboxed preload exposes the API without requiring local modules', async () => {
    const invocations = [];
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
            on() {},
            removeListener() {},
            send() {}
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
    assert.deepEqual(invocations, [['languages', undefined]]);
});
