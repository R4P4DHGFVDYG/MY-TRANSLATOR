const { app, BrowserWindow, globalShortcut, ipcMain, desktopCapturer, screen } = require('electron');
const { spawn } = require('child_process');
const { createHash, randomUUID } = require('crypto');
const path = require('path');
const { FixedAreaChangeTracker, rectanglesOverlap } = require('./fixed_area');
const { normalizeCaptureShortcut, hasShortcutConflict } = require('./shortcut');

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
const FIXED_CAPTURE_INTERVAL_MS = 650;
const INTRO_FALLBACK_MS = 5000;
const RESULT_CACHE_CAPACITY = 64;
const RESULT_CACHE_TTL_MS = 10 * 60 * 1000;
const CLIENT_ID = randomUUID();
const SOURCE_LANGUAGES = new Set(['en']);
const TARGET_LANGUAGES = new Set(['pt-BR', 'en']);
const OCR_ENGINES = new Set(['tesseract', 'paddleocr', 'easyocr']);
const TOAST_POSITIONS = new Set(['custom', 'mouse', 'top', 'bottom', 'center']);
const SHORTCUT_ACTIONS = new Set(['fixed', 'temporary', 'stop']);

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
const registeredKeyboardShortcuts = new Map();
let isStartingSnip = false;
let snipMode = null;
let activeTranslation = null;
let nextTranslationId = 0;
let fixedCaptureRegion = null;
let fixedCaptureTimer = null;
let fixedCaptureGeneration = 0;
let fixedCaptureRunning = false;
let fixedCaptureLastError = '';
const resultCache = new Map();
const fixedCaptureTracker = new FixedAreaChangeTracker();

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
    captureShortcutType: 'keyboard',
    captureShortcutValue: 'Ctrl+Shift+Q',
    temporaryShortcutType: 'keyboard',
    temporaryShortcutValue: 'Ctrl+Shift+W',
    stopShortcutType: 'keyboard',
    stopShortcutValue: 'Ctrl+Shift+E'
};

