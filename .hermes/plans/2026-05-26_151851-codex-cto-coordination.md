# HQ OCR Translator — Plano de Coordenação para Codex

> Para o Codex: executar este plano em tarefas pequenas, com validação a cada etapa, sem pular setup.

Objetivo:
Colocar o projeto HQ OCR Translator em um estado operacional estável para o Codex conseguir evoluir o MVP com segurança, previsibilidade e feedback rápido.

Arquitetura atual:
O projeto é dividido em duas partes:
- extension/: extensão Chrome/Edge Manifest V3
- bridge/: API Flask local que recebe screenshot, recorta a seleção, roda OCR, escolhe o melhor texto e traduz com LibreTranslate

Fluxo atual resumido:
1. popup.js dispara a ação.
2. background.js injeta content script e CSS.
3. contentScript.js permite selecionar uma área visível da página.
4. background.js chama chrome.tabs.captureVisibleTab.
5. O bridge recebe imageDataUrl + selection + viewport em /v1/translate-selection.
6. image_utils.py recorta a área.
7. ocr.py roda EasyOCR/Tesseract.
8. ranking.py escolhe o melhor resultado.
9. libretranslate.py traduz.
10. A extensão mostra o overlay com loading, erro ou tradução.

Tech stack:
- JavaScript vanilla na extensão
- Chrome/Edge Extension Manifest V3
- Python + Flask no bridge
- Pillow
- EasyOCR
- Tesseract/pytesseract
- LibreTranslate local

Estado observado:
- Há README e estrutura de MVP coerente.
- Há testes de bridge em bridge/tests/.
- Não há evidência de testes automatizados da extensão.
- O diretório hq-ocr-translator não está versionado em git.
- Codex CLI está instalado no sistema, mas precisa de repositório git para trabalhar bem.
- Tentar rodar pytest no ambiente atual falhou porque pytest não está instalado.

Principais riscos técnicos:
- Projeto fora de git bloqueia o fluxo ideal do Codex.
- OCR e tradução dependem de serviços locais e setup externo frágil.
- Falta smoke test ponta a ponta.
- Robustez de UX/erros da extensão ainda é bem MVP.
- Observabilidade baixa para debugar OCR ruim.
- O sleep(80) antes do capture é heurístico e pode falhar em cenários reais.

---

## Fase 0 — Preparar o terreno para o Codex

### Task 0.1: Transformar a raiz em repositório git

Objetivo:
Permitir que o Codex opere com histórico, diffs e commits.

Arquivos:
- Criar: .gitignore
- Inicializar: repositório git na raiz do projeto

Passos:
1. Entrar em /mnt/c/Users/GADEIM/Documents/Tradutor OCR extensao/hq-ocr-translator
2. Rodar git init
3. Criar .gitignore com pelo menos:
   - bridge/.venv/
   - __pycache__/
   - *.pyc
   - .pytest_cache/
   - node_modules/
   - dist/
   - build/
   - .DS_Store
4. Fazer commit inicial do estado atual.

Validação:
- git status limpo
- git log com commit inicial

### Task 0.2: Padronizar working directory e comandos base

Objetivo:
Evitar que o Codex rode fora da pasta certa.

Arquivos:
- Possível criação: docs/dev-setup.md ou atualização do README.md

Passos:
1. Definir a raiz oficial do projeto como hq-ocr-translator/
2. Documentar comandos mínimos de:
   - setup do bridge
   - rodar testes
   - subir bridge
   - carregar extensão no navegador

Validação:
- Um desenvolvedor novo consegue reproduzir o setup sem adivinhar caminho.

---

## Fase 1 — Fechar ambiente reproduzível

### Task 1.1: Criar ambiente Python do bridge

Objetivo:
Permitir que testes e execução local funcionem de forma consistente.

Arquivos:
- bridge/requirements.txt
- bridge/requirements-dev.txt
- bridge/requirements-ocr.txt

Passos:
1. Criar venv em bridge/.venv
2. Instalar requirements.txt e requirements-dev.txt
3. Verificar se pytest fica disponível

Validação:
- bridge/.venv ativo
- python -m pytest --version funciona

### Task 1.2: Fazer os testes atuais do bridge rodarem

Objetivo:
Garantir baseline de qualidade.

Arquivos:
- bridge/tests/test_app.py
- bridge/tests/test_ranking.py
- bridge/tests/test_image_utils.py
- quaisquer arquivos do bridge que precisem correção mínima

Passos:
1. Rodar pytest em bridge/
2. Corrigir falhas reais, se existirem
3. Registrar o comando oficial de teste

Validação:
- pytest passa 100% no bridge

