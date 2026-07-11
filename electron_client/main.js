const { app, BrowserWindow, globalShortcut, ipcMain, desktopCapturer, screen } = require('electron');
const { spawn } = require('child_process');
const { createHash, randomUUID } = require('crypto');
const path = require('path');

const APP_NAME = 'G.R.C TRANSLATOR';
const APP_ICON_PATH = path.join(__dirname, 'assets', 'spider-intro.png');
const BRIDGE_URL = 'http://127.0.0.1:8765/v1/translate-selection';
const BRIDGE_READY_URL = 'http://127.0.0.1:8765/ready';
const BRIDGE_REQUEST_TIMEOUT_MS = 45_000;
const TOAST_WIDTH = 600;
const TOAST_HEIGHT = 200;
const TOAST_MARGIN = 20;
const BRIDGE_DEFAULT_MAX_IMAGE_BYTES = 12 * 1024 * 1024;
const BRIDGE_DEFAULT_MAX_CROP_PIXELS = 12_000_000;
const MAX_SNIP_PIXELS = BRIDGE_DEFAULT_MAX_CROP_PIXELS;
const CAPTURE_SETTLE_MS = 16;
const INTRO_FALLBACK_MS = 5000;
const RESULT_CACHE_CAPACITY = 64;
const RESULT_CACHE_TTL_MS = 10 * 60 * 1000;
const CLIENT_ID = randomUUID();
const SOURCE_LANGUAGES = new Set(['en']);
const TARGET_LANGUAGES = new Set(['pt-BR', 'en']);
const OCR_ENGINES = new Set(['tesseract', 'paddleocr']);
const TOAST_POSITIONS = new Set(['custom', 'mouse', 'top', 'bottom', 'center']);

let settingsWindow = null;
let introWindow = null;
let introFallbackTimer = null;
let settingsReady = false;
let shouldShowSettings = false;
let shouldFocusSettings = false;
let snipWindow = null;
let snipDisplay = null;
let toastWindow = null;
let toastCloseTimer = null;
let toastReady = false;
let pendingToastPayload = null;
let isPositioningToast = false;
let sideMouseHookProcess = null;
let isStartingSnip = false;
let activeTranslation = null;
let nextTranslationId = 0;
const resultCache = new Map();

app.setName(APP_NAME);

const settings = {
    sourceLang: 'en',
    targetLang: 'pt-BR',
    ocrEngine: 'tesseract',
    position: 'custom',
    textColor: '#ffffff',
    bgColor: '#160d26',
    opacity: 0.94,
    customX: -1,
    customY: -1,
    mouseShortcutButton: 'XBUTTON1'
};

function isWindowAlive(window) {
    return Boolean(window) && typeof window.isDestroyed === 'function' && !window.isDestroyed();
}

function closeWindow(window) {
    if (isWindowAlive(window)) {
        window.close();
    }
}

function sendToWindow(window, channel, payload) {
    if (isWindowAlive(window) && window.webContents && !window.webContents.isDestroyed()) {
        window.webContents.send(channel, payload);
    }
}

function isEventFromWindow(event, window) {
    return isWindowAlive(window) && event.sender === window.webContents;
}

function getWebPreferences() {
    return {
        preload: path.join(__dirname, 'preload.js'),
        nodeIntegration: false,
        contextIsolation: true,
        webSecurity: true
    };
}

function closeToastWindow() {
    if (toastCloseTimer) {
        clearTimeout(toastCloseTimer);
        toastCloseTimer = null;
    }
    closeWindow(toastWindow);
    toastWindow = null;
    toastReady = false;
    pendingToastPayload = null;
    isPositioningToast = false;
}

function getPowerShellPath() {
    const systemRoot = process.env.SystemRoot || 'C:\\Windows';
    return path.join(systemRoot, 'System32', 'WindowsPowerShell', 'v1.0', 'powershell.exe');
}

function isMouseShortcutButton(value) {
    return value === 'XBUTTON1' || value === 'XBUTTON2';
}

function stopSideMouseShortcut() {
    const hookProcess = sideMouseHookProcess;
    sideMouseHookProcess = null;

    if (hookProcess && !hookProcess.killed) {
        try {
            hookProcess.kill();
        } catch (error) {
            console.error('Could not stop mouse shortcut hook:', error);
        }
    }
}

