import {
  CONFIG_VERSION,
  REQUEST_TIMEOUT_MS,
  cropBoundsForImage,
  fetchJsonWithTimeout,
  isRecord,
  responseErrorMessage,
  sanitizeStoredConfig
} from "./shared.js";

const MIN_SELECTION_SIZE = 8;
const DATA_URL_CHUNK_BYTES = 0x8000;
const activeOperations = new Map();

class OperationCancelledError extends Error {
  constructor() {
    super("Operação cancelada.");
    this.name = "OperationCancelledError";
  }
}

chrome.runtime.onInstalled.addListener(() => {
  void migrateStoredConfig();
});

chrome.runtime.onStartup.addListener(() => {
  void migrateStoredConfig();
});

chrome.commands.onCommand.addListener((command) => {
  if (command === "start-selection") {
    startSelection().catch(() => {
      // Shortcut errors cannot be returned to the popup UI.
    });
  }
});

chrome.tabs.onRemoved.addListener((tabId) => {
  cancelOperation(tabId, "A aba foi fechada.", false);
});

chrome.tabs.onUpdated.addListener((tabId, changeInfo) => {
  if (changeInfo.status === "loading") {
    cancelOperation(tabId, "A página foi recarregada.", false);
  }
});

chrome.tabs.onActivated.addListener(({ tabId, windowId }) => {
  for (const operation of activeOperations.values()) {
    if (operation.windowId === windowId && operation.tabId !== tabId) {
      cancelOperation(operation.tabId, "A aba deixou de estar ativa.");
    }
  }
});

chrome.runtime.onMessage.addListener((message, sender, sendResponse) => {
  if (!message || typeof message.type !== "string") {
    return false;
  }

  if (message.type === "HQ_OCR_START_SELECTION") {
    startSelection()
      .then(() => sendResponse({ ok: true }))
      .catch((error) => sendResponse({ ok: false, error: error.message }));
    return true;
  }

  if (message.type === "HQ_OCR_SELECTION_READY") {
    const operation = getSelectionOperation(sender.tab, message.operationId);
    if (!operation) {
      sendResponse({ ok: false, error: "A seleção expirou. Inicie uma nova seleção." });
      return false;
    }

    operation.phase = "translating";
    void completeTranslation(operation, sender.tab, message, sendResponse);
    return true;
  }

  if (message.type === "HQ_OCR_SELECTION_CANCELLED") {
    const operation = getCurrentOperation(sender.tab?.id);
    if (operation && operation.operationId === message.operationId) {
      cancelOperation(operation.tabId, "A seleção foi cancelada.", false);
    }
    sendResponse({ ok: true });
    return false;
  }

  return false;
});

async function migrateStoredConfig() {
  try {
    const stored = await chrome.storage.sync.get();
    const normalized = sanitizeStoredConfig(stored);
    if (storedConfigDiffers(stored, normalized)) {
      await chrome.storage.sync.set(normalized);
    }
  } catch {
    // Storage failures are surfaced when the user starts a new selection.
  }
}

function storedConfigDiffers(stored, normalized) {
  return stored.configVersion !== CONFIG_VERSION
    || stored.bridgeUrl !== normalized.bridgeUrl
    || stored.source !== normalized.source
    || stored.target !== normalized.target
    || stored.debugCaptures !== normalized.debugCaptures
    || !sameEngines(stored.engines, normalized.engines);
}

function sameEngines(left, right) {
  return Array.isArray(left)
    && left.length === right.length
    && left.every((engine, index) => engine === right[index]);
}

async function startSelection() {
  const [tab] = await chrome.tabs.query({ active: true, currentWindow: true });
  assertTab(tab);

  const operation = beginOperation(tab);
  try {
    await chrome.scripting.insertCSS({
      target: { tabId: tab.id },
      files: ["contentStyles.css"]
    });
    assertCurrentOperation(operation);

    await chrome.scripting.executeScript({
      target: { tabId: tab.id },
      files: ["contentScript.js"]
    });
    assertCurrentOperation(operation);

    await sendToTab(tab.id, {
      type: "HQ_OCR_ENABLE_SELECTION",
      operationId: operation.operationId
    });
  } catch (error) {
    if (isCurrentOperation(operation)) {
      cancelOperation(operation.tabId, "Não foi possível ativar a seleção.", false);
    }
    throw error;
  }
}