const shortcutSettingKeys = {
    fixed: ['captureShortcutType', 'captureShortcutValue'],
    temporary: ['temporaryShortcutType', 'temporaryShortcutValue'],
    stop: ['stopShortcutType', 'stopShortcutValue']
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

function configureFullscreenOverlay(window) {
    if (!isWindowAlive(window)) {
        return;
    }

    window.setAlwaysOnTop(true, 'screen-saver');
}

function showOverlay(window, inactive = false) {
    if (!isWindowAlive(window)) {
        return;
    }

    configureFullscreenOverlay(window);
    if (inactive) {
        window.showInactive();
    } else {
        window.show();
    }
    window.moveTop();
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

function getFixedAreaState() {
    return {
        active: Boolean(fixedCaptureRegion),
        selecting: isStartingSnip || isWindowAlive(snipWindow)
    };
}

function publishFixedAreaState() {
    sendToWindow(settingsWindow, 'fixed-area-state', getFixedAreaState());
}

function stopFixedCapture() {
    const hadFixedCapture = Boolean(fixedCaptureRegion) || fixedCaptureTimer !== null;
    if (fixedCaptureTimer) {
        clearTimeout(fixedCaptureTimer);
        fixedCaptureTimer = null;
    }
    fixedCaptureGeneration += 1;
    fixedCaptureRegion = null;
    fixedCaptureRunning = false;
    fixedCaptureTracker.reset();
    fixedCaptureLastError = '';
    if (hadFixedCapture) {
        cancelActiveTranslation();
        nextTranslationId += 1;
    }
    publishFixedAreaState();
}

function stopAreaCapture() {
    snipMode = null;
    if (isWindowAlive(snipWindow)) {
        const currentSnip = snipWindow;
        snipWindow = null;
        snipDisplay = null;
        closeWindow(currentSnip);
    }
    stopFixedCapture();
    cancelActiveTranslation();
    nextTranslationId += 1;
    closeToastWindow();
    publishFixedAreaState();
}

function getPowerShellPath() {
    const systemRoot = process.env.SystemRoot || 'C:\\Windows';
    return path.join(systemRoot, 'System32', 'WindowsPowerShell', 'v1.0', 'powershell.exe');
}

function isMouseShortcutButton(value) {
    return value === 'MBUTTON' || value === 'XBUTTON1' || value === 'XBUTTON2';
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

    const mouseShortcuts = [...SHORTCUT_ACTIONS]
        .map(action => ({ action, shortcut: getConfiguredShortcut(action) }))
        .filter(item => item.shortcut.type === 'mouse' && isMouseShortcutButton(item.shortcut.value));
    if (process.platform !== 'win32' || mouseShortcuts.length === 0) {
        return;
    }

    const hookPath = path.join(__dirname, 'mouse_hook.ps1');
    const hookProcess = spawn(getPowerShellPath(), [
        '-NoProfile',
        '-ExecutionPolicy',
        'Bypass',
        '-File',
        hookPath,
        '-Buttons',
        mouseShortcuts.map(item => item.shortcut.value).join(',')
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
            const pressedButton = line.trim();
            const match = mouseShortcuts.find(item => item.shortcut.value === pressedButton);
            if (match) {
                runShortcutAction(match.action);
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

function getConfiguredShortcut(action) {
    const [typeKey, valueKey] = shortcutSettingKeys[action];
    return { type: settings[typeKey], value: settings[valueKey] };
}

function runShortcutAction(action) {
    if (action === 'fixed') {
        void startSnip('fixed');
    } else if (action === 'temporary') {
        void startSnip('temporary');
    } else if (action === 'stop') {
        stopAreaCapture();
    }
}

function unregisterKeyboardShortcut(action) {
    const accelerator = registeredKeyboardShortcuts.get(action);
    if (accelerator) {
        globalShortcut.unregister(accelerator);
        registeredKeyboardShortcuts.delete(action);
    }
}

function setCaptureShortcut(action, type, value) {
    if (!SHORTCUT_ACTIONS.has(action)) {
        return { ok: false, error: 'Ação de atalho inválida.' };
    }
    const shortcut = normalizeCaptureShortcut(type, value);
    if (!shortcut) {
        return { ok: false, error: 'Atalho inválido.' };
    }

    const configuredShortcuts = Object.fromEntries(
        [...SHORTCUT_ACTIONS].map(shortcutAction => [shortcutAction, getConfiguredShortcut(shortcutAction)])
    );
    const duplicate = hasShortcutConflict(action, shortcut, configuredShortcuts);
    if (duplicate) {
        return { ok: false, error: 'Esse atalho já está configurado para outra ação.' };
    }

    if (shortcut.type === 'keyboard') {
        if (registeredKeyboardShortcuts.get(action) === shortcut.value) {
            return { ok: true, shortcut };
        }
        if (globalShortcut.isRegistered(shortcut.value)) {
            return { ok: false, error: 'Esse atalho já está sendo usado por outro aplicativo.' };
        }
        const registered = globalShortcut.register(shortcut.value, () => {
            runShortcutAction(action);
        });
        if (!registered) {
            return { ok: false, error: 'O Windows não permitiu registrar esse atalho.' };
        }

        unregisterKeyboardShortcut(action);
        registeredKeyboardShortcuts.set(action, shortcut.value);
    } else {
        unregisterKeyboardShortcut(action);
    }

    const [typeKey, valueKey] = shortcutSettingKeys[action];
    settings[typeKey] = shortcut.type;
    settings[valueKey] = shortcut.value;
    startSideMouseShortcut();
    return { ok: true, shortcut };
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

function fixedAreaBounds(display) {
    if (!fixedCaptureRegion || fixedCaptureRegion.displayId !== display.id) {
        return null;
    }
    const selection = fixedCaptureRegion.selection;
    return {
        x: display.bounds.x + selection.x,
        y: display.bounds.y + selection.y,
        width: selection.width,
        height: selection.height
    };
}

function positionOutsideFixedArea(position, workArea, display) {
    const monitoredArea = fixedAreaBounds(display);
    if (!monitoredArea) {
        return position;
    }
    const toastArea = { ...position, width: TOAST_WIDTH, height: TOAST_HEIGHT };
    if (!rectanglesOverlap(toastArea, monitoredArea)) {
        return position;
    }

    const candidates = [
        { x: position.x, y: monitoredArea.y - TOAST_HEIGHT - TOAST_MARGIN },
        { x: position.x, y: monitoredArea.y + monitoredArea.height + TOAST_MARGIN },
        { x: monitoredArea.x - TOAST_WIDTH - TOAST_MARGIN, y: position.y },
        { x: monitoredArea.x + monitoredArea.width + TOAST_MARGIN, y: position.y }
    ];
    for (const candidate of candidates) {
        const clamped = clampToastPosition(candidate, workArea);
        const candidateArea = { ...clamped, width: TOAST_WIDTH, height: TOAST_HEIGHT };
        if (!rectanglesOverlap(candidateArea, monitoredArea)) {
            return clamped;
        }
    }
    return position;
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
            showOverlay(currentToast, true);
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
        showOverlay(currentToast, true);
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

    const clampedPosition = positionOutsideFixedArea(
        clampToastPosition({ x: posX, y: posY }, workArea),
        workArea,
        display
    );

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

async function startSnip(mode = 'fixed') {
    if (mode !== 'fixed' && mode !== 'temporary') {
        return;
    }
    if (isStartingSnip || isWindowAlive(snipWindow)) {
        return;
    }

    stopFixedCapture();
    isStartingSnip = true;
    snipMode = mode;
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
        configureFullscreenOverlay(currentSnip);

        snipWindow = currentSnip;
        snipDisplay = display;
        currentSnip.on('closed', () => {
            if (snipWindow === currentSnip) {
                snipWindow = null;
                snipDisplay = null;
                snipMode = null;
                publishFixedAreaState();
            }
        });

        await currentSnip.loadFile(path.join(__dirname, 'snip.html'));
        if (!isWindowAlive(currentSnip) || snipWindow !== currentSnip || snipMode !== mode) {
            closeWindow(currentSnip);
            return;
        }

        showOverlay(currentSnip);
        publishFixedAreaState();
    } catch (error) {
        console.error('Failed to open screen selector:', error);
        if (isWindowAlive(snipWindow)) {
            closeWindow(snipWindow);
        }
        snipWindow = null;
        snipDisplay = null;
        snipMode = null;
        publishFixedAreaState();
        showToast('Não foi possível abrir o seletor de tela.', captureDisplay.bounds.x, captureDisplay.bounds.y, settings, captureDisplay);
    } finally {
        isStartingSnip = false;
        publishFixedAreaState();
    }
}

function wait(milliseconds) {
    return new Promise(resolve => setTimeout(resolve, milliseconds));
}

async function captureSelection(selection, display, options = {}) {
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
        height: bottom - top,
        performance: {
            captureMs: Number(captureMs.toFixed(2)),
            cropMs: Number(cropMs.toFixed(2)),
            encodeMs: Number(encodeMs.toFixed(2)),
            totalMs: Number((performance.now() - totalStartedAt).toFixed(2)),
            cropPixels: (right - left) * (bottom - top),
            encodedBytes: png.length
        }
    };

    if (options.logPerformance !== false) {
        console.info('[performance]', JSON.stringify({
            stage: 'capture',
            ...result.performance
        }));
    }
    return result;
}

async function translateTemporarySelection(selection, display) {
    const translationId = ++nextTranslationId;
    const anchorPoint = {
        x: display.bounds.x + selection.x,
        y: display.bounds.y + selection.y
    };

    try {
        const captured = await captureSelection(selection, display);
        if (translationId !== nextTranslationId) {
            return;
        }
        await translateSelection(captured, anchorPoint, display, translationId);
    } catch (error) {
        if (translationId === nextTranslationId) {
            showToast(errorMessageForTranslation(error, false), anchorPoint.x, anchorPoint.y, settings, display);
        }
    }
}

function scheduleFixedCapture(generation, delay = FIXED_CAPTURE_INTERVAL_MS) {
    if (generation !== fixedCaptureGeneration || !fixedCaptureRegion) {
        return;
    }
    if (fixedCaptureTimer) {
        clearTimeout(fixedCaptureTimer);
    }
    fixedCaptureTimer = setTimeout(() => {
        fixedCaptureTimer = null;
        void runFixedCapture(generation);
    }, delay);
}

function startFixedCapture(selection, display) {
    stopFixedCapture();
    fixedCaptureRegion = {
        selection: { ...selection },
        displayId: display.id
    };
    fixedCaptureGeneration += 1;
    const generation = fixedCaptureGeneration;
    publishFixedAreaState();
    scheduleFixedCapture(generation, 0);
}

async function runFixedCapture(generation) {
    if (generation !== fixedCaptureGeneration || !fixedCaptureRegion || fixedCaptureRunning) {
        return;
    }

    fixedCaptureRunning = true;
    const region = fixedCaptureRegion;
    const display = screen.getAllDisplays().find(item => item.id === region.displayId)
        || screen.getPrimaryDisplay();
    const anchorPoint = {
        x: display.bounds.x + region.selection.x,
        y: display.bounds.y + region.selection.y
    };

    try {
        let hiddenToast = null;
        const monitoredArea = fixedAreaBounds(display);
        if (
            monitoredArea
            && isWindowAlive(toastWindow)
            && toastWindow.isVisible()
            && rectanglesOverlap(toastWindow.getBounds(), monitoredArea)
        ) {
            hiddenToast = toastWindow;
            hiddenToast.hide();
            await wait(50);
        }

        let captured;
        try {
            captured = await captureSelection(region.selection, display, {
                logPerformance: false
            });
        } finally {
            if (isWindowAlive(hiddenToast)) {
                showOverlay(hiddenToast, true);
            }
        }
        if (generation !== fixedCaptureGeneration || !fixedCaptureRegion) {
            return;
        }
        if (!fixedCaptureTracker.updateDigest(captured.digest)) {
            return;
        }

        fixedCaptureLastError = '';
        console.info('[performance]', JSON.stringify({
            stage: 'fixed-capture-change',
            ...captured.performance
        }));
        const translationId = ++nextTranslationId;
        await translateSelection(captured, anchorPoint, display, translationId, {
            showLoading: false,
            handleErrors: false,
            shouldDisplay: payload => {
                if (generation !== fixedCaptureGeneration || !fixedCaptureRegion) {
                    return false;
                }
                const sourceText = payload.sourceText.trim();
                if (!sourceText) {
                    fixedCaptureTracker.updateText('');
                    closeToastWindow();
                    return false;
                }
                return fixedCaptureTracker.updateText(sourceText);
            }
        });
    } catch (error) {
        if (generation === fixedCaptureGeneration && fixedCaptureRegion) {
            const message = errorMessageForTranslation(error, false);
            if (message !== fixedCaptureLastError) {
                fixedCaptureLastError = message;
                showToast(message, anchorPoint.x, anchorPoint.y, settings, display);
            }
        }
    } finally {
        fixedCaptureRunning = false;
        scheduleFixedCapture(generation);
    }
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

async function translateSelection(selection, anchorPoint, display, translationId, options = {}) {
    if (translationId !== nextTranslationId) {
        return;
    }
    cancelActiveTranslation();

    const requestSettings = { ...settings };
    const shouldDisplay = typeof options.shouldDisplay === 'function'
        ? options.shouldDisplay
        : () => true;
    const cacheKey = resultCacheKey(selection, requestSettings);
    const cachedPayload = getCachedResult(cacheKey);
    if (cachedPayload) {
        if (shouldDisplay(cachedPayload)) {
            displayTranslationPayload(cachedPayload, anchorPoint, requestSettings, display);
        }
        console.info('[performance]', JSON.stringify({
            stage: 'translation',
            requestId: translationId,
            clientCacheHit: true,
            totalMs: 0
        }));
        return cachedPayload;
    }

    const controller = new AbortController();
    activeTranslation = { id: translationId, controller };
    if (options.showLoading !== false) {
        showToast('Traduzindo...', anchorPoint.x, anchorPoint.y, requestSettings, display);
    }
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
        if (shouldDisplay(payload)) {
            displayTranslationPayload(payload, anchorPoint, requestSettings, display);
        }
        console.info('[performance]', JSON.stringify({
            stage: 'translation',
            requestId: translationId,
            clientCacheHit: false,
            totalMs: Number((performance.now() - requestStartedAt).toFixed(2)),
            server: payload.performance || null
        }));
        return payload;
    } catch (error) {
        if (!isCurrentTranslation(translationId)) {
            return;
        }

        if (options.handleErrors === false) {
            throw error;
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
    for (const action of SHORTCUT_ACTIONS) {
        const shortcut = getConfiguredShortcut(action);
        const shortcutResult = setCaptureShortcut(action, shortcut.type, shortcut.value);
        if (!shortcutResult.ok) {
            console.error(`Could not register default ${action} shortcut: ${shortcutResult.error}`);
        }
    }
});

app.on('will-quit', () => {
    if (introFallbackTimer) {
        clearTimeout(introFallbackTimer);
        introFallbackTimer = null;
    }
    cancelActiveTranslation();
    stopFixedCapture();
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
    updateSettings(newSettings);
});

ipcMain.handle('set-capture-shortcut', (event, shortcut) => {
    if (!isEventFromWindow(event, settingsWindow) || !isPlainObject(shortcut)) {
        return { ok: false, error: 'Solicitação de atalho inválida.' };
    }
    return setCaptureShortcut(shortcut.action, shortcut.type, shortcut.value);
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

ipcMain.on('toggle-fixed-area', event => {
    if (!isEventFromWindow(event, settingsWindow)) {
        return;
    }

    const state = getFixedAreaState();
    if (state.active || state.selecting) {
        stopAreaCapture();
        return;
    }

    settingsWindow.minimize();
    void startSnip('fixed');
});

ipcMain.handle('fixed-area-state', event => {
    if (!isEventFromWindow(event, settingsWindow)) {
        return { active: false, selecting: false };
    }
    return getFixedAreaState();
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
    const completedMode = snipMode;
    snipWindow = null;
    snipDisplay = null;
    snipMode = null;
    if (isWindowAlive(currentSnip)) {
        currentSnip.hide();
        currentSnip.destroy();
    }
    if (!selection) {
        publishFixedAreaState();
        showToast('A seleção capturada é inválida ou grande demais.', display.bounds.x, display.bounds.y, settings, display);
        return;
    }

    if (completedMode === 'temporary') {
        publishFixedAreaState();
        void translateTemporarySelection(selection, display);
    } else {
        startFixedCapture(selection, display);
    }
});

ipcMain.on('snip-cancel', event => {
    if (!isEventFromWindow(event, snipWindow)) {
        return;
    }

    const currentSnip = snipWindow;
    snipWindow = null;
    snipDisplay = null;
    snipMode = null;
    closeWindow(currentSnip);
    publishFixedAreaState();
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
