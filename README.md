# I LOVE WEBCOMICS

Tradutor de HQs/webcomics para Chrome e Edge.

Voce seleciona um balao, legenda ou texto na pagina. A extensao le o texto da imagem e mostra a traducao em portugues.

Importante: a extensao precisa de um programinha local em Python rodando no seu PC. Sem ele, ela nao consegue fazer OCR.

## O Que Voce Precisa

- Windows 10 ou 11.
- Python 3.10 ou mais novo.
- Chrome ou Edge.
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
.\.venv\Scripts\python.exe -m pip install -r requirements.txt -r requirements-ocr.txt -r requirements-paddleocr.txt
```

Essa parte demora. E normal.

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
OCR: PaddleOCR e EasyOCR marcados
```

## Usar

1. Abra uma HQ ou webcomic no navegador.
2. Clique no botao da extensao ou use `Alt+Shift+O`.
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
.\.venv\Scripts\python.exe -m pip install -r requirements.txt -r requirements-ocr.txt -r requirements-paddleocr.txt
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

Normal. O OCR carrega modelos pesados na primeira vez.

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
