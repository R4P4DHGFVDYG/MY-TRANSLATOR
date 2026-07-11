const statusEl = document.getElementById("status");
const startButton = document.getElementById("startSelection");
const healthButton = document.getElementById("checkHealth");
const optionsButton = document.getElementById("openOptions");

startButton.addEventListener("click", async () => {
  setStatus("Ativando selecao...");
  const response = await chrome.runtime.sendMessage({ type: "HQ_OCR_START_SELECTION" });
  if (!response?.ok) {
    setStatus(response?.error || "Nao foi possivel ativar a selecao.");
    return;
  }
  window.close();
});

healthButton.addEventListener("click", checkHealth);
optionsButton.addEventListener("click", () => chrome.runtime.openOptionsPage());

async function checkHealth() {
  setStatus("Verificando bridge...");
  const config = await chrome.storage.sync.get({ bridgeUrl: "http://127.0.0.1:8765" });
  try {
    const response = await fetch(`${trimSlash(config.bridgeUrl)}/health`);
    const payload = await response.json();
    if (!response.ok || !payload.bridge?.ok) {
      throw new Error("Bridge retornou erro.");
    }
    const libre = payload.libretranslate?.ok ? "LibreTranslate ok" : "LibreTranslate falhou";
    setStatus(`Bridge ok. ${libre}.`);
  } catch (error) {
    setStatus(`Falha: ${error.message}`);
  }
}

function setStatus(text) {
  statusEl.textContent = text;
}

function trimSlash(value) {
  return String(value || "").replace(/\/+$/, "");
}
