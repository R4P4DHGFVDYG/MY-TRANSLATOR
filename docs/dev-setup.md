# Dev setup

Raiz oficial do projeto:

```powershell
cd "C:\Users\GADEIM\Documents\Tradutor OCR extensao\hq-ocr-translator"
```

## Bridge

Criar ambiente Python:

```powershell
cd .\bridge
python -m venv .venv
.\.venv\Scripts\Activate.ps1
pip install -r requirements.txt -r requirements-dev.txt
```

Instalar OCR real, quando for testar o pipeline completo:

```powershell
pip install -r requirements-ocr.txt -r requirements-paddleocr.txt
```

O Tesseract tambem precisa estar instalado no Windows e disponivel no `PATH`; `pytesseract` e apenas o wrapper Python.

Rodar testes:

```powershell
cd "C:\Users\GADEIM\Documents\Tradutor OCR extensao\hq-ocr-translator\bridge"
.\.venv\Scripts\python.exe -m pytest
```

Subir o bridge:

```powershell
cd "C:\Users\GADEIM\Documents\Tradutor OCR extensao\hq-ocr-translator\bridge"
.\.venv\Scripts\python.exe -m hq_ocr_bridge
```

Health:

```powershell
Invoke-RestMethod -Uri http://127.0.0.1:8765/health
```

Salvar recortes de diagnostico em todas as chamadas:

```powershell
$env:HQ_OCR_SAVE_DEBUG_CAPTURES = "true"
$env:HQ_OCR_DEBUG_CAPTURE_DIR = "debug-captures"
.\.venv\Scripts\python.exe -m hq_ocr_bridge
```

Para permitir que a opcao "Salvar recortes OCR" da extensao ative capturas por chamada,
habilite-a explicitamente no bridge:

```powershell
$env:HQ_OCR_ALLOW_REQUEST_DEBUG_CAPTURES = "true"
```

Mantenha essa opcao desligada em uso normal: os recortes podem conter texto sensivel.

O perfil rapido agora e o padrao: PaddleOCR mobile, uma variante, cache de OCR e aquecimento em segundo plano. Para sobrescrever explicitamente os valores:

```powershell
$env:HQ_OCR_FORCE_ENGINES = "true"
$env:HQ_OCR_DEFAULT_ENGINES = "paddleocr"
$env:HQ_OCR_PADDLEOCR_DETECTION_MODEL = "PP-OCRv5_mobile_det"
$env:HQ_OCR_PADDLEOCR_RECOGNITION_MODEL = "en_PP-OCRv5_mobile_rec"
$env:HQ_OCR_PADDLEOCR_MAX_PIXELS = "500000"
$env:HQ_OCR_MAX_VARIANTS = "1"
$env:HQ_OCR_ENGINE_TIMEOUT_SECONDS = "8"
$env:HQ_OCR_WARMUP_ON_START = "true"
.\.venv\Scripts\python.exe -m hq_ocr_bridge
```

MKL-DNN permanece desligado por padrao porque apresentou falha neste ambiente. Ative `HQ_OCR_PADDLEOCR_ENABLE_MKLDNN=true` somente depois de validar a CPU local.

Para comparar qualidade contra velocidade, troque `HQ_OCR_DEFAULT_ENGINES` para `paddleocr,easyocr`, aumente `HQ_OCR_MAX_VARIANTS` e adicione:

```powershell
$env:HQ_OCR_PARALLEL_ENGINES = "true"
```

Prontidao e metricas:

```powershell
Invoke-RestMethod -Uri http://127.0.0.1:8765/ready
```

O bridge registra uma linha `[performance]` por requisicao sem incluir imagem nem texto. A resposta do endpoint de traducao inclui tempos por etapa e informa se os caches de OCR/traducao foram usados. Os controles principais sao `HQ_OCR_CACHE_CAPACITY`, `HQ_OCR_CACHE_TTL_SECONDS`, `HQ_OCR_TRANSLATION_CACHE_CAPACITY`, `HQ_OCR_TRANSLATION_CACHE_TTL_SECONDS` e `HQ_OCR_LOG_PERFORMANCE`.

## Traducao

Por padrao, o bridge tenta os provedores configurados em
`HQ_OCR_TRANSLATION_PROVIDERS` (atualmente `deepl,google`). O endpoint `/health`
informa o provedor efetivamente disponivel.

Para usar exclusivamente um LibreTranslate local, configure antes de iniciar o bridge:

```powershell
$env:HQ_OCR_TRANSLATION_PROVIDERS = "libretranslate"
$env:HQ_OCR_LIBRETRANSLATE_URL = "http://127.0.0.1:5000"
```

O endpoint `/health` tambem mostra os OCRs disponiveis.

## Extensao

1. Abra `chrome://extensions` ou `edge://extensions`.
2. Ative o modo desenvolvedor.
3. Use "Load unpacked" / "Carregar sem compactacao".
4. Selecione:

```text
C:\Users\GADEIM\Documents\Tradutor OCR extensao\hq-ocr-translator\extension
```

## Checks rapidos

```powershell
cd "C:\Users\GADEIM\Documents\Tradutor OCR extensao\hq-ocr-translator"
node --check .\extension\background.js
node --check .\extension\contentScript.js
node --check .\extension\popup.js
node --check .\extension\options.js
node --check .\extension\shared.js
npm --prefix .\extension test
```

Esses checks validam sintaxe, nao substituem teste manual no navegador.