### Task 1.3: Validar dependências externas do pipeline real

Objetivo:
Descobrir cedo o que está quebrado fora do código.

Arquivos:
- README.md ou docs/dev-setup.md

Passos:
1. Verificar LibreTranslate em http://127.0.0.1:5000
2. Verificar Tesseract no PATH
3. Verificar EasyOCR e política de download/modelos
4. Confirmar resposta útil de GET /health

Validação:
- /health responde com status coerente para bridge, OCR e tradução

---

## Fase 2 — Endurecer o backend primeiro

### Task 2.1: Aumentar cobertura de contrato do endpoint principal

Objetivo:
Blindar o núcleo do sistema antes de mexer na UX.

Arquivos:
- bridge/tests/test_app.py
- bridge/hq_ocr_bridge/app.py

Adicionar testes para:
- body não JSON
- selection ausente ou inválida
- viewport ausente ou inválido
- engines não lista
- engines desconhecidas
- OCR sem texto
- LibreTranslate indisponível retornando 502
- imageDataUrl inválido

Validação:
- Testes cobrindo erros comuns do contrato HTTP

### Task 2.2: Melhorar observabilidade do bridge

Objetivo:
Facilitar debug de OCR e integração.

Arquivos prováveis:
- bridge/hq_ocr_bridge/app.py
- bridge/hq_ocr_bridge/ocr.py
- bridge/hq_ocr_bridge/libretranslate.py
- bridge/hq_ocr_bridge/image_utils.py

Passos:
1. Adicionar logging por etapa:
   - decode da imagem
   - crop
   - OCR por engine
   - score/ranking
   - tradução
2. Registrar warnings e tempos básicos quando possível
3. Evitar logging excessivo de payload bruto/base64

Validação:
- Em um caso de erro, dá para saber em qual etapa falhou

### Task 2.3: Criar smoke test do bridge com fixture real

Objetivo:
Ter uma validação semi-realista do pipeline.

Arquivos prováveis:
- bridge/tests/fixtures/
- novo teste de integração leve
- scripts de apoio, se necessário

Passos:
1. Adicionar 1 ou mais imagens pequenas de exemplo
2. Testar crop + OCR fake ou controlado
3. Se possível, criar procedimento manual guiado para OCR real

Validação:
- Existe um caminho simples para detectar regressão do pipeline

---

## Fase 3 — Endurecer a fronteira extensão <-> bridge

### Task 3.1: Revisar estados de erro da extensão

Objetivo:
Melhorar confiabilidade percebida pelo usuário.

Arquivos prováveis:
- extension/background.js
- extension/contentScript.js
- extension/options.js
- extension/popup.js

Cobrir explicitamente:
- bridge offline
- HTTP 502 do bridge
- OCR sem texto detectado
- página onde script injection falha
- captureVisibleTab falhando
- seleção pequena demais
- retorno parcial com warnings

Validação:
- Todo erro importante vira mensagem clara no overlay ou popup

### Task 3.2: Reduzir heurística frágil do capture

Objetivo:
Diminuir falhas causadas por timing arbitrário.

Arquivos prováveis:
- extension/background.js
- extension/contentScript.js

Passos:
1. Revisar o sleep(80)
2. Avaliar sincronização melhor entre remoção de seleção/loading e captura
3. Garantir que a área capturada não contenha lixo visual do overlay de seleção

Validação:
- Captura consistente em testes manuais repetidos

### Task 3.3: Documentar procedimento manual de QA da extensão

Objetivo:
Dar ao Codex um checklist claro de regressão.

Arquivos:
- docs/manual-qa.md ou README.md

Checklist mínimo:
- carregar extensão unpacked
- abrir uma página de HQ/teste
- selecionar área com texto
- verificar loading
- verificar tradução
- verificar erro amigável se bridge estiver offline

Validação:
- Qualquer pessoa consegue repetir o fluxo de teste manual

---

## Fase 4 — Melhorar OCR com base em dados reais

### Task 4.1: Coletar amostras reais de HQ para regressão

Objetivo:
Parar de otimizar no escuro.

Arquivos:
- docs/ocr-regression.md
- possível pasta de fixtures manuais sem conteúdo sensível

Passos:
1. Separar 3 a 10 recortes reais representativos
2. Classificar casos: fonte estilizada, baixo contraste, texto pequeno, etc.
3. Definir expectativa mínima por amostra

Validação:
- Há dataset pequeno para comparação antes/depois

### Task 4.2: Tornar o preprocess configurável

Objetivo:
Permitir iteração rápida sem refatorações grandes.

