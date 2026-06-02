const DEFAULT_CONFIG = {
  bridgeUrl: "http://127.0.0.1:8765",
  source: "en",
  target: "pt-BR",
  engines: ["paddleocr", "easyocr"],
  debugCaptures: false
};
const LEGACY_DEFAULT_ENGINES = ["easyocr", "tesseract"];

chrome.runtime.onInstalled.addListener(async () => {
  const current = await chrome.storage.sync.get(DEFAULT_CONFIG);
  await chrome.storage.sync.set({
    ...DEFAULT_CONFIG,
    ...current,
    engines: normalizeEngines(current.engines)
  });
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
    translateSelection(sender.tab, message.selection, message.viewport)
      .then(() => sendResponse({ ok: true }))
      .catch((error) => {
        if (sender.tab?.id) {
          sendToTab(sender.tab.id, {
            type: "HQ_OCR_SHOW_ERROR",
            selection: message.selection,
            error: error.message
          });
        }
        sendResponse({ ok: false, error: error.message });
      });
    return true;
  }

  return false;
});

async function startSelection() {
  const [tab] = await chrome.tabs.query({ active: true, currentWindow: true });
  if (!tab?.id) {
    throw new Error("No active tab found");
  }

  const config = await getConfig();
  await chrome.scripting.insertCSS({
    target: { tabId: tab.id },
    files: ["contentStyles.css"]
  });
  await chrome.scripting.executeScript({
    target: { tabId: tab.id },
    files: ["contentScript.js"]
  });
  await sendToTab(tab.id, {
    type: "HQ_OCR_ENABLE_SELECTION",
    config
  });
}

async function translateSelection(tab, selection, viewport) {
  if (!tab?.id || !tab.windowId) {
    throw new Error("Selection did not come from a browser tab");
  }

  const config = await getConfig();
  await sleep(80);
  const imageDataUrl = await chrome.tabs.captureVisibleTab(tab.windowId, {
    format: "png"
  });
  await sendToTab(tab.id, {
    type: "HQ_OCR_SHOW_LOADING",
    selection
  });

  const response = await fetch(`${trimSlash(config.bridgeUrl)}/v1/translate-selection`, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({
      imageDataUrl,
      selection,
      viewport,
      source: config.source,
      target: config.target,
      engines: config.engines,
      debug: config.debugCaptures
    })
  });
  const payload = await response.json().catch(() => ({}));

  if (!response.ok) {
    throw new Error(payload.error || `Bridge returned HTTP ${response.status}`);
  }

  await sendToTab(tab.id, {
    type: "HQ_OCR_SHOW_RESULT",
    selection,
    result: payload
  });
}

async function getConfig() {
  const config = await chrome.storage.sync.get(DEFAULT_CONFIG);
  const engines = normalizeEngines(config.engines);

  return {
    bridgeUrl: config.bridgeUrl || DEFAULT_CONFIG.bridgeUrl,
    source: config.source || DEFAULT_CONFIG.source,
    target: normalizeLanguageCode(config.target || DEFAULT_CONFIG.target),
    engines,
    debugCaptures: Boolean(config.debugCaptures)
  };
}

async function sendToTab(tabId, payload) {
  await chrome.tabs.sendMessage(tabId, payload);
}

function trimSlash(value) {
  return String(value || "").replace(/\/+$/, "");
}

function normalizeLanguageCode(value) {
  const trimmed = String(value || "").trim();
  return trimmed.toLowerCase() === "pt" || trimmed.toLowerCase() === "pt-br"
    ? "pt-BR"
    : trimmed.toLowerCase();
}

function normalizeEngines(value) {
  const engines = Array.isArray(value)
    ? value.filter((engine) => ["paddleocr", "easyocr", "tesseract"].includes(engine))
    : [];
  if (!engines.length || sameEngines(engines, LEGACY_DEFAULT_ENGINES)) {
    return DEFAULT_CONFIG.engines;
  }
  return engines;
}

function sameEngines(left, right) {
  return left.length === right.length && left.every((engine, index) => engine === right[index]);
}

function sleep(ms) {
  return new Promise((resolve) => setTimeout(resolve, ms));
}
