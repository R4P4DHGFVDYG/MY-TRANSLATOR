from __future__ import annotations

from typing import Any

import requests

from .cache import TTLCache
from .config import BridgeConfig


class LibreTranslateClient:
    def __init__(self, config: BridgeConfig) -> None:
        self.config = config
        self.base_url = config.libretranslate_url.rstrip("/")
        self._cache = TTLCache()

    def health(self) -> dict[str, Any]:
        try:
            response = requests.get(
                f"{self.base_url}/languages",
                timeout=self.config.request_timeout_seconds,
            )
            response.raise_for_status()
            languages = response.json()
            return {
                "ok": True,
                "url": self.base_url,
                "languages": [item.get("code") for item in languages if isinstance(item, dict)],
            }
        except Exception as exc:
            return {"ok": False, "url": self.base_url, "error": str(exc)}

    def translate(self, text: str, source: str = "en", target: str = "pt") -> str:
        if not text.strip() or source == target:
            return text

        cache_key = (source, target, text)
        cached = self._cache.get(cache_key)
        if isinstance(cached, str):
            return cached

        try:
            response = requests.post(
                f"{self.base_url}/translate",
                json={
                    "q": text,
                    "source": source,
                    "target": target,
                    "format": "text",
                },
                timeout=self.config.request_timeout_seconds,
            )
            response.raise_for_status()
            payload = response.json()
        except requests.RequestException as exc:
            raise RuntimeError(f"LibreTranslate request failed: {exc}") from exc
        except ValueError as exc:
            raise RuntimeError("LibreTranslate returned invalid JSON") from exc

        translated = payload.get("translatedText")
        if not isinstance(translated, str):
            raise RuntimeError("LibreTranslate response did not include translatedText")

        self._cache.set(cache_key, translated)
        return translated