function startSideMouseShortcut() {
    stopSideMouseShortcut();

    if (process.platform !== 'win32' || !isMouseShortcutButton(settings.mouseShortcutButton)) {
        return;
    }

    const hookPath = path.join(__dirname, 'mouse_hook.ps1');
    const hookProcess = spawn(getPowerShellPath(), [
        '-NoProfile',
        '-ExecutionPolicy',
        'Bypass',
        '-File',
        hookPath,
        '-Button',
        settings.mouseShortcutButton
    ], {
        windowsHide: true,
        stdio: ['ignore', 'pipe', 'pipe']
    });
    sideMouseHookProcess = hookProcess;

    let hookBuffer = '';
    hookProcess.stdout.on('data', data => {
        if (sideMouseHookProcess !== hookProcess) {
            return;
        }

        hookBuffer += data.toString();
        const lines = hookBuffer.split(/\r?\n/);
        hookBuffer = lines.pop() || '';

        for (const line of lines) {
            if (line.trim() === settings.mouseShortcutButton) {
                void startSnip();
            }
        }
    });

    hookProcess.stderr.on('data', data => {
        console.error(`Mouse shortcut hook: ${data}`);
    });
    hookProcess.on('exit', () => {
        if (sideMouseHookProcess === hookProcess) {
            sideMouseHookProcess = null;
        }
    });
    hookProcess.on('error', error => {
        console.error('Mouse shortcut hook failed:', error);
    });
}

function registerKeyboardShortcut() {
    const registered = globalShortcut.register('CommandOrControl+Shift+Q', () => {
        void startSnip();
    });

    if (!registered) {
        console.error('Could not register Ctrl+Shift+Q shortcut.');
    }
}

function createSettingsWindow() {
    settingsWindow = new BrowserWindow({
        title: APP_NAME,
        icon: APP_ICON_PATH,
        width: 580,
        height: 720,
        frame: false,
        transparent: true,
        resizable: false,
        backgroundColor: '#00000000',
        show: false,
        webPreferences: getWebPreferences()
    });
    settingsWindow.center();

    settingsWindow.on('closed', () => {
        settingsWindow = null;
        settingsReady = false;
    });
    const markSettingsReady = () => {
        if (settingsReady) {
            return;
        }
        settingsReady = true;
        if (shouldShowSettings) {
            showSettingsWindow(shouldFocusSettings);
        }
    };
    settingsWindow.once('ready-to-show', markSettingsReady);
    settingsWindow.webContents.once('did-finish-load', markSettingsReady);
    settingsWindow.loadFile(path.join(__dirname, 'index.html')).catch(error => {
        console.error('Failed to load settings window:', error);
    });
}

function showSettingsWindow(focus = true) {
    shouldShowSettings = true;
    shouldFocusSettings = shouldFocusSettings || focus;
    if (!settingsReady || !isWindowAlive(settingsWindow)) {
        return;
    }

    if (settingsWindow.isMinimized()) {
        settingsWindow.restore();
    }
    if (shouldFocusSettings) {
        settingsWindow.show();
        settingsWindow.focus();
    } else {
        settingsWindow.showInactive();
    }
}

function finishIntro() {
    if (introFallbackTimer) {
        clearTimeout(introFallbackTimer);
        introFallbackTimer = null;
    }

    const currentIntro = introWindow;
    introWindow = null;
    if (isWindowAlive(currentIntro)) {
        currentIntro.destroy();
    }
    showSettingsWindow(true);
}

