import {
  DEFAULT_CONFIG,
  fetchJsonWithTimeout,
  formatHealthStatus,
  responseErrorMessage,
  validateBridgeUrl
} from "./shared.js";

const statusEl = document.getElementById("status");
const startButton = document.getElementById("startSelection");
const healthButton = document.getElementById("checkHealth");
const optionsButton = document.getElementById("openOptions");

startButton.addEventListener("click", async () => {
  setStatus("Ativando seleção...");
  try {
    const response = await chrome.runtime.sendMessage({ type: "HQ_OCR_START_SELECTION" });
    if (!response?.ok) {
      throw new Error(response?.error || "Não foi possível ativar a seleção.");
    }
    window.close();
  } catch (error) {
    setStatus(`Falha: ${error.message}`);
  }
});

healthButton.addEventListener("click", checkHealth);
optionsButton.addEventListener("click", () => chrome.runtime.openOptionsPage());

async function checkHealth() {
  setStatus("Verificando bridge...");
  try {
    const { bridgeUrl } = await chrome.storage.sync.get({ bridgeUrl: DEFAULT_CONFIG.bridgeUrl });
    const { response, payload } = await fetchJsonWithTimeout(`${validateBridgeUrl(bridgeUrl)}/health`);
    if (!response.ok) {
      throw new Error(responseErrorMessage(payload, `Bridge retornou HTTP ${response.status}.`));
    }
    setStatus(formatHealthStatus(payload));
  } catch (error) {
    setStatus(`Falha: ${error.message}`);
  }
}

function setStatus(text) {
  statusEl.textContent = text;
}
