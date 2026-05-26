const DEFAULT_CONFIG = {
  bridgeUrl: "http://127.0.0.1:8765",
  source: "en",
  target: "pt",
  engines: ["easyocr", "tesseract"]
};

const form = document.getElementById("optionsForm");
const statusEl = document.getElementById("status");
const bridgeUrlEl = document.getElementById("bridgeUrl");
const sourceEl = document.getElementById("source");
const targetEl = document.getElementById("target");
const easyocrEl = document.getElementById("engineEasyocr");
const tesseractEl = document.getElementById("engineTesseract");
const healthButton = document.getElementById("health");

loadOptions();

form.addEventListener("submit", async (event) => {
  event.preventDefault();
  const engines = [];
  if (easyocrEl.checked) {
    engines.push("easyocr");
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
    target: targetEl.value.trim().toLowerCase(),
    engines
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
    const tess = payload.ocr?.tesseract?.installed ? "Tesseract ok" : "Tesseract indisponivel";
    const libre = payload.libretranslate?.ok ? "LibreTranslate ok" : "LibreTranslate falhou";
    setStatus(`${libre}. ${easy}. ${tess}.`);
  } catch (error) {
    setStatus(`Falha: ${error.message}`);
  }
});

async function loadOptions() {
  const config = await chrome.storage.sync.get(DEFAULT_CONFIG);
  bridgeUrlEl.value = config.bridgeUrl;
  sourceEl.value = config.source;
  targetEl.value = config.target;
  easyocrEl.checked = config.engines.includes("easyocr");
  tesseractEl.checked = config.engines.includes("tesseract");
}

function setStatus(text) {
  statusEl.textContent = text;
}
