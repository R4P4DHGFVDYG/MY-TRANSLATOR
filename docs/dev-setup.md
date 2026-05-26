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
pip install -r requirements-ocr.txt
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

## LibreTranslate

O bridge espera LibreTranslate em:

```text
http://127.0.0.1:5000
```

O endpoint `/health` do bridge mostra se o LibreTranslate esta acessivel e quais OCRs estao disponiveis.

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
```

Esses checks validam sintaxe, nao substituem teste manual no navegador.
