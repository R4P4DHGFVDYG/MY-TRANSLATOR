<p align="center">
  <img src="electron_client/assets/spider-intro.png" width="110" alt="Ícone de aranha do G.R.C Translator">
</p>

<h1 align="center">G.R.C TRANSLATOR</h1>

<p align="center">
  Tradução automática de legendas e textos diretamente da tela.
</p>

## Sobre o aplicativo

O G.R.C Translator foi criado principalmente para traduzir legendas de jogos. Você marca a área onde o texto aparece e continua jogando: quando a legenda muda, o aplicativo reconhece e mostra a tradução automaticamente.

### Destaques

- seleção de uma área automática;
- tradução exibida por cima do jogo;
- modos Automático e Automático — 8 bits, além da escolha manual entre os OCRs;
- atalho personalizado de teclado ou mouse;
- cores, posição e transparência configuráveis;
- suporte a mais de um monitor.

## O que é necessário

- Windows 10 ou 11;
- Python 3.10 ou mais recente;
- Node.js LTS;
- conexão com a internet;
- Tesseract OCR, usado primeiro pelo modo automático;
- pacote de idioma OCR do Windows para usar o mecanismo nativo opcional.

## Instalação

Abra o PowerShell e execute:

```powershell
cd "$env:USERPROFILE\Documents"
git clone https://github.com/R4P4DHGFVDYG/G-R-C-TRANSLATOR-.git
cd G-R-C-TRANSLATOR-

python -m venv .\bridge\.venv
.\bridge\.venv\Scripts\python.exe -m pip install --upgrade pip
.\bridge\.venv\Scripts\python.exe -m pip install -r .\bridge\requirements.txt -r .\bridge\requirements-windowsocr.txt -r .\bridge\requirements-tesseract.txt
winget install --id UB-Mannheim.TesseractOCR --exact

cd .\electron_client
npm ci
```

## Como iniciar

Abra um PowerShell na pasta `electron_client`:

```powershell
npm start
```

O aplicativo inicia o OCR local automaticamente e faz o aquecimento dos mecanismos durante a animação da aranha. Não é mais necessário manter um segundo PowerShell aberto.

## Como usar

1. Deixe o OCR em **Automático**. Em jogos com letras pixeladas, experimente **Automático — 8 bits**.
2. Clique em **Definir área automática**.
3. Marque a região onde as legendas aparecem.
4. Volte ao jogo e aguarde a próxima legenda.
5. Clique em **Parar tradução automática** quando terminar.

O atalho padrão é `Ctrl + Shift + Q`. Para trocar, clique em **Alterar** na seção de atalho e pressione a combinação ou o botão do mouse desejado.

## Jogos em tela cheia

Para melhor compatibilidade, use o jogo em **janela sem bordas**. Alguns jogos em tela cheia exclusiva ou com anti-cheat podem bloquear a captura e a legenda sobreposta.

## Observações

- O OCR funciona no computador, mas a tradução precisa de internet.
- A primeira inicialização de alguns mecanismos OCR pode demorar um pouco; o aquecimento começa junto com a animação de abertura.
- Ainda não existe um instalador pronto; por enquanto, o aplicativo é iniciado pelos comandos acima.
