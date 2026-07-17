<p align="center">
  <img src="electron_client/assets/spider-intro.png" width="110" alt="Ícone de aranha do G.R.C Translator">
</p>

<h1 align="center">G.R.C TRANSLATOR</h1>

<p align="center">
  Tradução automática de legendas e textos diretamente da tela.
</p>

<p align="center">
  <a href="https://github.com/R4P4DHGFVDYG/MY-TRANSLATOR/releases">Baixar o G.R.C TRANSLATOR</a>
</p>

## Sobre o aplicativo

O G.R.C Translator foi criado principalmente para traduzir legendas de jogos. Você marca a área onde o texto aparece e continua jogando: quando a legenda muda, o aplicativo reconhece e mostra a tradução automaticamente.

### Destaques

- área automática para acompanhar legendas continuamente;
- área temporária para reconhecer e traduzir apenas uma vez;
- tradução exibida por cima do jogo sem bloquear os controles;
- modo **Automático**, além da escolha manual do OCR;
- três atalhos personalizáveis por teclado ou botão do mouse;
- fonte do Windows, tamanho, alinhamento, cores, posição e transparência configuráveis;
- suporte a mais de um monitor.

## Baixar e instalar

A versão atual é a **1.0.2** para Windows de 64 bits.

1. Baixe `GRC-Translator-Setup-1.0.2.exe`.
2. Abra o instalador e escolha a pasta de destino.
3. Inicie o **G.R.C TRANSLATOR** pelo atalho da área de trabalho ou do menu Iniciar.

## Requisitos

- Windows 10 ou 11 de 64 bits;
- conexão com a internet para realizar as traduções;
- textos em **inglês** ou **português (Brasil)**.

## Como usar

1. Escolha o idioma do texto e o idioma da tradução.
2. Deixe o mecanismo em **Automático** para o aplicativo comparar os mecanismos disponíveis.
3. Clique em **Definir área automática** e marque onde as legendas aparecem.
4. Volte ao jogo. O aplicativo reconhecerá novamente somente quando a imagem ou o texto mudar.
5. Use **Parar tradução automática** quando terminar.

Para traduzir somente uma tela ou uma legenda, use o atalho de **Área temporária**.

## Mecanismos OCR

- **Automático:** compara os mecanismos rápidos e usa o PaddleOCR quando a leitura fica incerta;
- **Windows OCR, Tesseract e EasyOCR:** podem ser selecionados individualmente para comparação;
- **Paddle OCR (Recomendado)** foi o que desempenhou maiores resultados nos testes

**Recomendo testar cada um pra ver qual se adapata melhor.**

O primeiro uso do PaddleOCR ou EasyOCR pode levar um pouco mais de tempo.

## Atalhos

- `Ctrl + Shift + Q`: selecionar a área automática;
- `Ctrl + Shift + W`: selecionar uma área temporária;
- `Ctrl + Shift + E`: interromper a seleção ou a tradução ativa.

Todos podem ser alterados na seção **Atalhos de captura** usando uma combinação de teclado ou um botão compatível do mouse.

## Jogos em tela cheia

Para melhor compatibilidade, use o jogo em **janela sem bordas**. Alguns jogos em tela cheia exclusiva ou com anti-cheat podem bloquear a captura e a legenda sobreposta.
