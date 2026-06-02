from __future__ import annotations

import requests

from hq_ocr_bridge.config import BridgeConfig
from hq_ocr_bridge.libretranslate import LibreTranslateClient


class FakeResponse:
    def __init__(self, payload, status_code=200):
        self.payload = payload
        self.status_code = status_code

    def raise_for_status(self):
        if self.status_code >= 400:
            raise requests.HTTPError(f"HTTP {self.status_code}")

    def json(self):
        return self.payload


def test_google_translate_provider_uses_pt_br(monkeypatch):
    def fake_get(url, params, timeout):
        assert params["client"] == "gtx"
        assert params["sl"] == "en"
        assert params["tl"] == "pt-BR"
        return FakeResponse([[["OLA", "HELLO"], [" MUNDO", " WORLD"]]])

    monkeypatch.setattr(requests, "get", fake_get)

    client = LibreTranslateClient(
        BridgeConfig(translation_providers=("google",), request_timeout_seconds=1)
    )

    assert client.translate("HELLO WORLD", "en", "pt-BR") == "OLA MUNDO"
    assert client.last_provider == "google"
    assert client.last_warnings == []


def test_google_falls_back_to_deepl_with_pt_br(monkeypatch):
    def fake_get(url, params, timeout):
        raise requests.ConnectionError("blocked")

    def fake_post(url, data=None, json=None, headers=None, timeout=None):
        assert headers == {"Authorization": "DeepL-Auth-Key test-key"}
        assert data["target_lang"] == "PT-BR"
        return FakeResponse({"translations": [{"text": "OLA MUNDO"}]})

    monkeypatch.setattr(requests, "get", fake_get)
    monkeypatch.setattr(requests, "post", fake_post)

    client = LibreTranslateClient(
        BridgeConfig(
            translation_providers=("google", "deepl"),
            deepl_auth_key="test-key",
            request_timeout_seconds=1,
        )
    )

    assert client.translate("HELLO WORLD", "en", "pt-BR") == "OLA MUNDO"
    assert client.last_provider == "deepl"
    assert len(client.last_warnings) == 1


def test_deepl_is_used_first_with_key(monkeypatch):
    def fail_get(*args, **kwargs):
        raise AssertionError("Google should not be called when DeepL succeeds")

    def fake_post(url, data=None, json=None, headers=None, timeout=None):
        assert headers == {"Authorization": "DeepL-Auth-Key test-key"}
        assert data["source_lang"] == "EN"
        assert data["target_lang"] == "PT-BR"
        return FakeResponse({"translations": [{"text": "OLA MUNDO"}]})

    monkeypatch.setattr(requests, "get", fail_get)
    monkeypatch.setattr(requests, "post", fake_post)

    client = LibreTranslateClient(
        BridgeConfig(
            deepl_auth_key="test-key",
            request_timeout_seconds=1,
        )
    )

    assert client.translate("HELLO WORLD", "en", "pt-BR") == "OLA MUNDO"
    assert client.last_provider == "deepl"
    assert client.last_warnings == []


def test_pt_alias_is_normalized_to_brazilian_portuguese(monkeypatch):
    def fake_get(url, params, timeout):
        assert params["tl"] == "pt-BR"
        return FakeResponse([[["OLA MUNDO", "HELLO WORLD"]]])

    monkeypatch.setattr(requests, "get", fake_get)

    client = LibreTranslateClient(
        BridgeConfig(translation_providers=("google",), request_timeout_seconds=1)
    )

    assert client.translate("HELLO WORLD", "en", "pt") == "OLA MUNDO"


def test_health_does_not_probe_disabled_libretranslate(monkeypatch):
    def fail_get(*args, **kwargs):
        raise AssertionError("LibreTranslate should not be probed")

    monkeypatch.setattr(requests, "get", fail_get)

    client = LibreTranslateClient(
        BridgeConfig(translation_providers=("deepl", "google"))
    )

    health = client.health()

    assert health["ok"] is True
    assert health["order"] == ["deepl", "google"]
    assert health["libretranslate"]["disabled"] is True
