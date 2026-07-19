# Compilar o instalador no Windows

O instalador é gerado em formato NSIS para Windows x64. Ele inclui o Electron, o serviço OCR local congelado, os modelos do PaddleOCR e EasyOCR e uma cópia portátil do Tesseract.

## Requisitos de desenvolvimento

- Windows 10 ou 11 x64;
- Python 3.10 ou mais recente;
- Node.js 22 LTS ou mais recente;
- Tesseract instalado em `C:\Program Files\Tesseract-OCR`;
- modelos locais usados pelo aplicativo.

Prepare as dependências na raiz do repositório:

```powershell
python -m venv .\bridge\.venv
.\bridge\.venv\Scripts\python.exe -m pip install --upgrade pip
.\bridge\.venv\Scripts\python.exe -m pip install -r .\bridge\requirements-build.txt

cd .\electron_client
npm ci
cd ..
```

Antes da primeira compilação, execute o aplicativo pelo menos uma vez com PaddleOCR em inglês e português e com EasyOCR. Isso cria os modelos esperados em `bridge\.paddlex-cache` e `%USERPROFILE%\.EasyOCR\model`.

## Gerar o Setup.exe

```powershell
cd .\electron_client
npm run dist:win
```

O processo roda os testes, empacota o bridge e cria:

```text
release\GRC-Translator-Setup-1.0.0.exe
```

Para repetir somente o empacotamento durante o desenvolvimento, sem rodar os testes novamente:

```powershell
npm run dist:win:quick
```

O script aceita caminhos alternativos por meio destas variáveis de ambiente:

- `HQ_OCR_BUILD_PADDLE_CACHE_DIR`;
- `HQ_OCR_BUILD_EASYOCR_MODEL_DIR`;
- `HQ_OCR_BUILD_TESSERACT_DIR`.

Os diretórios `build` e `release` são artefatos locais ignorados pelo Git. A assinatura digital não é aplicada automaticamente; uma versão pública deve ser assinada antes da distribuição para evitar avisos de origem desconhecida do Windows.