Arquivos prováveis:
- bridge/hq_ocr_bridge/image_utils.py
- bridge/hq_ocr_bridge/config.py
- bridge/tests/test_image_utils.py

Passos:
1. Identificar pontos do preprocess que hoje estão fixos
2. Expor toggles/parâmetros mínimos se necessário
3. Medir efeito nas amostras reais

Validação:
- Dá para ajustar preprocess sem quebrar o contrato do app

### Task 4.3: Refinar ranking de OCR

Objetivo:
Escolher melhor resultado de forma menos frágil.

Arquivos prováveis:
- bridge/hq_ocr_bridge/ranking.py
- bridge/tests/test_ranking.py

Passos:
1. Revisar pesos heurísticos atuais
2. Adicionar testes de ranking com casos reais/limítrofes
3. Ajustar consenso entre engines sem inflar falsos positivos

Validação:
- Melhor engine é escolhida com mais consistência nos casos de teste

---

## Fase 5 — Evolução de produto/UX

### Task 5.1: Melhorar overlay de resultado

Objetivo:
Aumentar utilidade prática do MVP.

Possíveis melhorias:
- copiar tradução
- expandir/recolher texto OCR
- retry
- melhor posicionamento
- histórico curto da última tradução

Arquivos prováveis:
- extension/contentScript.js
- extension/contentStyles.css

### Task 5.2: Melhorar tela de opções

Objetivo:
Facilitar operação e debug.

Possíveis melhorias:
- status visual de health por componente
- texto de ajuda de setup
- botão de teste mais informativo

Arquivos prováveis:
- extension/options.js
- extension/options.html
- extension/options.css

---

## Ordem recomendada de execução pelo Codex

1. Git e .gitignore
2. Setup reproduzível do bridge
3. Fazer pytest passar
4. Validar /health e dependências reais
5. Reforçar testes do endpoint principal
6. Adicionar logging/observabilidade
7. Endurecer erros e timing da extensão
8. Criar smoke test/manual QA
9. Só depois otimizar OCR e UX

---

## Critério de pronto do próximo marco

O próximo marco aceitável é:
- projeto em git
- setup reproduzível documentado
- testes do bridge passando
- /health confiável
- fluxo manual básico funcionando: selecionar área -> OCR -> tradução -> overlay
- mensagens de erro úteis quando o bridge ou OCR falharem

---

## Instrução operacional para o Codex

Quando começar a executar:
- sempre trabalhar a partir de /mnt/c/Users/GADEIM/Documents/Tradutor OCR extensao/hq-ocr-translator
- não mexer em muitas frentes ao mesmo tempo
- fazer uma etapa pequena por vez
- validar após cada etapa
- registrar commits pequenos e claros
- priorizar infraestrutura, testes e observabilidade antes de otimizações de OCR e UX

## Arquivos mais prováveis de mudança nas primeiras execuções
- /mnt/c/Users/GADEIM/Documents/Tradutor OCR extensao/hq-ocr-translator/.gitignore
- /mnt/c/Users/GADEIM/Documents/Tradutor OCR extensao/hq-ocr-translator/README.md
- /mnt/c/Users/GADEIM/Documents/Tradutor OCR extensao/hq-ocr-translator/bridge/hq_ocr_bridge/app.py
- /mnt/c/Users/GADEIM/Documents/Tradutor OCR extensao/hq-ocr-translator/bridge/hq_ocr_bridge/ocr.py
- /mnt/c/Users/GADEIM/Documents/Tradutor OCR extensao/hq-ocr-translator/bridge/hq_ocr_bridge/image_utils.py
- /mnt/c/Users/GADEIM/Documents/Tradutor OCR extensao/hq-ocr-translator/bridge/hq_ocr_bridge/ranking.py
- /mnt/c/Users/GADEIM/Documents/Tradutor OCR extensao/hq-ocr-translator/bridge/tests/test_app.py
- /mnt/c/Users/GADEIM/Documents/Tradutor OCR extensao/hq-ocr-translator/extension/background.js
- /mnt/c/Users/GADEIM/Documents/Tradutor OCR extensao/hq-ocr-translator/extension/contentScript.js
- /mnt/c/Users/GADEIM/Documents/Tradutor OCR extensao/hq-ocr-translator/extension/options.js

## Observações finais de CTO
- A arquitetura do MVP está boa o bastante para continuar.
- O gargalo agora não é “inventar mais feature”; é criar base operacional para o Codex parar de trabalhar no escuro.
- Sem git, testes e smoke test real, qualquer melhoria no OCR vira chute caro.
- O caminho certo é estabilizar a fundação primeiro e só depois acelerar produto.