function createIntroWindow() {
    const display = screen.getPrimaryDisplay();
    const { x, y, width, height } = display.bounds;
    const currentIntro = new BrowserWindow({
        x,
        y,
        width,
        height,
        frame: false,
        transparent: true,
        backgroundColor: '#00000000',
        alwaysOnTop: true,
        skipTaskbar: true,
        focusable: false,
        show: false,
        hasShadow: false,
        enableLargerThanScreen: true,
        webPreferences: getWebPreferences()
    });
    introWindow = currentIntro;
    currentIntro.setIgnoreMouseEvents(true);
    currentIntro.on('closed', () => {
        if (introWindow === currentIntro) {
            introWindow = null;
        }
    });
    currentIntro.once('ready-to-show', () => {
        if (introWindow === currentIntro) {
            currentIntro.showInactive();
        }
    });
    currentIntro.loadFile(path.join(__dirname, 'intro.html')).catch(error => {
        console.error('Failed to load intro animation:', error);
        finishIntro();
    });

    introFallbackTimer = setTimeout(() => {
        if (introWindow === currentIntro) {
            console.warn('Intro animation timed out; showing the application.');
            finishIntro();
        }
    }, INTRO_FALLBACK_MS);
}

async function getBridgeStatus() {
    const controller = new AbortController();
    const timeoutId = setTimeout(() => controller.abort(), 1500);
    try {
        const response = await fetch(BRIDGE_READY_URL, { signal: controller.signal });
        const payload = await response.json().catch(() => null);
        if (response.ok && payload && payload.ready === true) {
            return { state: 'ready', label: 'OCR local pronto' };
        }
        return { state: 'warming', label: 'Carregando o OCR' };
    } catch {
        return { state: 'offline', label: 'Bridge desconectado' };
    } finally {
        clearTimeout(timeoutId);
    }
}

function clampToastPosition(position, workArea) {
    const maxX = workArea.x + Math.max(0, workArea.width - TOAST_WIDTH - TOAST_MARGIN);
    const maxY = workArea.y + Math.max(0, workArea.height - TOAST_HEIGHT - TOAST_MARGIN);

    return {
        x: Math.min(Math.max(position.x, workArea.x), maxX),
        y: Math.min(Math.max(position.y, workArea.y), maxY)
    };
}

function showToast(text, x, y, currentSettings, preferredDisplay = null) {
    const anchorPoint = {
        x: Number.isFinite(x) ? x : 0,
        y: Number.isFinite(y) ? y : 0
    };
    let display = preferredDisplay || screen.getDisplayNearestPoint(anchorPoint);
    let workArea = display.workArea;
    pendingToastPayload = { text, style: currentSettings };

    let currentToast = toastWindow;
    if (!isWindowAlive(currentToast)) {
        currentToast = new BrowserWindow({
            width: TOAST_WIDTH,
            height: TOAST_HEIGHT,
            frame: false,
            transparent: true,
            alwaysOnTop: true,
            skipTaskbar: true,
            focusable: true,
            show: false,
            webPreferences: getWebPreferences()
        });
        toastWindow = currentToast;
        toastReady = false;

        currentToast.on('closed', () => {
            if (toastWindow === currentToast) {
                toastWindow = null;
                toastReady = false;
                pendingToastPayload = null;
            }
        });
        currentToast.on('moved', () => {
            if (!isWindowAlive(currentToast) || isPositioningToast) {
                return;
            }

            const [nx, ny] = currentToast.getPosition();
            settings.customX = nx;
            settings.customY = ny;
            settings.position = 'custom';
        });
        currentToast.webContents.on('did-finish-load', () => {
            if (toastWindow !== currentToast) {
                return;
            }
            toastReady = true;
            if (pendingToastPayload) {
                sendToWindow(currentToast, 'set-text', pendingToastPayload);
            }
            currentToast.showInactive();
        });
        currentToast.loadFile(path.join(__dirname, 'toast.html')).catch(error => {
            console.error('Failed to load translation toast:', error);
            if (toastWindow === currentToast) {
                closeToastWindow();
            } else {
                closeWindow(currentToast);
            }
        });
    } else if (toastReady) {
        sendToWindow(currentToast, 'set-text', pendingToastPayload);
        currentToast.showInactive();
    }

    let posX = Math.floor(workArea.x + (workArea.width - TOAST_WIDTH) / 2);
    let posY = workArea.y + TOAST_MARGIN;

    if (currentSettings.position === 'custom') {
        if (currentSettings.customX !== -1 && currentSettings.customY !== -1) {
            posX = currentSettings.customX;
            posY = currentSettings.customY;
            display = screen.getDisplayNearestPoint({ x: posX, y: posY });
            workArea = display.workArea;
        } else {
            posY = Math.floor(workArea.y + (workArea.height - TOAST_HEIGHT) / 2);
        }
    } else if (currentSettings.position === 'bottom') {
        posY = workArea.y + workArea.height - TOAST_HEIGHT - TOAST_MARGIN;
    } else if (currentSettings.position === 'center') {
        posY = Math.floor(workArea.y + (workArea.height - TOAST_HEIGHT) / 2);
    } else if (currentSettings.position === 'mouse') {
        posX = anchorPoint.x + 10;
        posY = anchorPoint.y + 10;
    }

    const clampedPosition = clampToastPosition({ x: posX, y: posY }, workArea);

    isPositioningToast = true;
    currentToast.setPosition(Math.round(clampedPosition.x), Math.round(clampedPosition.y));
    setTimeout(() => {
        if (toastWindow === currentToast) {
            isPositioningToast = false;
        }
    }, 50);

    if (toastCloseTimer) {
        clearTimeout(toastCloseTimer);
    }
    toastCloseTimer = setTimeout(() => {
        toastCloseTimer = null;
        if (toastWindow === currentToast) {
            closeToastWindow();
        }
    }, 20000);
}

