export const CONFIG_VERSION = 2;

export const DEFAULT_CONFIG = Object.freeze({
  bridgeUrl: "http://127.0.0.1:8765",
  source: "en",
  target: "pt-BR",
  engines: ["paddleocr", "easyocr"],
  debugCaptures: false,
  configVersion: CONFIG_VERSION
});

export const VALID_ENGINES = Object.freeze(["paddleocr", "easyocr", "tesseract"]);
export const REQUEST_TIMEOUT_MS = 45_000;

const LOCAL_BRIDGE_HOSTS = new Set(["127.0.0.1", "localhost"]);
const LANGUAGE_CODE_PATTERN = /^([a-z]{2,3})(?:-([a-z]{2,4}))?$/i;

export function validateBridgeUrl(value) {
  const rawValue = typeof value === "string" ? value.trim() : "";
  if (!rawValue) {
    throw new Error("Informe a URL do bridge.");
  }

  let url;
  try {
    url = new URL(rawValue);
  } catch {
    throw new Error("A URL do bridge é inválida.");
  }

  if (url.protocol !== "http:") {
    throw new Error("O bridge deve usar HTTP local.");
  }
  if (!LOCAL_BRIDGE_HOSTS.has(url.hostname)) {
    throw new Error("Use localhost ou 127.0.0.1 para o bridge.");
  }
  if (url.username || url.password || url.search || url.hash || url.pathname !== "/") {
    throw new Error("A URL do bridge não deve conter caminho, credenciais ou parâmetros.");
  }

  return url.origin;
}

export function normalizeBridgeUrl(value) {
  try {
    return validateBridgeUrl(value);
  } catch {
    return DEFAULT_CONFIG.bridgeUrl;
  }
}

export function validateLanguageCode(value) {
  const rawValue = typeof value === "string" ? value.trim() : "";
  const match = LANGUAGE_CODE_PATTERN.exec(rawValue);
  if (!match) {
    throw new Error("Use um código de idioma como en, ja ou pt-BR.");
  }

  const language = match[1].toLowerCase();
  const region = match[2];
  if (language === "pt") {
    return "pt-BR";
  }
  if (!region) {
    return language;
  }

  const formattedRegion = region.length === 4
    ? `${region[0].toUpperCase()}${region.slice(1).toLowerCase()}`
    : region.toUpperCase();
  return `${language}-${formattedRegion}`;
}

export function normalizeLanguageCode(value, fallback) {
  try {
    return validateLanguageCode(value);
  } catch {
    return fallback;
  }
}

export function normalizeEngines(value, fallback = DEFAULT_CONFIG.engines) {
  const engines = Array.isArray(value)
    ? value
      .map((engine) => String(engine).trim().toLowerCase())
      .filter((engine, index, all) => VALID_ENGINES.includes(engine) && all.indexOf(engine) === index)
    : [];

  return engines.length ? engines : [...fallback];
}

export function validateEngines(value) {
  if (!Array.isArray(value)) {
    throw new Error("Selecione pelo menos um mecanismo de OCR.");
  }

  const engines = normalizeEngines(value, []);
  if (!engines.length) {
    throw new Error("Selecione pelo menos um mecanismo de OCR.");
  }

  return engines;
}

export function sanitizeStoredConfig(value = {}) {
  return {
    bridgeUrl: normalizeBridgeUrl(value.bridgeUrl),
    source: normalizeLanguageCode(value.source, DEFAULT_CONFIG.source),
    target: normalizeLanguageCode(value.target, DEFAULT_CONFIG.target),
    engines: normalizeEngines(value.engines),
    debugCaptures: Boolean(value.debugCaptures),
    configVersion: CONFIG_VERSION
  };
}

export function isRecord(value) {
  return Boolean(value) && typeof value === "object" && !Array.isArray(value);
}

