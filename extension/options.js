const DEFAULT_CONFIG = {
  bridgeUrl: "http://127.0.0.1:8765",
  source: "en",
  target: "pt-BR",
  engines: ["paddleocr", "easyocr"],
  debugCaptures: false
};
const LEGACY_DEFAULT_ENGINES = ["easyocr", "tesseract"];

const form = document.getElementById("optionsForm");
const statusEl = document.getElementById("status");
const bridgeUrlEl = document.getElementById("bridgeUrl");
const sourceEl = document.getElementById("source");
const targetEl = document.getElementById("target");
const easyocrEl = document.getElementById("engineEasyocr");
const paddleocrEl = document.getElementById("enginePaddleocr");
const tesseractEl = document.getElementById("engineTesseract");
const debugCapturesEl = document.getElementById("debugCaptures");
const healthButton = document.getElementById("health");

loadOptions();

form.addEventListener("submit", async (event) => {
  event.preventDefault();
  const engines = [];
  if (easyocrEl.checked) {
    engines.push("easyocr");
  }
  if (paddleocrEl.checked) {
    engines.push("paddleocr");
  }
  if (tesseractEl.checked) {
    engines.push("tesseract");
  }
  if (!engines.length) {
    setStatus("Selecione pelo menos um OCR.");
    return;
  }

  await chrome.storage.sync.set({
    bridgeUrl: bridgeUrlEl.value.trim().replace(/\/+$/, ""),
    source: sourceEl.value.trim().toLowerCase(),
    target: normalizeLanguageCode(targetEl.value),
    engines,
    debugCaptures: debugCapturesEl.checked
  });
  setStatus("Opcoes salvas.");
});

healthButton.addEventListener("click", async () => {
  setStatus("Verificando bridge...");
  try {
    const response = await fetch(`${bridgeUrlEl.value.trim().replace(/\/+$/, "")}/health`);
    const payload = await response.json();
    if (!response.ok) {
      throw new Error(`HTTP ${response.status}`);
    }
    const easy = payload.ocr?.easyocr?.installed ? "EasyOCR ok" : "EasyOCR indisponivel";
    const paddle = payload.ocr?.paddleocr?.installed ? "PaddleOCR ok" : "PaddleOCR indisponivel";
    const tess = payload.ocr?.tesseract?.installed ? "Tesseract ok" : "Tesseract indisponivel";
    const translation = payload.translation?.ok ? "Traducao ok" : "Traducao falhou";
    const order = Array.isArray(payload.translation?.order)
      ? ` (${payload.translation.order.join(" > ")})`
      : "";
    setStatus(`${translation}${order}. ${easy}. ${paddle}. ${tess}.`);
  } catch (error) {
    setStatus(`Falha: ${error.message}`);
  }
});

async function loadOptions() {
  const config = await chrome.storage.sync.get(DEFAULT_CONFIG);
  const engines = normalizeEngines(config.engines);
  bridgeUrlEl.value = config.bridgeUrl;
  sourceEl.value = config.source;
  targetEl.value = normalizeLanguageCode(config.target);
  easyocrEl.checked = engines.includes("easyocr");
  paddleocrEl.checked = engines.includes("paddleocr");
  tesseractEl.checked = engines.includes("tesseract");
  debugCapturesEl.checked = Boolean(config.debugCaptures);
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

function setStatus(text) {
  statusEl.textContent = text;
}