async function completeTranslation(operation, tab, message, sendResponse) {
  try {
    await translateSelection(operation, tab, message);
    sendResponse({ ok: true });
  } catch (error) {
    if (!(error instanceof OperationCancelledError) && isCurrentOperation(operation)) {
      const messageText = errorMessage(error, "Falha ao traduzir a seleção.");
      try {
        await showOperationError(operation, message.selection, messageText);
      } catch {
        // The tab can navigate after the request fails; the original error is still returned.
      }
      sendResponse({ ok: false, error: messageText });
    } else {
      sendResponse({ ok: false, cancelled: true });
    }
  } finally {
    finishOperation(operation);
  }
}

async function translateSelection(operation, tab, message) {
  assertCurrentOperation(operation);
  assertTab(tab);
  const selection = validateSelection(message.selection, message.viewport);
  const viewport = validateViewport(message.viewport);
  const config = await getConfig();

  assertCurrentOperation(operation);
  await ensureTabIsStillActive(tab);
  assertCurrentOperation(operation);

  const imageDataUrl = await chrome.tabs.captureVisibleTab(tab.windowId, { format: "png" });
  if (typeof imageDataUrl !== "string" || !imageDataUrl.startsWith("data:image/png;base64,")) {
    throw new Error("Não foi possível capturar a imagem da aba.");
  }
  const bridgeCapture = await cropCaptureForBridge(
    imageDataUrl,
    selection,
    viewport
  );

  assertCurrentOperation(operation);
  await sendToTab(tab.id, {
    type: "HQ_OCR_SHOW_LOADING",
    operationId: operation.operationId,
    selection
  });
  assertCurrentOperation(operation);

  const { response, payload } = await fetchJsonWithTimeout(
    `${config.bridgeUrl}/v1/translate-selection`,
    {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({
        imageDataUrl: bridgeCapture.imageDataUrl,
        selection: bridgeCapture.selection,
        viewport: bridgeCapture.viewport,
        source: config.source,
        target: config.target,
        engines: config.engines,
        debug: config.debugCaptures,
        requestId: operation.operationId
      }),
      signal: operation.controller.signal
    },
    REQUEST_TIMEOUT_MS
  );

  assertCurrentOperation(operation);
  if (!response.ok) {
    throw new Error(responseErrorMessage(payload, `Bridge retornou HTTP ${response.status}.`));
  }

  const result = validateTranslationResponse(payload);
  await sendToTab(tab.id, {
    type: "HQ_OCR_SHOW_RESULT",
    operationId: operation.operationId,
    selection,
    result
  });
}

async function getConfig() {
  const stored = await chrome.storage.sync.get();
  return sanitizeStoredConfig(stored);
}

async function ensureTabIsStillActive(tab) {
  const [activeTab] = await chrome.tabs.query({ active: true, windowId: tab.windowId });
  if (activeTab?.id !== tab.id) {
    throw new Error("A aba mudou antes da captura. Selecione a área novamente.");
  }
}

async function cropCaptureForBridge(imageDataUrl, selection, viewport) {
  if (typeof OffscreenCanvas !== "function" || typeof createImageBitmap !== "function") {
    throw new Error("Este navegador não oferece suporte ao recorte da captura.");
  }

  const response = await fetch(imageDataUrl);
  if (!response.ok) {
    throw new Error("Não foi possível preparar a captura da aba.");
  }

  const bitmap = await createImageBitmap(await response.blob());
  try {
    const crop = cropBoundsForImage(
      selection,
      viewport,
      bitmap.width,
      bitmap.height
    );
    const canvas = new OffscreenCanvas(crop.width, crop.height);
    const context = canvas.getContext("2d", { alpha: false });
    if (!context) {
      throw new Error("Não foi possível preparar o recorte da captura.");
    }

    context.drawImage(
      bitmap,
      crop.left,
      crop.top,
      crop.width,
      crop.height,
      0,
      0,
      crop.width,
      crop.height
    );
    const croppedBlob = await canvas.convertToBlob({ type: "image/png" });

    return {
      imageDataUrl: await blobToDataUrl(croppedBlob),
      selection: { x: 0, y: 0, width: crop.width, height: crop.height },
      viewport: { width: crop.width, height: crop.height }
    };
  } finally {
    if (typeof bitmap.close === "function") {
      bitmap.close();
    }
  }
}

async function blobToDataUrl(blob) {
  const bytes = new Uint8Array(await blob.arrayBuffer());
  let binary = "";
  for (let offset = 0; offset < bytes.length; offset += DATA_URL_CHUNK_BYTES) {
    binary += String.fromCharCode(
      ...bytes.subarray(offset, offset + DATA_URL_CHUNK_BYTES)
    );
  }

  return `data:${blob.type || "image/png"};base64,${btoa(binary)}`;
}

