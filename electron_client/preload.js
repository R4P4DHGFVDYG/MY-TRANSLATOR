const { contextBridge, ipcRenderer } = require('electron');

function subscribe(channel, callback) {
    if (typeof callback !== 'function') {
        return () => {};
    }
    const listener = (_event, payload) => callback(payload);
    ipcRenderer.on(channel, listener);
    return () => ipcRenderer.removeListener(channel, listener);
}

contextBridge.exposeInMainWorld('ocrDesktop', {
    intro: {
        complete: () => ipcRenderer.send('intro-complete')
    },
    settings: {
        update: settings => ipcRenderer.send('update-settings', settings),
        close: () => ipcRenderer.send('close-settings'),
        minimize: () => ipcRenderer.send('minimize-settings'),
        setCaptureShortcut: (action, shortcut) => ipcRenderer.invoke('set-capture-shortcut', {
            action,
            ...shortcut
        }),
        toggleFixedArea: () => ipcRenderer.send('toggle-fixed-area'),
        getFixedAreaState: () => ipcRenderer.invoke('fixed-area-state'),
        onFixedAreaState: callback => subscribe('fixed-area-state', callback),
        editOverlayArea: () => ipcRenderer.send('edit-overlay-area'),
        resetOverlayArea: () => ipcRenderer.send('reset-overlay-area'),
        getOverlayAreaState: () => ipcRenderer.invoke('overlay-area-state'),
        onOverlayAreaState: callback => subscribe('overlay-area-state', callback),
        onOverlayAreaError: callback => subscribe('overlay-area-error', callback),
        getBridgeStatus: () => ipcRenderer.invoke('bridge-status'),
        getLanguages: () => ipcRenderer.invoke('languages'),
        getSystemFonts: () => ipcRenderer.invoke('system-fonts')
    },
    snip: {
        complete: selection => ipcRenderer.send('snip-complete', selection),
        cancel: () => ipcRenderer.send('snip-cancel')
    },
    overlayEditor: {
        onBounds: callback => subscribe('overlay-editor-bounds', callback),
        onError: callback => subscribe('overlay-editor-error', callback),
        save: () => ipcRenderer.send('overlay-editor-save'),
        cancel: () => ipcRenderer.send('overlay-editor-cancel'),
        reset: () => ipcRenderer.send('overlay-editor-reset')
    },
    toast: {
        onSetText: callback => subscribe('set-text', callback),
        close: () => ipcRenderer.send('close-toast')
    }
});