function getSourceForDisplay(sources, display) {
    const displayId = String(display.id);
    const matchingSource = sources.find(source => String(source.display_id) === displayId);
    if (matchingSource) {
        return matchingSource;
    }

    const displayIndex = screen.getAllDisplays().findIndex(item => item.id === display.id);
    return sources[displayIndex] || sources[0];
}

async function startSnip() {
    if (isStartingSnip || isWindowAlive(snipWindow)) {
        return;
    }

    isStartingSnip = true;
    cancelActiveTranslation();
    nextTranslationId += 1;
    closeToastWindow();

    let captureDisplay = screen.getPrimaryDisplay();
    try {
        const display = screen.getDisplayNearestPoint(screen.getCursorScreenPoint());
        captureDisplay = display;
        const { x, y, width, height } = display.bounds;
        const currentSnip = new BrowserWindow({
            x,
            y,
            width,
            height,
            frame: false,
            transparent: true,
            alwaysOnTop: true,
            skipTaskbar: true,
            enableLargerThanScreen: true,
            backgroundColor: '#00000000',
            show: false,
            webPreferences: getWebPreferences()
        });

        snipWindow = currentSnip;
        snipDisplay = display;
        currentSnip.on('closed', () => {
            if (snipWindow === currentSnip) {
                snipWindow = null;
                snipDisplay = null;
            }
        });

        await currentSnip.loadFile(path.join(__dirname, 'snip.html'));
        if (!isWindowAlive(currentSnip) || snipWindow !== currentSnip) {
            return;
        }

        currentSnip.show();
    } catch (error) {
        console.error('Failed to open screen selector:', error);
        if (isWindowAlive(snipWindow)) {
            closeWindow(snipWindow);
        }
        snipWindow = null;
        snipDisplay = null;
        showToast('Não foi possível abrir o seletor de tela.', captureDisplay.bounds.x, captureDisplay.bounds.y, settings, captureDisplay);
    } finally {
        isStartingSnip = false;
    }
}

function wait(milliseconds) {
    return new Promise(resolve => setTimeout(resolve, milliseconds));
}

