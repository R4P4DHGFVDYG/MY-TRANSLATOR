import assert from "node:assert/strict";
import test from "node:test";

import {
  DEFAULT_CONFIG,
  cropBoundsForImage,
  formatHealthStatus,
  sanitizeStoredConfig,
  validateBridgeUrl,
  validateLanguageCode
} from "../shared.js";

test("maps a CSS selection to captured image pixels", () => {
  const crop = cropBoundsForImage(
    { x: 10, y: 20, width: 30, height: 40 },
    { width: 100, height: 100 },
    200,
    300
  );

  assert.deepEqual(crop, { left: 20, top: 60, width: 60, height: 120 });
});

test("preserves a valid legacy engine selection during migration", () => {
  const config = sanitizeStoredConfig({
    engines: ["easyocr", "tesseract"],
    bridgeUrl: "http://localhost:8765",
    source: "EN",
    target: "pt"
  });

  assert.deepEqual(config.engines, ["easyocr", "tesseract"]);
  assert.equal(config.bridgeUrl, "http://localhost:8765");
  assert.equal(config.source, "en");
  assert.equal(config.target, "pt-BR");
});

test("falls back only when persisted engine configuration is invalid", () => {
  const config = sanitizeStoredConfig({ engines: ["unknown"] });

  assert.deepEqual(config.engines, DEFAULT_CONFIG.engines);
});

test("accepts only local bridge URLs", () => {
  assert.equal(validateBridgeUrl("http://127.0.0.1:8765/"), "http://127.0.0.1:8765");
  assert.throws(() => validateBridgeUrl("https://example.com"));
  assert.throws(() => validateBridgeUrl("http://localhost:8765/api"));
});

test("normalizes language codes", () => {
  assert.equal(validateLanguageCode("PT"), "pt-BR");
  assert.equal(validateLanguageCode("EN-us"), "en-US");
  assert.throws(() => validateLanguageCode("english"));
});

test("uses one health summary for all extension surfaces", () => {
  const status = formatHealthStatus({
    bridge: { ok: true },
    translation: { ok: true, order: ["deepl", "google"] },
    ocr: {
      easyocr: { installed: true },
      paddleocr: { installed: false },
      tesseract: { installed: true }
    }
  });

  assert.match(status, /Tradução disponível \(deepl > google\)/);
  assert.match(status, /EasyOCR ok/);
  assert.match(status, /PaddleOCR indisponível/);
});
