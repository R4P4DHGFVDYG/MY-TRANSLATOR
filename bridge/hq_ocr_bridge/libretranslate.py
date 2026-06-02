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
        self.last_provider: str | None = None
        self.last_warnings: list[str] = []

    def health(self) -> dict[str, Any]:
        libretranslate = (
            self._libretranslate_health()
            if "libretranslate" in self.config.translation_providers
            else self._disabled_libretranslate_health()
        )
        providers = {
            "google": {
                "configured": "google" in self.config.translation_providers,
                "ok": "google" in self.config.translation_providers,
                "url": self.config.google_translate_url,
                "warning": "unofficial endpoint; not health-checked",
            },
            "deepl": {
                "configured": bool(self.config.deepl_auth_key),
                "ok": bool(self.config.deepl_auth_key),
                "url": self.config.deepl_api_url,
            },
            "libretranslate": libretranslate,
        }
        return {
            "ok": any(_provider_usable(name, providers) for name in self.config.translation_providers),
            "order": list(self.config.translation_providers),
            "providers": providers,
            "libretranslate": libretranslate,
        }

    def translate(self, text: str, source: str = "en", target: str = "pt-BR") -> str:
        self.last_provider = None
        self.last_warnings = []
        if not text.strip() or source == target:
            self.last_provider = "none"
            return text

        cache_key = (self.config.translation_providers, source, target, text)
        cached = self._cache.get(cache_key)
        if isinstance(cached, str):
            self.last_provider = "cache"
            return cached

        errors: list[str] = []
        for provider in self.config.translation_providers:
            try:
                if provider == "google":
                    translated = self._translate_google(text, source, target)
                elif provider == "deepl":
                    translated = self._translate_deepl(text, source, target)
                elif provider == "libretranslate":
                    translated = self._translate_libretranslate(text, source, target)
                else:
                    errors.append(f"{provider}: unknown provider")
                    continue
            except RuntimeError as exc:
                errors.append(f"{provider}: {exc}")
                continue

            self.last_provider = provider
            self.last_warnings = errors.copy()
            self._cache.set(cache_key, translated)
            return translated

        raise RuntimeError("Translation failed: " + "; ".join(errors))

    def _libretranslate_health(self) -> dict[str, Any]:
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

    def _disabled_libretranslate_health(self) -> dict[str, Any]:
        return {
            "configured": False,
            "disabled": True,
            "ok": False,
            "url": self.base_url,
        }

    def _translate_google(self, text: str, source: str, target: str) -> str:
        try:
            response = requests.get(
                self.config.google_translate_url,
                params={
                    "client": "gtx",
                    "sl": _google_lang(source),
                    "tl": _google_lang(target),
                    "dt": "t",
                    "q": text,
                },
                timeout=self.config.request_timeout_seconds,
            )
            response.raise_for_status()
            payload = response.json()
        except requests.RequestException as exc:
            raise RuntimeError(f"Google Translate request failed: {exc}") from exc
        except ValueError as exc:
            raise RuntimeError("Google Translate returned invalid JSON") from exc

        translated = _parse_google_payload(payload)
        if not translated:
            raise RuntimeError("Google Translate response did not include text")
        return translated

    def _translate_deepl(self, text: str, source: str, target: str) -> str:
        if not self.config.deepl_auth_key:
            raise RuntimeError("DEEPL_AUTH_KEY is not configured")

        try:
            response = requests.post(
                self.config.deepl_api_url,
                data={
                    "text": text,
                    "source_lang": _deepl_lang(source),
                    "target_lang": _deepl_lang(target),
                },
                headers={"Authorization": f"DeepL-Auth-Key {self.config.deepl_auth_key}"},
                timeout=self.config.request_timeout_seconds,
            )
            response.raise_for_status()
            payload = response.json()
        except requests.RequestException as exc:
            raise RuntimeError(f"DeepL request failed: {exc}") from exc
        except ValueError as exc:
            raise RuntimeError("DeepL returned invalid JSON") from exc

        translations = payload.get("translations")
        if not isinstance(translations, list) or not translations:
            raise RuntimeError("DeepL response did not include translations")
        translated = translations[0].get("text")
        if not isinstance(translated, str):
            raise RuntimeError("DeepL response did not include text")
        return translated

    def _translate_libretranslate(self, text: str, source: str, target: str) -> str:
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

        return translated


def _provider_usable(name: str, providers: dict[str, dict[str, Any]]) -> bool:
    provider = providers.get(name)
    return bool(provider and provider.get("ok"))


def _parse_google_payload(payload: Any) -> str:
    if not isinstance(payload, list) or not payload:
        return ""
    sentences = payload[0]
    if not isinstance(sentences, list):
        return ""

    fragments: list[str] = []
    for sentence in sentences:
        if isinstance(sentence, list) and sentence and isinstance(sentence[0], str):
            fragments.append(sentence[0])
    return "".join(fragments).strip()


def _google_lang(value: str) -> str:
    normalized = value.strip()
    return "pt-BR" if normalized.lower() in {"pt", "pt-br"} else normalized


def _deepl_lang(value: str) -> str:
    normalized = value.strip().upper().replace("-", "_")
    if normalized == "PT":
        return "PT-BR"
    return normalized.replace("_", "-")