async function captureSelection(selection, display) {
    const totalStartedAt = performance.now();
    await wait(CAPTURE_SETTLE_MS);

    const { width, height } = display.bounds;
    const thumbnailSize = {
        width: Math.max(1, Math.round(width * display.scaleFactor)),
        height: Math.max(1, Math.round(height * display.scaleFactor))
    };
    const captureStartedAt = performance.now();
    const sources = await desktopCapturer.getSources({
        types: ['screen'],
        thumbnailSize
    });
    const captureMs = performance.now() - captureStartedAt;
    const source = getSourceForDisplay(sources, display);
    if (!source || source.thumbnail.isEmpty()) {
        throw new Error('No screen source is available.');
    }

    const imageSize = source.thumbnail.getSize();
    const scaleX = imageSize.width / width;
    const scaleY = imageSize.height / height;
    const left = Math.max(0, Math.min(imageSize.width, Math.round(selection.x * scaleX)));
    const top = Math.max(0, Math.min(imageSize.height, Math.round(selection.y * scaleY)));
    const right = Math.max(left, Math.min(imageSize.width, Math.round((selection.x + selection.width) * scaleX)));
    const bottom = Math.max(top, Math.min(imageSize.height, Math.round((selection.y + selection.height) * scaleY)));
    if (right <= left || bottom <= top) {
        throw new Error('The selected region does not contain visible pixels.');
    }
    if ((right - left) * (bottom - top) > MAX_SNIP_PIXELS) {
        throw new Error('The selected region is too large.');
    }

    const cropStartedAt = performance.now();
    const croppedImage = source.thumbnail.crop({
        x: left,
        y: top,
        width: right - left,
        height: bottom - top
    });
    const cropMs = performance.now() - cropStartedAt;
    const encodeStartedAt = performance.now();
    const png = croppedImage.toPNG();
    const encodeMs = performance.now() - encodeStartedAt;
    if (png.length > BRIDGE_DEFAULT_MAX_IMAGE_BYTES) {
        throw new Error('The selected image is too large.');
    }
    const result = {
        base64: `data:image/png;base64,${png.toString('base64')}`,
        digest: createHash('sha256').update(png).digest('hex'),
        width: right - left,
        height: bottom - top
    };

    console.info('[performance]', JSON.stringify({
        stage: 'capture',
        captureMs: Number(captureMs.toFixed(2)),
        cropMs: Number(cropMs.toFixed(2)),
        encodeMs: Number(encodeMs.toFixed(2)),
        totalMs: Number((performance.now() - totalStartedAt).toFixed(2)),
        cropPixels: result.width * result.height,
        encodedBytes: png.length
    }));
    return result;
}

function isPlainObject(value) {
    return Boolean(value) && typeof value === 'object' && !Array.isArray(value);
}

function isValidColor(value) {
    return typeof value === 'string' && /^#[0-9a-f]{6}$/i.test(value);
}

function updateSettings(newSettings) {
    if (!isPlainObject(newSettings)) {
        return;
    }

    if (SOURCE_LANGUAGES.has(newSettings.sourceLang)) {
        settings.sourceLang = newSettings.sourceLang;
    }
    if (TARGET_LANGUAGES.has(newSettings.targetLang)) {
        settings.targetLang = newSettings.targetLang;
    }
    if (OCR_ENGINES.has(newSettings.ocrEngine)) {
        settings.ocrEngine = newSettings.ocrEngine;
    }
    if (TOAST_POSITIONS.has(newSettings.position)) {
        settings.position = newSettings.position;
    }
    if (isValidColor(newSettings.textColor)) {
        settings.textColor = newSettings.textColor;
    }
    if (isValidColor(newSettings.bgColor)) {
        settings.bgColor = newSettings.bgColor;
    }

    const opacity = Number(newSettings.opacity);
    if (Number.isFinite(opacity)) {
        settings.opacity = Math.min(1, Math.max(0, opacity));
    }

    for (const key of ['customX', 'customY']) {
        const coordinate = Number(newSettings[key]);
        if (Number.isFinite(coordinate)) {
            settings[key] = Math.round(coordinate);
        }
    }

    if (newSettings.mouseShortcutButton === 'disabled' || isMouseShortcutButton(newSettings.mouseShortcutButton)) {
        settings.mouseShortcutButton = newSettings.mouseShortcutButton;
    }
}

function validateSnipPayload(payload) {
    if (!isPlainObject(payload)) {
        return null;
    }

    const x = Number(payload.x);
    const y = Number(payload.y);
    const width = Number(payload.width);
    const height = Number(payload.height);
    if (![x, y, width, height].every(Number.isFinite) || width <= 10 || height <= 10) {
        return null;
    }

    const normalizedWidth = Math.floor(width);
    const normalizedHeight = Math.floor(height);
    if (normalizedWidth * normalizedHeight > MAX_SNIP_PIXELS) {
        return null;
    }

    return {
        x: Math.floor(x),
        y: Math.floor(y),
        width: normalizedWidth,
        height: normalizedHeight
    };
}

function cancelActiveTranslation() {
    const translation = activeTranslation;
    activeTranslation = null;
    if (translation) {
        translation.controller.abort();
    }
}

