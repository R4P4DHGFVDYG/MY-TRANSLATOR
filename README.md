# HQ OCR Translator

Extensao Chrome/Edge Manifest V3 para selecionar uma area visivel de uma HQ online, enviar a captura para um bridge local, rodar OCR e traduzir com LibreTranslate.

Este projeto usa o Translumo como referencia de pipeline, nao como base direta. O fluxo do MVP e:

1. A extensao injeta uma camada de selecao na aba ativa.
2. O usuario arrasta uma area da pagina visivel.
3. O service worker captura a aba com `chrome.tabs.captureVisibleTab`.
4. O bridge local recorta a imagem, roda EasyOCR e Tesseract, escolhe o melhor texto e chama LibreTranslate.
5. A extensao mostra um overlay simples perto da selecao.

## Estrutura

- `extension/`: extensao Chrome/Edge MV3.
- `bridge/`: API Flask local em `127.0.0.1:8765`.

## Requisitos

- Python 3.10+.
- LibreTranslate rodando localmente em `http://127.0.0.1:5000`.
- Para OCR real: Tesseract OCR instalado com idioma ingles (`eng`) e/ou EasyOCR com modelos disponiveis.

## Rodar o bridge

```powershell
cd .\hq-ocr-translator\bridge
python -m venv .venv
.\.venv\Scripts\Activate.ps1
pip install -r requirements.txt -r requirements-ocr.txt
python -m hq_ocr_bridge
```

Variaveis uteis:

- `HQ_OCR_BRIDGE_HOST`: padrao `127.0.0.1`.
- `HQ_OCR_BRIDGE_PORT`: padrao `8765`.
- `HQ_OCR_LIBRETRANSLATE_URL`: padrao `http://127.0.0.1:5000`.
- `HQ_OCR_EASYOCR_MODEL_DIR`: diretorio local de modelos EasyOCR.
- `HQ_OCR_ALLOW_EASYOCR_DOWNLOAD`: `true` para permitir download automatico de modelos.

## Carregar a extensao

1. Abra `chrome://extensions` ou `edge://extensions`.
2. Ative o modo desenvolvedor.
3. Use "Load unpacked" / "Carregar sem compactacao".
4. Selecione `hq-ocr-translator/extension`.

## API local

```http
GET /health
POST /v1/translate-selection
```

Exemplo:

```json
{
  "imageDataUrl": "data:image/png;base64,...",
  "selection": { "x": 10, "y": 20, "width": 300, "height": 120 },
  "viewport": { "width": 1365, "height": 768 },
  "source": "en",
  "target": "pt",
  "engines": ["easyocr", "tesseract"]
}
```

## Testes

```powershell
cd .\hq-ocr-translator\bridge
pip install -r requirements.txt -r requirements-dev.txt
pytest
```

Os testes principais usam OCR e tradutor falsos. O smoke test de OCR real deve ser feito manualmente depois que Tesseract/EasyOCR estiverem instalados.

Setup detalhado para desenvolvimento: `docs/dev-setup.md`.
