import {
  CONFIG_VERSION,
  VALID_ENGINES,
  fetchJsonWithTimeout,
  formatHealthStatus,
  responseErrorMessage,
  sanitizeStoredConfig,
  validateBridgeUrl,
  validateEngines,
  validateLanguageCode
} from "./shared.js";

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

const engineInputs = {
  easyocr: easyocrEl,
  paddleocr: paddleocrEl,
  tesseract: tesseractEl
};

void loadOptions();

form.addEventListener("submit", async (event) => {
  event.preventDefault();
  try {
    const config = readFormConfig();
    await chrome.storage.sync.set(config);
    setStatus("Opções salvas.");
  } catch (error) {
    setStatus(`Falha: ${error.message}`);
  }
});

healthButton.addEventListener("click", async () => {
  setStatus("Verificando bridge...");
  try {
    const bridgeUrl = validateBridgeUrl(bridgeUrlEl.value);
    const { response, payload } = await fetchJsonWithTimeout(`${bridgeUrl}/health`);
    if (!response.ok) {
      throw new Error(responseErrorMessage(payload, `Bridge retornou HTTP ${response.status}.`));
    }
    setStatus(formatHealthStatus(payload));
  } catch (error) {
    setStatus(`Falha: ${error.message}`);
  }
});

async function loadOptions() {
  try {
    const stored = await chrome.storage.sync.get();
    const config = sanitizeStoredConfig(stored);
    bridgeUrlEl.value = config.bridgeUrl;
    sourceEl.value = config.source;
    targetEl.value = config.target;
    for (const engine of VALID_ENGINES) {
      engineInputs[engine].checked = config.engines.includes(engine);
    }
    debugCapturesEl.checked = config.debugCaptures;
  } catch (error) {
    setStatus(`Falha ao carregar opções: ${error.message}`);
  }
}

function readFormConfig() {
  const engines = VALID_ENGINES.filter((engine) => engineInputs[engine].checked);
  return {
    bridgeUrl: validateBridgeUrl(bridgeUrlEl.value),
    source: validateLanguageCode(sourceEl.value),
    target: validateLanguageCode(targetEl.value),
    engines: validateEngines(engines),
    debugCaptures: debugCapturesEl.checked,
    configVersion: CONFIG_VERSION
  };
}

function setStatus(text) {
  statusEl.textContent = text;
}
