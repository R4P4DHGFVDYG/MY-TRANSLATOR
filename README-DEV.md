# G.R.C Translator — documentação de desenvolvimento

Este documento reúne informações internas de arquitetura, configuração, diagnóstico e manutenção. O guia simples para usuários permanece no [README principal](README.md).

## Arquitetura

```text
Região selecionada
    -> Electron captura e recorta o monitor
    -> hash evita processar a mesma imagem
    -> bridge Flask decodifica o PNG
    -> OCR local reconhece o texto
    -> normalização prepara a frase
    -> provedor externo traduz
    -> Electron descarta respostas antigas
    -> toast exibe a tradução mais recente
```

### Componentes

```text
bridge/           API local, OCR, tradução, caches e testes Python
electron_client/  processo principal, interface, seleção e overlay Electron
desktop_client/   cliente desktop Python legado
docs/             documentação complementar
```

O bridge escuta apenas em `127.0.0.1:8765`. O Electron envia a imagem já recortada para `POST /v1/translate-selection`.

## Ambiente de desenvolvimento

Na raiz do repositório:

```powershell
python -m venv .\bridge\.venv
.\bridge\.venv\Scripts\python.exe -m pip install --upgrade pip
.\bridge\.venv\Scripts\python.exe -m pip install -r .\bridge\requirements.txt -r .\bridge\requirements-dev.txt -r .\bridge\requirements-tesseract.txt
winget install --id UB-Mannheim.TesseractOCR --exact

cd .\electron_client
npm ci
cd ..
```

O `pytesseract` é apenas o wrapper Python. O executável também precisa estar no `PATH` ou em `C:\Program Files\Tesseract-OCR\tesseract.exe`.

### OCRs opcionais

EasyOCR:

```powershell
.\bridge\.venv\Scripts\python.exe -m pip install -r .\bridge\requirements-ocr.txt
```

PaddleOCR:

```powershell
.\bridge\.venv\Scripts\python.exe -m pip install -r .\bridge\requirements-paddleocr.txt
```

Os modelos de PaddleOCR e EasyOCR não devem ser versionados. O primeiro carregamento pode baixar modelos e aquecer o mecanismo.

## Inicialização manual

Bridge:

```powershell
cd .\bridge
.\.venv\Scripts\python.exe -m hq_ocr_bridge
```

Electron, em outro terminal:

```powershell
cd .\electron_client
npm start
```

Endpoints úteis:

```powershell
Invoke-RestMethod http://127.0.0.1:8765/health
Invoke-RestMethod http://127.0.0.1:8765/ready
```

`/health` informa os OCRs e provedores disponíveis. `/ready` retorna HTTP 200 depois do aquecimento configurado.

## Tradução

O bridge usa os provedores definidos em `HQ_OCR_TRANSLATION_PROVIDERS`. A ordem padrão é:

```text
deepl,google
```

Sem `HQ_OCR_DEEPL_AUTH_KEY`, DeepL é ignorado por falta de credencial e o Google é usado como fallback. O endpoint público do Google não é oficial e pode mudar ou aplicar limites.

DeepL:

```powershell
$env:HQ_OCR_DEEPL_AUTH_KEY = "SUA_CHAVE"
```

LibreTranslate local:

```powershell
$env:HQ_OCR_TRANSLATION_PROVIDERS = "libretranslate"
$env:HQ_OCR_LIBRETRANSLATE_URL = "http://127.0.0.1:5000"
```

Credenciais devem permanecer em variáveis de ambiente ou arquivos locais ignorados pelo Git.

## Fluxo de baixa latência

- O Electron captura somente a região escolhida.
- Um SHA-256 evita OCR quando o PNG não mudou.
- O texto reconhecido também é comparado com o resultado anterior.
- A captura automática é serial; não há vários OCRs simultâneos para a mesma área.
- Uma requisição de tradução nova invalida a anterior.
- Respostas atrasadas são descartadas pelo `clientId` e `requestId`.
- O Electron mantém cache de resultados por imagem.
- O bridge mantém caches TTL para OCR e tradução.
- Requisições idênticas em andamento compartilham o mesmo trabalho de tradução.

