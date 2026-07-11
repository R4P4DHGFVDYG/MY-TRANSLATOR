(() => {
  if (window.__hqOcrTranslatorLoaded) {
    return;
  }
  window.__hqOcrTranslatorLoaded = true;

  let selectionLayer = null;
  let resultOverlay = null;
  let dragState = null;

  chrome.runtime.onMessage.addListener((message) => {
    if (!message || typeof message.type !== "string") {
      return;
    }

    if (message.type === "HQ_OCR_ENABLE_SELECTION") {
      enableSelection();
    }
    if (message.type === "HQ_OCR_SHOW_LOADING") {
      showOverlay(message.selection, "loading");
    }
    if (message.type === "HQ_OCR_SHOW_RESULT") {
      showOverlay(message.selection, "result", message.result);
    }
    if (message.type === "HQ_OCR_SHOW_ERROR") {
      showOverlay(message.selection, "error", { error: message.error });
    }
  });

  function enableSelection() {
    removeSelectionLayer();
    removeResultOverlay();

    selectionLayer = document.createElement("div");
    selectionLayer.className = "hq-ocr-selection-layer";
    selectionLayer.innerHTML = '<div class="hq-ocr-selection-box"></div>';
    document.documentElement.appendChild(selectionLayer);

    const box = selectionLayer.querySelector(".hq-ocr-selection-box");
    selectionLayer.addEventListener("mousedown", (event) => beginDrag(event, box));
    selectionLayer.addEventListener("mousemove", (event) => updateDrag(event, box));
    selectionLayer.addEventListener("mouseup", finishDrag);
    window.addEventListener("keydown", cancelOnEscape, true);
  }

  function beginDrag(event, box) {
    if (event.button !== 0) {
      return;
    }

    event.preventDefault();
    dragState = {
      startX: event.clientX,
      startY: event.clientY,
      currentX: event.clientX,
      currentY: event.clientY
    };
    drawBox(box, dragState);
  }

  function updateDrag(event, box) {
    if (!dragState) {
      return;
    }

    dragState.currentX = event.clientX;
    dragState.currentY = event.clientY;
    drawBox(box, dragState);
  }

  function finishDrag(event) {
    if (!dragState) {
      return;
    }

    dragState.currentX = event.clientX;
    dragState.currentY = event.clientY;
    const selection = normalizeSelection(dragState);
    dragState = null;
    removeSelectionLayer();

    if (selection.width < 8 || selection.height < 8) {
      showOverlay(selection, "error", { error: "Selection is too small" });
      return;
    }

    chrome.runtime.sendMessage({
      type: "HQ_OCR_SELECTION_READY",
      selection,
      viewport: {
        width: window.innerWidth,
        height: window.innerHeight
      }
    }, () => {
      void chrome.runtime.lastError;
    });
  }

  function drawBox(box, state) {
    const selection = normalizeSelection(state);
    box.style.left = `${selection.x}px`;
    box.style.top = `${selection.y}px`;
    box.style.width = `${selection.width}px`;
    box.style.height = `${selection.height}px`;
  }

  function normalizeSelection(state) {
    const x = Math.min(state.startX, state.currentX);
    const y = Math.min(state.startY, state.currentY);
    const width = Math.abs(state.currentX - state.startX);
    const height = Math.abs(state.currentY - state.startY);
    return { x, y, width, height };
  }

  function cancelOnEscape(event) {
    if (event.key === "Escape") {
      dragState = null;
      removeSelectionLayer();
    }
  }

  function removeSelectionLayer() {
    if (selectionLayer) {
      selectionLayer.remove();
      selectionLayer = null;
    }
    window.removeEventListener("keydown", cancelOnEscape, true);
  }

  function showOverlay(selection, state, payload = {}) {
    removeResultOverlay();

    resultOverlay = document.createElement("section");
    resultOverlay.className = `hq-ocr-result-overlay hq-ocr-${state}`;
    resultOverlay.style.left = `${overlayLeft(selection)}px`;
    resultOverlay.style.top = `${overlayTop(selection)}px`;

    const closeButton = document.createElement("button");
    closeButton.className = "hq-ocr-close";
    closeButton.type = "button";
    closeButton.textContent = "x";
    closeButton.title = "Fechar";
    closeButton.addEventListener("click", removeResultOverlay);

    const title = document.createElement("div");
    title.className = "hq-ocr-title";

    const body = document.createElement("div");
    body.className = "hq-ocr-body";

    if (state === "loading") {
      title.textContent = "Traduzindo";
      body.innerHTML = '<div class="hq-ocr-spinner"></div><span>OCR em andamento...</span>';
    } else if (state === "error") {
      title.textContent = "Erro";
      body.textContent = payload.error || "Falha ao traduzir a selecao.";
    } else {
      title.textContent = "Traducao";
      renderResult(body, payload);
    }

    resultOverlay.append(closeButton, title, body);
    document.documentElement.appendChild(resultOverlay);
  }

  function renderResult(body, result) {
    const translated = document.createElement("div");
    translated.className = "hq-ocr-translated";
    translated.textContent = result.translatedText || "Nenhum texto traduzido.";
    body.appendChild(translated);

    if (result.sourceText) {
      const source = document.createElement("details");
      source.className = "hq-ocr-source";
      const summary = document.createElement("summary");
      summary.textContent = "Texto OCR";
      const content = document.createElement("p");
      content.textContent = result.sourceText;
      source.append(summary, content);
      body.appendChild(source);
    }

    if (Array.isArray(result.warnings) && result.warnings.length) {
      const warning = document.createElement("div");
      warning.className = "hq-ocr-warning";
      warning.textContent = result.warnings[0];
      body.appendChild(warning);
    }
  }

  function removeResultOverlay() {
    if (resultOverlay) {
      resultOverlay.remove();
      resultOverlay = null;
    }
  }

  function overlayLeft(selection) {
    const preferred = selection.x;
    const max = Math.max(12, window.innerWidth - 376);
    return Math.min(Math.max(12, preferred), max);
  }

  function overlayTop(selection) {
    const below = selection.y + selection.height + 10;
    if (below < window.innerHeight - 180) {
      return below;
    }
    return Math.max(12, selection.y - 180);
  }
})();