function isCurrentTranslation(id) {
    return activeTranslation && activeTranslation.id === id;
}

async function readBridgeResponse(response) {
    let payload = null;
    try {
        payload = await response.json();
    } catch {
        // The status code below still gives the user a useful error for malformed responses.
    }

    if (!response.ok) {
        const message = isPlainObject(payload) && typeof payload.error === 'string'
            ? payload.error
            : `O bridge retornou HTTP ${response.status}.`;
        throw new Error(message);
    }
    if (!isPlainObject(payload)) {
        throw new Error('O bridge retornou uma resposta inválida.');
    }
    if (typeof payload.translatedText !== 'string' || typeof payload.sourceText !== 'string') {
        throw new Error('A resposta do bridge não contém o texto esperado.');
    }

    return payload;
}

function errorMessageForTranslation(error, timedOut) {
    if (timedOut) {
        return 'A tradução demorou demais. Tente novamente.';
    }
    if (error instanceof Error && error.message) {
        return `Erro ao traduzir: ${error.message}`;
    }
    return 'Erro ao traduzir com o servidor local.';
}

function resultCacheKey(selection, requestSettings) {
    return `${requestSettings.ocrEngine}\0${requestSettings.sourceLang}\0${requestSettings.targetLang}\0${selection.digest}`;
}

function getCachedResult(key) {
    const cached = resultCache.get(key);
    if (!cached) {
        return null;
    }
    if (cached.expiresAt <= Date.now()) {
        resultCache.delete(key);
        return null;
    }
    resultCache.delete(key);
    resultCache.set(key, cached);
    return cached.payload;
}

function cacheResult(key, payload) {
    resultCache.set(key, {
        payload,
        expiresAt: Date.now() + RESULT_CACHE_TTL_MS
    });
    while (resultCache.size > RESULT_CACHE_CAPACITY) {
        resultCache.delete(resultCache.keys().next().value);
    }
}

function displayTranslationPayload(payload, anchorPoint, requestSettings, display) {
    const translatedText = payload.translatedText.trim();
    if (translatedText) {
        showToast(translatedText, anchorPoint.x, anchorPoint.y, requestSettings, display);
    } else if (payload.sourceText.trim()) {
        throw new Error('O OCR encontrou texto, mas o bridge não retornou uma tradução.');
    } else {
        showToast('Nenhum texto detectado.', anchorPoint.x, anchorPoint.y, requestSettings, display);
    }
}

async function translateSelection(selection, anchorPoint, display, translationId) {
    if (translationId !== nextTranslationId) {
        return;
    }
    cancelActiveTranslation();

    const requestSettings = { ...settings };
    const cacheKey = resultCacheKey(selection, requestSettings);
    const cachedPayload = getCachedResult(cacheKey);
    if (cachedPayload) {
        displayTranslationPayload(cachedPayload, anchorPoint, requestSettings, display);
        console.info('[performance]', JSON.stringify({
            stage: 'translation',
            requestId: translationId,
            clientCacheHit: true,
            totalMs: 0
        }));
        return;
    }

    const controller = new AbortController();
    activeTranslation = { id: translationId, controller };
    showToast('Traduzindo...', anchorPoint.x, anchorPoint.y, requestSettings, display);
    const requestStartedAt = performance.now();

    let timedOut = false;
    const timeoutId = setTimeout(() => {
        timedOut = true;
        controller.abort();
    }, BRIDGE_REQUEST_TIMEOUT_MS);

    try {
        const response = await fetch(BRIDGE_URL, {
            method: 'POST',
            headers: { 'Content-Type': 'application/json' },
            signal: controller.signal,
            body: JSON.stringify({
                imageDataUrl: selection.base64,
                selection: { x: 0, y: 0, width: selection.width, height: selection.height },
                viewport: { width: selection.width, height: selection.height },
                source: requestSettings.sourceLang,
                target: requestSettings.targetLang,
                engines: [requestSettings.ocrEngine],
                clientId: CLIENT_ID,
                requestId: translationId
            })
        });
        const payload = await readBridgeResponse(response);
        if (!isCurrentTranslation(translationId)) {
            return;
        }

        cacheResult(cacheKey, payload);
        displayTranslationPayload(payload, anchorPoint, requestSettings, display);
        console.info('[performance]', JSON.stringify({
            stage: 'translation',
            requestId: translationId,
            clientCacheHit: false,
            totalMs: Number((performance.now() - requestStartedAt).toFixed(2)),
            server: payload.performance || null
        }));
    } catch (error) {
        if (!isCurrentTranslation(translationId)) {
            return;
        }

        showToast(errorMessageForTranslation(error, timedOut), anchorPoint.x, anchorPoint.y, requestSettings, display);
    } finally {
        clearTimeout(timeoutId);
        if (isCurrentTranslation(translationId)) {
            activeTranslation = null;
        }
    }
}