function validateSelection(selection, viewport) {
  if (!isRecord(selection)) {
    throw new Error("A seleção recebida é inválida.");
  }

  const normalizedViewport = validateViewport(viewport);
  const normalizedSelection = {
    x: nonNegativeFiniteNumber(selection.x, "x"),
    y: nonNegativeFiniteNumber(selection.y, "y"),
    width: positiveFiniteNumber(selection.width, "largura"),
    height: positiveFiniteNumber(selection.height, "altura")
  };

  if (normalizedSelection.x < 0 || normalizedSelection.y < 0
    || normalizedSelection.width < MIN_SELECTION_SIZE
    || normalizedSelection.height < MIN_SELECTION_SIZE
    || normalizedSelection.x + normalizedSelection.width > normalizedViewport.width
    || normalizedSelection.y + normalizedSelection.height > normalizedViewport.height) {
    throw new Error("A seleção está fora da área visível da aba.");
  }

  return normalizedSelection;
}

function validateViewport(viewport) {
  if (!isRecord(viewport)) {
    throw new Error("As dimensões da aba são inválidas.");
  }

  return {
    width: positiveFiniteNumber(viewport.width, "largura da aba"),
    height: positiveFiniteNumber(viewport.height, "altura da aba")
  };
}

function positiveFiniteNumber(value, label) {
  if (typeof value !== "number" || !Number.isFinite(value) || value <= 0) {
    throw new Error(`Valor inválido para ${label}.`);
  }
  return value;
}

function nonNegativeFiniteNumber(value, label) {
  if (typeof value !== "number" || !Number.isFinite(value) || value < 0) {
    throw new Error(`Valor inválido para ${label}.`);
  }
  return value;
}

function errorMessage(error, fallback) {
  return error instanceof Error && error.message ? error.message : fallback;
}

function validateTranslationResponse(payload) {
  if (!isRecord(payload) || typeof payload.translatedText !== "string") {
    throw new Error("O bridge retornou uma resposta de tradução inválida.");
  }
  if ("sourceText" in payload && typeof payload.sourceText !== "string") {
    throw new Error("O bridge retornou um texto OCR inválido.");
  }
  if ("warnings" in payload && !Array.isArray(payload.warnings)) {
    throw new Error("O bridge retornou avisos inválidos.");
  }
  return payload;
}

function assertTab(tab) {
  if (!Number.isInteger(tab?.id) || !Number.isInteger(tab?.windowId)) {
    throw new Error("Não foi possível identificar a aba ativa.");
  }
}

function beginOperation(tab) {
  cancelOperation(tab.id, "Uma nova seleção foi iniciada.");
  const operation = {
    tabId: tab.id,
    windowId: tab.windowId,
    operationId: createOperationId(),
    controller: new AbortController(),
    phase: "selecting"
  };
  activeOperations.set(tab.id, operation);
  return operation;
}

function getSelectionOperation(tab, operationId) {
  if (!Number.isInteger(tab?.id) || typeof operationId !== "string") {
    return null;
  }
  const operation = getCurrentOperation(tab.id);
  if (!operation || operation.operationId !== operationId || operation.phase !== "selecting") {
    return null;
  }
  return operation;
}

function getCurrentOperation(tabId) {
  return Number.isInteger(tabId) ? activeOperations.get(tabId) : null;
}

function assertCurrentOperation(operation) {
  if (!isCurrentOperation(operation)) {
    throw new OperationCancelledError();
  }
}

function isCurrentOperation(operation) {
  return activeOperations.get(operation.tabId) === operation && !operation.controller.signal.aborted;
}

function finishOperation(operation) {
  if (activeOperations.get(operation.tabId) === operation) {
    activeOperations.delete(operation.tabId);
  }
}

function cancelOperation(tabId, reason, notify = true) {
  const operation = activeOperations.get(tabId);
  if (!operation) {
    return;
  }

  activeOperations.delete(tabId);
  operation.controller.abort(new Error(reason));
  if (notify) {
    void sendToTab(tabId, {
      type: "HQ_OCR_CANCEL_OPERATION",
      operationId: operation.operationId
    }).catch(() => {});
  }
}

async function showOperationError(operation, selection, error) {
  await sendToTab(operation.tabId, {
    type: "HQ_OCR_SHOW_ERROR",
    operationId: operation.operationId,
    selection,
    error: error || "Falha ao traduzir a seleção."
  });
}

async function sendToTab(tabId, payload) {
  await chrome.tabs.sendMessage(tabId, payload);
}

function createOperationId() {
  if (typeof crypto.randomUUID === "function") {
    return crypto.randomUUID();
  }
  return `${Date.now()}-${Math.random().toString(36).slice(2)}`;
}
