'use strict';

const assert = require('node:assert/strict');
const path = require('node:path');
const { app, BrowserWindow, screen } = require('electron');

const DEFAULT_STYLE = {
    bgColor: '#160d26',
    fontFamily: 'Segoe UI',
    fontSize: 30,
    opacity: 0.94,
    overlayAreaConfigured: true,
    textAlign: 'center',
    textColor: '#ffffff'
};

async function waitForLayout(window) {
    await new Promise(resolve => setTimeout(resolve, 120));
    return window.webContents.executeJavaScript(`(async () => {
        await document.fonts.ready;
        await new Promise(resolve => requestAnimationFrame(() => requestAnimationFrame(resolve)));
        const content = document.getElementById('content');
        const toast = document.getElementById('toastBox');
        const closeButton = document.getElementById('closeButton');
        return {
            clientHeight: content.clientHeight,
            clientWidth: content.clientWidth,
            closeDisplay: getComputedStyle(closeButton).display,
            configured: toast.classList.contains('configured-overlay'),
            fontSize: Number.parseFloat(getComputedStyle(content).fontSize),
            scrollHeight: content.scrollHeight,
            scrollWidth: content.scrollWidth,
            text: content.textContent
        };
    })()`);
}

async function render(window, bounds, text, style = {}) {
    window.setBounds({ x: 0, y: 0, ...bounds });
    window.webContents.send('set-text', {
        text,
        style: { ...DEFAULT_STYLE, ...style }
    });
    return waitForLayout(window);
}

async function run() {
    const window = new BrowserWindow({
        width: 900,
        height: 300,
        frame: false,
        show: false,
        transparent: true,
        webPreferences: {
            backgroundThrottling: false,
            contextIsolation: true,
            nodeIntegration: false,
            preload: path.join(__dirname, 'preload.js'),
            sandbox: true
        }
    });
    await window.loadFile(path.join(__dirname, 'toast.html'));

    const shortText = await render(window, { width: 220, height: 90 }, 'Olá!');
    assert.equal(shortText.configured, true);
    assert.equal(shortText.closeDisplay, 'none');
    assert.equal(shortText.fontSize, 30);

    const longTextValue = 'Esta é uma tradução longa que precisa quebrar linhas e reduzir a fonte sem escapar da área escolhida pelo usuário. '.repeat(2);
    const longText = await render(window, { width: 220, height: 90 }, longTextValue);
    assert.ok(longText.fontSize < shortText.fontSize);
    assert.ok(longText.scrollHeight <= longText.clientHeight + 1);
    assert.ok(longText.scrollWidth <= longText.clientWidth + 1);

    const largeArea = await render(window, { width: 900, height: 300 }, longTextValue);
    assert.ok(largeArea.fontSize >= longText.fontSize);
    assert.ok(largeArea.scrollHeight <= largeArea.clientHeight + 1);

    window.webContents.send('set-text', { text: 'primeiro', style: DEFAULT_STYLE });
    window.webContents.send('set-text', { text: 'segundo', style: DEFAULT_STYLE });
    window.webContents.send('set-text', { text: 'conteúdo mais recente', style: DEFAULT_STYLE });
    const frequentUpdate = await waitForLayout(window);
    assert.equal(frequentUpdate.text, 'conteúdo mais recente');

    const displays = screen.getAllDisplays();
    if (displays.length > 1) {
        const secondaryDisplay = displays[1];
        window.setBounds({
            x: secondaryDisplay.bounds.x + 20,
            y: secondaryDisplay.bounds.y + 20,
            width: Math.min(640, secondaryDisplay.bounds.width - 40),
            height: Math.min(180, secondaryDisplay.bounds.height - 40)
        });
        assert.equal(screen.getDisplayMatching(window.getBounds()).id, secondaryDisplay.id);
    }

    window.destroy();
    console.log('Overlay smoke test passed.');
}

app.whenReady()
    .then(run)
    .then(() => app.quit())
    .catch(error => {
        console.error(error);
        app.exit(1);
    });