app.whenReady().then(() => {
    if (process.platform === 'win32') {
        app.setAppUserModelId('com.grc.translator');
    }
    if (process.platform === 'darwin' && app.dock) {
        app.dock.setIcon(APP_ICON_PATH);
    }
    createSettingsWindow();
    createIntroWindow();
    registerKeyboardShortcut();
    startSideMouseShortcut();
});

app.on('will-quit', () => {
    if (introFallbackTimer) {
        clearTimeout(introFallbackTimer);
        introFallbackTimer = null;
    }
    cancelActiveTranslation();
    globalShortcut.unregisterAll();
    stopSideMouseShortcut();
});

app.on('window-all-closed', () => {
    if (process.platform !== 'darwin') {
        app.quit();
    }
});

ipcMain.on('update-settings', (event, newSettings) => {
    if (!isEventFromWindow(event, settingsWindow)) {
        return;
    }

    const previousMouseShortcutButton = settings.mouseShortcutButton;
    updateSettings(newSettings);
    if (settings.mouseShortcutButton !== previousMouseShortcutButton) {
        startSideMouseShortcut();
    }
});

ipcMain.on('intro-complete', event => {
    if (isEventFromWindow(event, introWindow)) {
        finishIntro();
    }
});

ipcMain.on('minimize-settings', event => {
    if (isEventFromWindow(event, settingsWindow)) {
        settingsWindow.minimize();
    }
});

ipcMain.on('start-capture', event => {
    if (!isEventFromWindow(event, settingsWindow)) {
        return;
    }
    settingsWindow.minimize();
    void startSnip();
});

ipcMain.handle('bridge-status', event => {
    if (!isEventFromWindow(event, settingsWindow)) {
        return { state: 'offline', label: 'Status indisponível' };
    }
    return getBridgeStatus();
});

ipcMain.on('snip-complete', (event, payload) => {
    const currentSnip = snipWindow;
    if (!isEventFromWindow(event, currentSnip)) {
        return;
    }

    const selection = validateSnipPayload(payload);
    const display = snipDisplay || screen.getPrimaryDisplay();
    snipWindow = null;
    snipDisplay = null;
    if (isWindowAlive(currentSnip)) {
        currentSnip.hide();
        currentSnip.destroy();
    }
    if (!selection) {
        showToast('A seleção capturada é inválida ou grande demais.', display.bounds.x, display.bounds.y, settings, display);
        return;
    }

    const anchorPoint = {
        x: display.bounds.x + selection.x,
        y: display.bounds.y + selection.y
    };
    const translationId = ++nextTranslationId;
    void captureSelection(selection, display)
        .then(captured => translateSelection(captured, anchorPoint, display, translationId))
        .catch(error => {
            if (translationId !== nextTranslationId) {
                return;
            }
            console.error('Failed to capture selected region:', error);
            showToast('Não foi possível capturar a região selecionada.', anchorPoint.x, anchorPoint.y, settings, display);
        });
});

ipcMain.on('snip-cancel', event => {
    if (!isEventFromWindow(event, snipWindow)) {
        return;
    }

    const currentSnip = snipWindow;
    snipWindow = null;
    snipDisplay = null;
    closeWindow(currentSnip);
});

ipcMain.on('close-toast', event => {
    if (isEventFromWindow(event, toastWindow)) {
        cancelActiveTranslation();
        closeToastWindow();
    }
});

ipcMain.on('close-settings', event => {
    if (isEventFromWindow(event, settingsWindow)) {
        app.quit();
    }
});
