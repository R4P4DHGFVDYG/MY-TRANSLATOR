# HQ OCR Translator

Extensao Chrome/Edge Manifest V3 para selecionar uma area visivel de uma HQ online, enviar a captura para um bridge local, rodar OCR e traduzir o texto reconhecido.

Este projeto usa o Translumo como referencia de pipeline, nao como base direta. O fluxo do MVP e:

1. A extensao injeta uma camada de selecao na aba ativa.
2. O usuario arrasta uma area da pagina visivel.
3. O service worker captura a aba com `chrome.tabs.captureVisibleTab`.
4. O bridge local recorta a imagem, roda OCR, escolhe o melhor texto e chama o tradutor configurado.
5. A extensao mostra um overlay simples perto da selecao.

## Estrutura

- `extension/`: extensao Chrome/Edge MV3.
- `bridge/`: API Flask local em `127.0.0.1:8765`.

## Requisitos

- Python 3.10+.
- Tradutor via bridge. Por padrao tenta DeepL primeiro e cai para Google Translate nao oficial.
- Para OCR real: PaddleOCR ou EasyOCR com modelos disponiveis.

## Rodar o bridge

```powershell
cd .\hq-ocr-translator\bridge
python -m venv .venv
.\.venv\Scripts\Activate.ps1
pip install -r requirements.txt -r requirements-ocr.txt
python -m hq_ocr_bridge
```

PaddleOCR e o OCR principal recomendado para HQs neste projeto. Para instalar a stack dele:

```powershell
pip install -r requirements-paddleocr.txt
```

Variaveis uteis:

- `HQ_OCR_BRIDGE_HOST`: padrao `127.0.0.1`.
- `HQ_OCR_BRIDGE_PORT`: padrao `8765`.
- `HQ_OCR_LIBRETRANSLATE_URL`: padrao `http://127.0.0.1:5000`.
- `HQ_OCR_TRANSLATION_PROVIDERS`: ordem de tradutores, padrao `deepl,google`. Use `deepl,google,libretranslate` para reativar LibreTranslate como fallback.
- `HQ_OCR_DEEPL_AUTH_KEY`: chave DeepL usada quando `deepl` estiver na ordem.
- `HQ_OCR_DEEPL_API_URL`: endpoint DeepL, padrao `https://api-free.deepl.com/v2/translate`.
- `HQ_OCR_GOOGLE_TRANSLATE_URL`: endpoint Google nao oficial, padrao `https://translate.googleapis.com/translate_a/single`.
- `HQ_OCR_EASYOCR_MODEL_DIR`: diretorio local de modelos EasyOCR.
- `HQ_OCR_ALLOW_EASYOCR_DOWNLOAD`: `true` para permitir download automatico de modelos.
- `HQ_OCR_PADDLEOCR_MAX_PIXELS`: limite de pixels processados pelo PaddleOCR, padrao `700000`.
- `HQ_OCR_PADDLEOCR_ENABLE_MKLDNN`: `true` para reativar MKL-DNN/oneDNN. Padrao `false` porque falhou neste Windows.
- `HQ_OCR_SAVE_DEBUG_CAPTURES`: `true` para salvar recortes OCR de todas as requisicoes.
- `HQ_OCR_DEBUG_CAPTURE_DIR`: pasta dos recortes, padrao `debug-captures`.

Depois de instalar PaddleOCR, reinicie o bridge. Selecione apenas o balao/texto; screenshots ou paineis grandes podem ficar lentos mesmo com o limite de seguranca.

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
  "target": "pt-BR",
  "engines": ["paddleocr", "easyocr"],
  "debug": false
}
```

Quando `debug` estiver `true`, o bridge salva `crop.png`, `ocr-preprocessed.png`, `request.json` e `response.json` para comparar o balao real com o texto reconhecido.

## Testes

```powershell
cd .\hq-ocr-translator\bridge
pip install -r requirements.txt -r requirements-dev.txt
pytest
```

Os testes principais usam OCR e tradutor falsos. O smoke test de OCR real deve ser feito manualmente depois que Tesseract/EasyOCR estiverem instalados.

Setup detalhado para desenvolvimento: `docs/dev-setup.md`.
