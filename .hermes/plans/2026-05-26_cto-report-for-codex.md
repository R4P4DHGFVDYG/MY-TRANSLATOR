# CTO Report para Codex - 2026-05-26

## Mandato

Codex, trate este projeto como uma recuperação controlada de MVP, não como terreno para sair adicionando feature.

Seu papel agora é:
- estabilizar a base operacional
- reduzir incerteza técnica
- fechar o caminho mínimo até OCR real funcionando
- só depois pensar em melhoria de UX e otimização

## Estado atual consolidado

Repositório:
- O projeto já está em git.
- Histórico recente observado:
  - `8b25acf Record health validation findings`
  - `a1c81e2 Add Codex handoff for Hermes`
  - `9b7ace4 Document local development setup`
  - `b4b4141 Initial HQ OCR translator MVP`
- Working tree observado: limpo.

Arquitetura:
- `extension/`: extensão MV3 responsável por seleção de área, captura e overlay.
- `bridge/`: serviço local Flask que recebe screenshot, recorta, roda OCR, ranqueia resultado e traduz.

Validação já registrada:
- Testes atuais do bridge passaram.
- Sintaxe dos scripts principais da extensão já passou.
- Bridge já foi validado como operacional.
- LibreTranslate já foi validado como operacional.

Bloqueio real neste momento:
- OCR ainda não está fechado de verdade.
- `easyocr` não está instalado no `.venv` do bridge.
- `pytesseract` não está instalado no `.venv` do bridge.
- `tesseract` não está disponível no PATH do Windows.

## Diagnóstico de CTO

A situação mudou em relação ao plano inicial.

O problema principal já não é mais:
- falta de git
- falta de setup básico
- falta de documentação mínima

O problema principal agora é um só:
- a cadeia de OCR ainda não está operacional ponta a ponta

Isso significa que qualquer esforço em overlay, micro-UX, heurística fina de ranking ou polimento visual antes de fechar OCR real é prematuro.

## Prioridade absoluta

Fechar o OCR real com o menor caminho de risco.

Ordem recomendada:
1. Fazer o bridge reconhecer ao menos uma engine OCR real funcionando.
2. Validar `/health` com OCR instalado de fato.
3. Executar um smoke test mínimo de OCR fim a fim.
4. Só então abrir frente de robustez, observabilidade e UX.

## Estratégia recomendada

### Caminho preferido

Adotar EasyOCR como primeiro caminho de sucesso.

Justificativa:
- reduz dependência imediata do Tesseract no Windows
- encurta o tempo até a primeira prova de OCR real funcionando
- permite validar o pipeline do produto antes de ampliar compatibilidade

### Caminho secundário

Adicionar Tesseract depois, como engine complementar ou fallback.

Justificativa:
- Tesseract no Windows aumenta acoplamento com instalação externa e PATH
- isso é útil, mas não precisa ser o primeiro desbloqueio do MVP

## Próxima execução esperada do Codex

### Missão 1: destravar OCR real

Objetivo:
colocar o projeto em estado onde o `/health` reflita OCR instalado e onde exista pelo menos uma prova mínima de tradução via captura

Passos esperados:
1. Inspecionar `bridge/requirements-ocr.txt`.
2. Instalar dependências OCR no `.venv` do bridge.
3. Verificar se o projeto já suporta EasyOCR sem download automático ou se precisa decidir política de modelos.
4. Se necessário, habilitar explicitamente a política de download de modelos para ambiente local de desenvolvimento.
5. Revalidar `/health`.
6. Rodar um teste mínimo com imagem real ou fixture controlada.

Critério de pronto:
- `/health` mostra OCR disponível de forma coerente
- existe evidência objetiva de OCR retornando texto
- o bridge responde sem depender de interpretação manual vaga

## O que NÃO fazer agora

Não priorizar agora:
- refatoração ampla da extensão
- redesign de overlay
- ajustes cosméticos em options/popup
- heurísticas sofisticadas de ranking sem amostra real
- múltiplas frentes paralelas de melhoria

Se o OCR não estiver fechado, essas frentes só aumentam custo e dispersão.

## Regras de execução

- Trabalhe a partir da raiz oficial do projeto.
- Faça mudanças pequenas e reversíveis.
- Valide cada etapa antes da próxima.
- Se encontrar bloqueio externo, registre o bloqueio com evidência objetiva.
- Não “assuma que funciona”; sempre produzir prova curta: comando, saída e conclusão.
- Se precisar escolher entre abrangência e fechamento, escolha fechamento.

## Evidência mínima que um próximo report deve trazer

O próximo report do Codex precisa responder claramente:

1. `easyocr` foi instalado no `.venv` do bridge?
2. `pytesseract` foi instalado?
3. `tesseract` ficou de fora por decisão explícita ou por bloqueio?
4. O `/health` mudou? Como exatamente?
5. Existe uma execução real provando OCR?
6. O gargalo seguinte passou a ser qualidade do OCR ou ainda é setup?

## Definição de sucesso do próximo marco

Considerarei o próximo marco aceitável quando houver:
- bridge operacional
- LibreTranslate operacional
- pelo menos uma engine OCR operacional
- evidência mínima de fluxo real funcionando
- um report curto, factual e sem maquiagem

## Linha final de CTO

Codex: pare de preparar terreno. O terreno já está preparado o suficiente.

Agora o trabalho é converter a base atual em capacidade real de OCR.

Se tiver que escolher uma única meta: faça o projeto sair de “bridge e tradução ok, OCR bloqueado” para “OCR real confirmado”.
