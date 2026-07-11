# G.R.C TRANSLATOR

O G.R.C TRANSLATOR e um tradutor OCR para desktop, com a extensao de Chrome/Edge preservada como cliente alternativo.

Voce seleciona um balao, legenda ou texto na pagina. A extensao le o texto da imagem e mostra a traducao em portugues.

Importante: a extensao precisa de um programinha local em Python rodando no seu PC. Sem ele, ela nao consegue fazer OCR.

## O Que Voce Precisa

- Windows 10 ou 11.
- Python 3.10 ou mais novo.
- Chrome ou Edge.
- Node.js LTS, apenas se for usar o aplicativo desktop Electron.
- Internet na primeira instalacao.

Baixe Python aqui:

```text
https://www.python.org/downloads/
```

Na instalacao do Python, marque:

```text
Add Python to PATH
```

## Baixar O Projeto

Escolha um dos jeitos.

### Jeito Facil

1. Clique no botao verde `Code` aqui no GitHub.
2. Clique em `Download ZIP`.
3. Extraia o ZIP em `Documentos`.
4. Renomeie a pasta extraida para:

```text
I-LOVE-WEBCOMICS
```

### Jeito Com Git

No PowerShell:

```powershell
cd "$env:USERPROFILE\Documents"
git clone https://github.com/R4P4DHGFVDYG/I-LOVE-WEBCOMICS-.git I-LOVE-WEBCOMICS
```

## Instalar

No PowerShell:

```powershell
cd "$env:USERPROFILE\Documents\I-LOVE-WEBCOMICS\bridge"

python -m venv .venv
.\.venv\Scripts\python.exe -m pip install --upgrade pip
.\.venv\Scripts\python.exe -m pip install -r requirements.txt -r requirements-tesseract.txt
winget install --id UB-Mannheim.TesseractOCR --exact
```

Essa parte demora. E normal.

### Aplicativo Desktop (Recomendado)

Para usar o atalho `Ctrl+Shift+Q` fora do navegador, instale tambem as dependencias do Electron:

```powershell
cd "$env:USERPROFILE\Documents\I-LOVE-WEBCOMICS\electron_client"
npm ci
```

O aplicativo desktop incluido vem configurado para OCR em ingles. Nas configuracoes, e possivel alternar entre Tesseract, PaddleOCR e EasyOCR; a escolha fica salva para a proxima inicializacao. O bridge localiza automaticamente a instalacao padrao do Tesseract em `C:\Program Files\Tesseract-OCR`.

## Iniciar

Sempre que for usar, deixe este PowerShell aberto:

```powershell
cd "$env:USERPROFILE\Documents\I-LOVE-WEBCOMICS\bridge"
.\.venv\Scripts\python.exe -m hq_ocr_bridge
```

Se estiver tudo certo, aparece um servidor em:

```text
http://127.0.0.1:8765
```

Nao feche essa janela enquanto estiver usando a extensao.

### Aplicativo Desktop

Depois de iniciar o bridge, em outro PowerShell rode:

```powershell
cd "$env:USERPROFILE\Documents\I-LOVE-WEBCOMICS\electron_client"
npm start
```

Use `Ctrl+Shift+Q`, um dos botoes laterais configurados ou `Definir area automatica` para selecionar a regiao das legendas. O aplicativo verifica essa area continuamente, ignora imagens e textos repetidos e traduz apenas quando o conteudo muda. Use o mesmo atalho para redefinir a regiao ou clique em `Parar traducao automatica` para encerrar o monitoramento.

As janelas de selecao e traducao usam uma sobreposicao de tela cheia para permanecer visiveis em jogos no modo janela sem bordas (borderless fullscreen). Tela cheia exclusiva e alguns sistemas anti-cheat podem bloquear sobreposicoes ou a captura do Windows; nesses casos, selecione janela sem bordas nas configuracoes do jogo.

No pacote local deste projeto, `iniciar_tradutor_jogos.bat` inicia o bridge, verifica o OCR e somente entao abre o Electron.

## Instalar A Extensao No Navegador

1. Abra `chrome://extensions` no Chrome ou `edge://extensions` no Edge.
2. Ative `Modo do desenvolvedor`.
3. Clique em `Carregar sem compactacao`.
4. Selecione esta pasta:

```text
Documentos\I-LOVE-WEBCOMICS\extension
```

5. Abra as opcoes da extensao.
6. Deixe assim:

```text
Bridge URL: http://127.0.0.1:8765
Origem: en
Destino: pt-BR
OCR: PaddleOCR marcado (EasyOCR e opcional e mais lento)
```

## Usar

1. Abra uma HQ ou webcomic no navegador.
2. Clique no botao da extensao ou use `Alt+Q`.
3. Arraste somente em cima do texto.
4. Espere alguns segundos.
5. A traducao aparece perto da selecao.

Dica: selecione so o balao ou legenda. Se selecionar a pagina inteira, fica lento e erra mais.

Para trocar o atalho, abra:

```text
chrome://extensions/shortcuts
```

## Atualizar

Se voce baixou com Git:

```powershell
cd "$env:USERPROFILE\Documents\I-LOVE-WEBCOMICS"
git pull
cd bridge
.\.venv\Scripts\python.exe -m pip install -r requirements.txt -r requirements-tesseract.txt
cd ..\electron_client
npm ci
```

Se voce baixou ZIP, baixe o ZIP novo e substitua a pasta antiga.

## Problemas Comuns

### A extensao diz que nao conseguiu conectar

O programa local provavelmente nao esta rodando. Abra o PowerShell e rode:

```powershell
cd "$env:USERPROFILE\Documents\I-LOVE-WEBCOMICS\bridge"
.\.venv\Scripts\python.exe -m hq_ocr_bridge
```

### `python` nao e reconhecido

Reinstale o Python e marque:

```text
Add Python to PATH
```

Depois feche e abra o PowerShell de novo.

### A primeira traducao demora

Inicie pelo `iniciar_tradutor_jogos.bat` e espere a mensagem de que tudo esta pronto. Se o bridge for iniciado manualmente, acompanhe `http://127.0.0.1:8765/ready`; o endpoint responde HTTP 200 depois do aquecimento.

## Desempenho

O caminho desktop rapido aplica estas otimizacoes:

- abre o seletor imediatamente e captura somente depois que a regiao foi escolhida;
- recorta a regiao no processo principal do Electron e envia apenas esse PNG ao bridge;
- usa Tesseract local com filtragem de artefatos pela posicao e confianca das palavras;
- reutiliza resultados por imagem e texto com caches LRU/TTL;
- cancela trabalho obsoleto quando uma captura mais nova chega;
- reutiliza a janela de traducao e conexoes HTTP.

O Electron e o bridge imprimem linhas `[performance]` com os tempos de captura, recorte, codificacao, OCR, traducao e total. O JSON retornado tambem inclui `performance.timings` e os indicadores de cache.

### A traducao ficou estranha

Pode acontecer. As vezes o OCR le certo, mas o tradutor entende a frase mal. Tente selecionar uma area menor, pegando apenas o texto.

### PowerShell bloqueou a ativacao da venv

Nao precisa ativar nada. Use sempre este formato:

```powershell
.\.venv\Scripts\python.exe -m hq_ocr_bridge
```

## Usar Sem Instalar No PC

Ainda nao tem servidor publico pronto.

Enquanto nao existir um servidor online, cada pessoa precisa rodar o programa local no proprio PC.
