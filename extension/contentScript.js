(() => {
  if (window.__hqOcrTranslatorLoaded) {
    return;
  }
  window.__hqOcrTranslatorLoaded = true;

  const MIN_SELECTION_SIZE = 8;
  const OVERLAY_MARGIN = 12;
  const OVERLAY_GAP = 10;

  let activeOperationId = null;
  let selectionLayer = null;
  let resultOverlay = null;
  let dragState = null;
  let overlaySelection = null;

  chrome.runtime.onMessage.addListener((message, _sender, sendResponse) => {
    if (!message || typeof message.type !== "string") {
      return false;
    }

    if (message.type === "HQ_OCR_ENABLE_SELECTION") {
      if (!isOperationId(message.operationId)) {
        sendResponse({ ok: false });
        return false;
      }
      activeOperationId = message.operationId;
      enableSelection();
      sendResponse({ ok: true });
      return false;
    }

    if (!matchesActiveOperation(message.operationId)) {
      sendResponse({ ok: false, ignored: true });
      return false;
    }

    if (message.type === "HQ_OCR_SHOW_LOADING") {
      showOverlay(message.selection, "loading");
    } else if (message.type === "HQ_OCR_SHOW_RESULT") {
      showOverlay(message.selection, "result", message.result);
    } else if (message.type === "HQ_OCR_SHOW_ERROR") {
      showOverlay(message.selection, "error", { error: message.error });
    } else if (message.type === "HQ_OCR_CANCEL_OPERATION") {
      activeOperationId = null;
      dragState = null;
      removeSelectionLayer();
      removeResultOverlay();
    }

    sendResponse({ ok: true });
    return false;
  });

  window.addEventListener("resize", positionResultOverlay, true);
  window.visualViewport?.addEventListener("resize", positionResultOverlay);

  function enableSelection() {
    removeSelectionLayer();
    removeResultOverlay();

    selectionLayer = document.createElement("div");
    selectionLayer.className = "hq-ocr-selection-layer";
    selectionLayer.setAttribute("aria-hidden", "true");

    const box = document.createElement("div");
    box.className = "hq-ocr-selection-box";
    selectionLayer.appendChild(box);
    document.documentElement.appendChild(selectionLayer);

    selectionLayer.addEventListener("pointerdown", (event) => beginDrag(event, box));
    selectionLayer.addEventListener("pointermove", (event) => updateDrag(event, box));
    selectionLayer.addEventListener("pointerup", (event) => {
      void finishDrag(event);
    });
    selectionLayer.addEventListener("pointercancel", cancelDrag);
    selectionLayer.addEventListener("contextmenu", (event) => event.preventDefault());
    window.addEventListener("keydown", cancelOnEscape, true);
  }

  function beginDrag(event, box) {
    if (!event.isPrimary || event.button !== 0) {
      return;
    }

    event.preventDefault();
    dragState = {
      pointerId: event.pointerId,
      startX: event.clientX,
      startY: event.clientY,
      currentX: event.clientX,
      currentY: event.clientY
    };
    selectionLayer?.setPointerCapture(event.pointerId);
    drawBox(box, dragState);
  }

  function updateDrag(event, box) {
    if (!dragState || event.pointerId !== dragState.pointerId) {
      return;
    }

    event.preventDefault();
    dragState.currentX = event.clientX;
    dragState.currentY = event.clientY;
    drawBox(box, dragState);
  }

  async function finishDrag(event) {
    if (!dragState || event.pointerId !== dragState.pointerId) {
      return;
    }

    event.preventDefault();
    dragState.currentX = event.clientX;
    dragState.currentY = event.clientY;
    const selection = normalizeSelection(dragState);
    const operationId = activeOperationId;
    releasePointer(event.pointerId);
    dragState = null;
    removeSelectionLayer();

    if (selection.width < MIN_SELECTION_SIZE || selection.height < MIN_SELECTION_SIZE) {
      showOverlay(selection, "error", { error: "A seleção é muito pequena." });
      cancelSelection(operationId, true);
      return;
    }

    // Two animation frames acknowledge that the selection layer was removed before capture.
    await waitForNextPaint();
    if (!matchesActiveOperation(operationId)) {
      return;
    }

    try {
      const response = await chrome.runtime.sendMessage({
        type: "HQ_OCR_SELECTION_READY",
        operationId,
        selection,
        viewport: {
          width: window.innerWidth,
          height: window.innerHeight
        }
      });
      if (response?.cancelled && matchesActiveOperation(operationId)) {
        activeOperationId = null;
        removeResultOverlay();
      } else if (!response?.ok && matchesActiveOperation(operationId)) {
        showOverlay(selection, "error", { error: response?.error || "Não foi possível iniciar a tradução." });
        activeOperationId = null;
      }
    } catch {
      if (matchesActiveOperation(operationId)) {
        showOverlay(selection, "error", { error: "Não foi possível comunicar com a extensão." });
        activeOperationId = null;
      }
    }
  }

  function cancelDrag(event) {
    if (!dragState || event.pointerId !== dragState.pointerId) {
      return;
    }
    cancelSelection(activeOperationId);
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
      event.preventDefault();
      cancelSelection(activeOperationId);
    }
  }

  function cancelSelection(operationId, preserveOverlay = false) {
    releasePointer(dragState?.pointerId);
    dragState = null;
    removeSelectionLayer();
    if (!preserveOverlay) {
      removeResultOverlay();
    }
    activeOperationId = null;

    if (isOperationId(operationId)) {
      void chrome.runtime.sendMessage({
        type: "HQ_OCR_SELECTION_CANCELLED",
        operationId
      }).catch(() => {});
    }
  }

  function releasePointer(pointerId) {
    if (Number.isInteger(pointerId) && selectionLayer?.hasPointerCapture(pointerId)) {
      selectionLayer.releasePointerCapture(pointerId);
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
    overlaySelection = normalizeOverlaySelection(selection);

    resultOverlay = document.createElement("section");
    resultOverlay.className = `hq-ocr-result-overlay hq-ocr-${state}`;
    resultOverlay.setAttribute("role", "status");
    resultOverlay.setAttribute("aria-live", state === "error" ? "assertive" : "polite");

    const closeButton = document.createElement("button");
    closeButton.className = "hq-ocr-close";
    closeButton.type = "button";
    closeButton.textContent = "×";
    closeButton.title = "Fechar";
    closeButton.setAttribute("aria-label", "Fechar tradução");
    closeButton.addEventListener("click", () => {
      if (state === "loading") {
        cancelSelection(activeOperationId);
      } else {
        removeResultOverlay();
      }
    });

    const title = document.createElement("div");
    title.className = "hq-ocr-title";

    const body = document.createElement("div");
    body.className = "hq-ocr-body";

    if (state === "loading") {
      title.textContent = "Traduzindo";
      const spinner = document.createElement("div");
      spinner.className = "hq-ocr-spinner";
      const label = document.createElement("span");
      label.textContent = "OCR em andamento...";
      body.append(spinner, label);
    } else if (state === "error") {
      title.textContent = "Erro";
      body.textContent = typeof payload.error === "string" && payload.error.trim()
        ? payload.error
        : "Falha ao traduzir a seleção.";
    } else {
      title.textContent = "Tradução";
      renderResult(body, payload);
    }

    resultOverlay.append(closeButton, title, body);
    document.documentElement.appendChild(resultOverlay);
    positionResultOverlay();
    requestAnimationFrame(positionResultOverlay);
  }

  function renderResult(body, result) {
    const translatedText = typeof result?.translatedText === "string" ? result.translatedText.trim() : "";
    const sourceText = typeof result?.sourceText === "string" ? result.sourceText.trim() : "";
    const translated = document.createElement("div");
    translated.className = "hq-ocr-translated";
    translated.textContent = translatedText || (sourceText ? "Nenhuma tradução disponível." : "Nenhum texto detectado.");
    body.appendChild(translated);

    if (sourceText) {
      const source = document.createElement("details");
      source.className = "hq-ocr-source";
      const summary = document.createElement("summary");
      summary.textContent = "Texto OCR";
      const content = document.createElement("p");
      content.textContent = sourceText;
      source.append(summary, content);
      body.appendChild(source);
    }

    if (Array.isArray(result?.warnings) && result.warnings.length) {
      const firstWarning = result.warnings.find((warning) => typeof warning === "string" && warning.trim());
      if (firstWarning) {
        const warning = document.createElement("div");
        warning.className = "hq-ocr-warning";
        warning.textContent = firstWarning;
        body.appendChild(warning);
      }
    }
  }

  function removeResultOverlay() {
    if (resultOverlay) {
      resultOverlay.remove();
      resultOverlay = null;
    }
    overlaySelection = null;
  }

  function positionResultOverlay() {
    if (!resultOverlay || !overlaySelection) {
      return;
    }

    const rect = resultOverlay.getBoundingClientRect();
    const maxLeft = Math.max(OVERLAY_MARGIN, window.innerWidth - rect.width - OVERLAY_MARGIN);
    const left = clamp(overlaySelection.x, OVERLAY_MARGIN, maxLeft);
    const below = overlaySelection.y + overlaySelection.height + OVERLAY_GAP;
    const maxTop = Math.max(OVERLAY_MARGIN, window.innerHeight - rect.height - OVERLAY_MARGIN);
    const preferredAbove = overlaySelection.y - rect.height - OVERLAY_GAP;
    const top = below + rect.height <= window.innerHeight - OVERLAY_MARGIN
      ? below
      : clamp(preferredAbove, OVERLAY_MARGIN, maxTop);

    resultOverlay.style.left = `${left}px`;
    resultOverlay.style.top = `${top}px`;
  }

  function normalizeOverlaySelection(selection) {
    if (!selection || !Number.isFinite(selection.x) || !Number.isFinite(selection.y)
      || !Number.isFinite(selection.width) || !Number.isFinite(selection.height)) {
      return { x: OVERLAY_MARGIN, y: OVERLAY_MARGIN, width: 0, height: 0 };
    }
    return selection;
  }

  function waitForNextPaint() {
    return new Promise((resolve) => requestAnimationFrame(() => requestAnimationFrame(resolve)));
  }

  function matchesActiveOperation(operationId) {
    return isOperationId(operationId) && operationId === activeOperationId;
  }

  function isOperationId(value) {
    return typeof value === "string" && value.length >= 8;
  }

  function clamp(value, min, max) {
    return Math.min(Math.max(value, min), max);
  }
})();
