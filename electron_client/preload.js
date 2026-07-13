const { contextBridge, ipcRenderer } = require('electron');

function subscribe(channel, callback) {
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
        getBridgeStatus: () => ipcRenderer.invoke('bridge-status'),
        getLanguages: () => ipcRenderer.invoke('languages'),
        getSystemFonts: () => ipcRenderer.invoke('system-fonts')
    },
    snip: {
        complete: selection => ipcRenderer.send('snip-complete', selection),
        cancel: () => ipcRenderer.send('snip-cancel')
    },
    toast: {
        onSetText: callback => subscribe('set-text', callback),
        close: () => ipcRenderer.send('close-toast')
    }
});