export function cropBoundsForImage(selection, viewport, imageWidth, imageHeight) {
  if (!isRecord(selection) || !isRecord(viewport)) {
    throw new Error("A sele\u00e7\u00e3o da captura \u00e9 inv\u00e1lida.");
  }

  const viewportWidth = positiveFiniteNumber(viewport.width);
  const viewportHeight = positiveFiniteNumber(viewport.height);
  const x = nonNegativeFiniteNumber(selection.x);
  const y = nonNegativeFiniteNumber(selection.y);
  const width = positiveFiniteNumber(selection.width);
  const height = positiveFiniteNumber(selection.height);
  const captureWidth = positiveFiniteNumber(imageWidth);
  const captureHeight = positiveFiniteNumber(imageHeight);

  if (x + width > viewportWidth || y + height > viewportHeight) {
    throw new Error("A sele\u00e7\u00e3o est\u00e1 fora da captura.");
  }

  const left = clamp(Math.round(x * captureWidth / viewportWidth), 0, captureWidth);
  const top = clamp(Math.round(y * captureHeight / viewportHeight), 0, captureHeight);
  const right = clamp(
    Math.round((x + width) * captureWidth / viewportWidth),
    0,
    captureWidth
  );
  const bottom = clamp(
    Math.round((y + height) * captureHeight / viewportHeight),
    0,
    captureHeight
  );

  if (right <= left || bottom <= top) {
    throw new Error("A sele\u00e7\u00e3o n\u00e3o cont\u00e9m pixels vis\u00edveis.");
  }

  return { left, top, width: right - left, height: bottom - top };
}

export function responseErrorMessage(payload, fallback) {
  if (isRecord(payload) && typeof payload.error === "string" && payload.error.trim()) {
    return payload.error.trim();
  }
  return fallback;
}

export async function fetchJsonWithTimeout(url, options = {}, timeoutMs = REQUEST_TIMEOUT_MS) {
  const controller = new AbortController();
  const externalSignal = options.signal;
  let timedOut = false;
  let onExternalAbort;

  if (externalSignal) {
    onExternalAbort = () => controller.abort(externalSignal.reason);
    if (externalSignal.aborted) {
      onExternalAbort();
    } else {
      externalSignal.addEventListener("abort", onExternalAbort, { once: true });
    }
  }

  const timeoutId = setTimeout(() => {
    timedOut = true;
    controller.abort(new Error("Tempo limite excedido."));
  }, timeoutMs);

  try {
    const response = await fetch(url, { ...options, signal: controller.signal });
    const payload = await response.json().catch(() => null);
    return { response, payload };
  } catch (error) {
    if (timedOut) {
      throw new Error("O bridge demorou demais para responder.");
    }
    if (externalSignal?.aborted) {
      const reason = externalSignal.reason;
      throw reason instanceof Error ? reason : new Error("Operação cancelada.");
    }
    throw error;
  } finally {
    clearTimeout(timeoutId);
    if (externalSignal && onExternalAbort) {
      externalSignal.removeEventListener("abort", onExternalAbort);
    }
  }
}

export function formatHealthStatus(payload) {
  if (!isRecord(payload) || !isRecord(payload.bridge) || payload.bridge.ok !== true) {
    throw new Error("A resposta de saúde do bridge é inválida.");
  }

  const translation = isRecord(payload.translation) ? payload.translation : {};
  const translationLabel = translation.ok === true ? "Tradução disponível" : "Tradução indisponível";
  const providerOrder = Array.isArray(translation.order)
    ? translation.order.filter((provider) => typeof provider === "string" && provider.trim())
    : [];
  const providers = providerOrder.length ? ` (${providerOrder.join(" > ")})` : "";

  const ocr = isRecord(payload.ocr) ? payload.ocr : {};
  const engineLabels = [
    ["easyocr", "EasyOCR"],
    ["paddleocr", "PaddleOCR"],
    ["tesseract", "Tesseract"]
  ].map(([key, label]) => {
    const status = isRecord(ocr[key]) && ocr[key].installed === true ? "ok" : "indisponível";
    return `${label} ${status}`;
  });

  return `Bridge ok. ${translationLabel}${providers}. ${engineLabels.join(". ")}.`;
}

function positiveFiniteNumber(value) {
  if (typeof value !== "number" || !Number.isFinite(value) || value <= 0) {
    throw new Error("Dimens\u00f5es da captura inv\u00e1lidas.");
  }
  return value;
}

function nonNegativeFiniteNumber(value) {
  if (typeof value !== "number" || !Number.isFinite(value) || value < 0) {
    throw new Error("Coordenadas da captura inv\u00e1lidas.");
  }
  return value;
}

function clamp(value, min, max) {
  return Math.min(Math.max(value, min), max);
}
