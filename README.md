# G.R.C TRANSLATOR

Aplicativo desktop para traduzir legendas e textos exibidos na tela usando OCR. O usuário define uma área uma única vez, e o aplicativo monitora essa região, reconhece apenas conteúdos novos e exibe a tradução sobre o jogo ou programa.

O projeto também preserva uma extensão para Chrome/Edge e um cliente desktop Python como alternativas, mas o cliente principal é o aplicativo Electron.

## Funcionalidades

- área automática de tradução: selecione a região das legendas uma vez;
- OCR local com Tesseract, PaddleOCR ou EasyOCR;
- escolha do mecanismo OCR diretamente na interface;
- atalhos globais personalizados de teclado ou mouse;
- legenda sobreposta, reposicionável e com aparência configurável;
- interface desktop em tons de roxo e animação de abertura;
- cache de imagens, textos reconhecidos e traduções;
- cancelamento de requisições antigas e descarte de resultados atrasados;
- logs de desempenho para captura, OCR, tradução e tempo total;
- suporte a múltiplos monitores e jogos em janela sem bordas.

## Como funciona

```text
Área da tela
    -> captura e recorte no Electron
    -> comparação com a imagem anterior
    -> OCR local no bridge Python
    -> limpeza do texto
    -> tradução via DeepL ou Google Translate
    -> legenda sobreposta no Electron
```

O OCR é executado localmente. A tradução usa internet: o bridge tenta DeepL quando uma chave está configurada e usa Google Translate como fallback. O endpoint utilizado do Google não é uma API oficial garantida.

## Requisitos

- Windows 10 ou Windows 11;
- Python 3.10 ou superior;
- Node.js LTS e npm;
- Tesseract OCR para o modo padrão;
- conexão com a internet para instalar dependências, baixar modelos opcionais e traduzir.

## Instalação rápida

Abra o PowerShell e clone o repositório:

```powershell
cd "$env:USERPROFILE\Documents"
git clone https://github.com/R4P4DHGFVDYG/G-R-C-TRANSLATOR-.git
cd G-R-C-TRANSLATOR-
```

### 1. Bridge Python e Tesseract

```powershell
python -m venv .\bridge\.venv
.\bridge\.venv\Scripts\python.exe -m pip install --upgrade pip
.\bridge\.venv\Scripts\python.exe -m pip install -r .\bridge\requirements.txt -r .\bridge\requirements-tesseract.txt
winget install --id UB-Mannheim.TesseractOCR --exact
```

O bridge procura o Tesseract no `PATH` e também em `C:\Program Files\Tesseract-OCR\tesseract.exe`.

### 2. Aplicativo Electron

```powershell
cd .\electron_client
npm ci
cd ..
```

## Executar

Abra um PowerShell na raiz do projeto e inicie o bridge:

```powershell
cd .\bridge
.\.venv\Scripts\python.exe -m hq_ocr_bridge
```

Mantenha essa janela aberta. Em outro PowerShell, inicie o Electron:

```powershell
cd .\electron_client
npm start
```

O bridge fica disponível apenas no computador local em `http://127.0.0.1:8765`. O endpoint `http://127.0.0.1:8765/ready` indica quando o OCR terminou de aquecer.

## Uso

1. Escolha o mecanismo OCR na interface.
2. Clique em **Definir área automática**.
3. Arraste sobre a região onde as legendas aparecem.
4. Volte ao jogo ou programa.
5. O aplicativo traduz automaticamente quando o conteúdo da região muda.
6. Use **Parar tradução automática** para encerrar o monitoramento.

O atalho padrão é `Ctrl + Shift + Q`. Em **Atalho de captura**, clique em **Alterar** e pressione:

- uma combinação de teclado;
- uma tecla entre `F1` e `F24`;
- o botão do meio do mouse;
- um dos dois botões laterais do mouse.

Cliques esquerdo e direito não podem ser usados como atalho, pois isso bloquearia a operação normal do Windows. Botões adicionais de mouses gamer normalmente precisam ser mapeados para uma tecla no software do fabricante.

## Mecanismos OCR opcionais

Tesseract é o padrão e inicia mais rápido. Para instalar EasyOCR:

```powershell
.\bridge\.venv\Scripts\python.exe -m pip install -r .\bridge\requirements-ocr.txt
```

Para instalar PaddleOCR:

```powershell
.\bridge\.venv\Scripts\python.exe -m pip install -r .\bridge\requirements-paddleocr.txt
```

O primeiro uso de PaddleOCR ou EasyOCR pode demorar enquanto os modelos são carregados ou baixados.

## Provedores de tradução

Sem configuração adicional, o Google Translate é usado como fallback. Para usar a API gratuita do DeepL primeiro:

```powershell
cd .\bridge
$env:HQ_OCR_DEEPL_AUTH_KEY = "SUA_CHAVE_DEEPL"
.\.venv\Scripts\python.exe -m hq_ocr_bridge
```

Nunca salve a chave diretamente no código ou faça commit de arquivos `.env`.

## Jogos em tela cheia

O seletor e a legenda usam uma janela de sobreposição no nível mais alto. O modo recomendado é **janela sem bordas** ou **borderless fullscreen**.

Tela cheia exclusiva e alguns sistemas anti-cheat podem bloquear a captura ou qualquer sobreposição externa. Nesses casos, altere o modo de exibição dentro do jogo. O projeto não injeta código no processo do jogo.

## Extensão para navegador

1. Inicie o bridge Python.
2. Abra `chrome://extensions` ou `edge://extensions`.
3. Ative o modo de desenvolvedor.
4. Clique em **Carregar sem compactação**.
5. Selecione a pasta `extension` deste repositório.

O atalho da extensão pode ser alterado em `chrome://extensions/shortcuts` ou `edge://extensions/shortcuts`.

## Testes

Bridge Python:

```powershell
cd .\bridge
.\.venv\Scripts\python.exe -m pip install -r requirements-dev.txt
.\.venv\Scripts\python.exe -m pytest
```

Electron:

```powershell
cd .\electron_client
npm test
```

Extensão:

```powershell
cd .\extension
npm test
```

## Desempenho e privacidade

O Electron e o bridge registram linhas `[performance]` contendo apenas métricas de tempo e estado dos caches. Em condições normais, imagens e textos reconhecidos não são gravados em disco.

Capturas de diagnóstico podem conter informações sensíveis. Ative `HQ_OCR_SAVE_DEBUG_CAPTURES` somente durante investigação e não publique a pasta `debug-captures`.

Principais otimizações do fluxo:

- captura restrita à área selecionada;
- detecção de imagem e texto repetidos;
- caches LRU com expiração;
- uma única captura/OCR automática por vez;
- cancelamento lógico de trabalho obsoleto;
- prioridade para a legenda mais recente;
- reutilização da janela de tradução e das conexões HTTP.

## Estrutura do repositório

```text
bridge/           servidor local, OCR, tradução e testes Python
electron_client/  aplicativo desktop Electron
extension/        extensão alternativa para Chrome e Edge
desktop_client/   cliente desktop Python legado
docs/             documentação técnica de desenvolvimento
```

## Limitações atuais

- a tradução não funciona offline;
- o endpoint público do Google pode mudar ou aplicar limites;
- não existe instalador pronto versionado no repositório;
- o resultado depende da legibilidade, idioma, fonte e contraste da imagem;
- ainda não há um arquivo `LICENSE` na raiz do projeto.

## Contribuição

Antes de enviar uma alteração, mantenha cada commit focado, não inclua modelos OCR, ambientes virtuais, capturas ou credenciais e execute os testes relacionados.