Valores padrão importantes:

- captura da área fixa a cada 650 ms;
- cache Electron: 64 resultados por 10 minutos;
- cache OCR: 128 resultados por 10 minutos;
- cache de tradução: 128 resultados por 15 minutos;
- uma requisição OCR concorrente por padrão;
- timeout da chamada Electron ao bridge: 45 segundos.

## Logs de desempenho

Electron e bridge escrevem eventos `[performance]`. As métricas incluem:

- captura do monitor;
- recorte e codificação PNG;
- decodificação no bridge;
- OCR;
- tradução;
- tempo total;
- acertos dos caches.

O JSON retornado pelo endpoint inclui `performance.timings` e indicadores de cache. Logs normais não devem incluir a imagem nem o texto reconhecido.

Variáveis relacionadas:

```text
HQ_OCR_LOG_PERFORMANCE
HQ_OCR_CACHE_CAPACITY
HQ_OCR_CACHE_TTL_SECONDS
HQ_OCR_TRANSLATION_CACHE_CAPACITY
HQ_OCR_TRANSLATION_CACHE_TTL_SECONDS
```

## Privacidade e capturas de diagnóstico

Em uso normal, recortes e textos não são persistidos em disco. Para salvar imagens durante uma investigação:

```powershell
$env:HQ_OCR_SAVE_DEBUG_CAPTURES = "true"
$env:HQ_OCR_DEBUG_CAPTURE_DIR = "debug-captures"
```

Essas imagens podem conter diálogos, nomes ou outras informações visíveis na tela. A pasta `debug-captures` é ignorada pelo Git e deve ser removida depois do diagnóstico.

## Configuração avançada do OCR

Exemplo de perfil Tesseract:

```powershell
$env:HQ_OCR_FORCE_ENGINES = "true"
$env:HQ_OCR_DEFAULT_ENGINES = "tesseract"
$env:HQ_OCR_MAX_VARIANTS = "1"
$env:HQ_OCR_ENGINE_TIMEOUT_SECONDS = "8"
$env:HQ_OCR_WARMUP_ON_START = "true"
```

Para comparar mecanismos em paralelo:

```powershell
$env:HQ_OCR_DEFAULT_ENGINES = "tesseract,paddleocr"
$env:HQ_OCR_PARALLEL_ENGINES = "true"
```

O uso normal do Electron envia somente o OCR selecionado na interface.

## Atalhos globais

Atalhos de teclado usam `globalShortcut` do Electron. O gravador aceita combinações com modificadores ou teclas `F1` a `F24`.

No Windows, os botões do mouse são observados por `electron_client/mouse_hook.ps1`. São suportados botão do meio, lateral 1 e lateral 2. Cliques esquerdo e direito são rejeitados para não bloquear a interação normal do sistema.

## Overlay e jogos

As janelas de seleção e legenda usam `alwaysOnTop` no nível `screen-saver` e são movidas novamente para o topo ao aparecer.

Isso melhora a compatibilidade com janela sem bordas. Tela cheia exclusiva, conteúdo protegido e alguns anti-cheats podem impedir captura ou sobreposição. O projeto não injeta DLL e não cria hooks dentro do processo do jogo.

## Testes

Bridge:

```powershell
cd .\bridge
.\.venv\Scripts\python.exe -m pytest
```

Electron:

```powershell
cd .\electron_client
npm test
```

Antes de um commit, também execute:

```powershell
node --check .\electron_client\main.js
node --check .\electron_client\preload.js
```

## Limitações e trabalho futuro

- criar instalador e fluxo de atualização;
- permitir tradução totalmente offline;
- melhorar a captura de jogos em tela cheia exclusiva quando o Windows permitir;
- criar métricas comparativas por jogo e mecanismo OCR;
- ampliar idiomas de origem e destino;
- adicionar um arquivo `LICENSE` antes de distribuição pública ampla.

## Regras de manutenção

- commits pequenos e focados;
- não versionar `.env`, chaves, ambientes virtuais, modelos ou capturas;
- adicionar teste para comportamento novo;
- preservar cancelamento e prioridade da requisição mais recente.
