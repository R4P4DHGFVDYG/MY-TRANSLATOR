from __future__ import annotations

import base64
import io
import itertools
import os
from time import perf_counter
from uuid import uuid4

import requests

BRIDGE_URL = os.getenv("HQ_OCR_BRIDGE_URL", "http://127.0.0.1:8765").rstrip("/")
REQUEST_TIMEOUT = (3.05, 45)
CLIENT_ID = uuid4().hex
_REQUEST_IDS = itertools.count(1)
_SESSION = requests.Session()


def image_to_data_url(image):
    buffered = io.BytesIO()
    image.save(buffered, format="PNG")
    img_str = base64.b64encode(buffered.getvalue()).decode("utf-8")
    return f"data:image/png;base64,{img_str}"

def _error_from_payload(payload, fallback):
    if isinstance(payload, dict):
        message = payload.get("error")
        if isinstance(message, str) and message.strip():
            return message.strip()
    return fallback


def translate_image(
    image,
    source_lang="en",
    target_lang="pt-BR",
    request_id=None,
):
    width, height = image.size
    current_request_id = request_id if request_id is not None else next(_REQUEST_IDS)
    payload = {
        "imageDataUrl": image_to_data_url(image),
        "selection": {
            "x": 0,
            "y": 0,
            "width": width,
            "height": height
        },
        "viewport": {
            "width": width,
            "height": height
        },
        "source": source_lang,
        "target": target_lang,
        "engines": ["tesseract"],
        "clientId": CLIENT_ID,
        "requestId": current_request_id,
    }

    started_at = perf_counter()
    try:
        response = _SESSION.post(
            f"{BRIDGE_URL}/v1/translate-selection",
            json=payload,
            timeout=REQUEST_TIMEOUT,
        )
    except requests.Timeout:
        return "A tradução demorou demais. Tente novamente."
    except requests.RequestException:
        return "Não foi possível conectar ao servidor local. Verifique se o bridge está em execução."

    elapsed_ms = (perf_counter() - started_at) * 1000

    try:
        data = response.json()
    except ValueError:
        return f"O servidor local retornou uma resposta inválida (HTTP {response.status_code})."

    if not response.ok:
        message = _error_from_payload(data, f"O bridge retornou HTTP {response.status_code}.")
        return f"Erro ao traduzir: {message}"
    if not isinstance(data, dict):
        return "O servidor local retornou uma resposta inválida."

    print(
        "[performance] "
        f"requestId={current_request_id} clientTotalMs={elapsed_ms:.2f} "
        f"server={data.get('performance')}",
        flush=True,
    )

    translated_text = data.get("translatedText")
    source_text = data.get("sourceText")
    if not isinstance(translated_text, str) or not isinstance(source_text, str):
        return "O servidor local não retornou o texto esperado."
    if translated_text.strip():
        return translated_text.strip()
    if source_text.strip():
        return "O OCR encontrou texto, mas o bridge não retornou uma tradução."
    return "Nenhum texto detectado."
