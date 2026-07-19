# Benchmark de OCR (somente desenvolvimento)

Este benchmark compara os mecanismos usando o mesmo `OcrService` do aplicativo, mas roda como uma ferramenta separada. Ele não é importado pelo Electron, não inicia junto com o bridge e não entra no executável do PyInstaller.

Ele mede apenas OCR. Nenhuma tradução online é enviada durante os testes.

## 1. Montar o conjunto de imagens

No PowerShell, a partir da pasta `bridge`:

```powershell
.\.venv\Scripts\python.exe tools\benchmark_ocr.py prepare `
  --images debug-captures `
  --source-format debug-captures `
  --limit 200
```

O comando:

- usa somente o `crop.png` de cada captura de debug;
- ignora imagens de pré-processamento para não processar o mesmo recorte duas vezes;
- remove duplicatas exatas por SHA-256;
- escolhe uma amostra reproduzível com a seed `42`;
- copia a amostra para `benchmark/data/ground-truth-images`;
- cria `benchmark/data/ground-truth.jsonl`.

O diretório `benchmark/data` é ignorado pelo Git porque pode conter telas e textos privados. Use `--reference-source` apenas se quiser manter referências para as capturas originais em vez de copiar as imagens. Use `--force` para substituir conscientemente um manifesto já existente.

## 2. Anotar a resposta correta

Abra `benchmark/data/ground-truth.jsonl`. Cada linha é um objeto JSON independente:

```json
{"id":"capture-001","image":"ground-truth-images/capture-001.png","text":"Looking through your brother's letters","language":"en","category":"pixel-art","split":"test","sequence":null,"frameIndex":null,"sha256":"..."}
```

Preencha o campo `text` exatamente como a legenda deveria ser lida. Linhas com `text` vazio são ignoradas. Campos úteis:

- `language`: `en`, `pt` ou outra tag aceita pelo pipeline;
- `category`: por exemplo `pixel-art`, `cursiva`, `cenario-em-movimento`, `baixo-contraste` ou `interface`;
- `split`: use `test` para a medição principal;
- `sequence` e `frameIndex`: opcionais, para identificar quadros consecutivos da mesma legenda.

Mantenha imagens fáceis e difíceis. Para avaliar o problema de cenário em movimento, guarde vários quadros da mesma legenda com fundos diferentes e marque todos com a categoria `cenario-em-movimento`.

## 3. Executar

```powershell
.\.venv\Scripts\python.exe tools\benchmark_ocr.py run `
  --manifest benchmark\data\ground-truth.jsonl `
  --repeats 3
```

Por padrão são testados:

- `automatic`: exatamente Tesseract + Windows OCR e o fallback PaddleOCR do modo Automático normal;
- `tesseract`;
- `windowsocr`;
- `paddleocr`;
- `easyocr`.

O cache do OCR é desativado somente nas tentativas do benchmark, evitando tempos artificialmente baixos. Os mecanismos são aquecidos antes da medição e o tempo de aquecimento é registrado separadamente. Para medir inicialização fria, adicione `--skip-warmup`.

Para comparar apenas alguns mecanismos:

```powershell
.\.venv\Scripts\python.exe tools\benchmark_ocr.py run `
  --manifest benchmark\data\ground-truth.jsonl `
  --profiles automatic paddleocr `
  --repeats 5
```

O perfil `standard` é usado por padrão e corresponde ao modo Automático normal. Um pré-processamento experimental pode ser testado sem alterar o aplicativo com `--preprocessing-profile pixel-art`.

## Resultados

Cada execução cria uma pasta em `benchmark/results` com:

- `benchmark-summary.md`: resumo para leitura rápida;
- `benchmark-attempts.csv`: uma linha por tentativa;
- `benchmark-results.json`: dados completos, avisos e resultados de cada engine.

O JSON também registra as versões das dependências e as configurações de OCR que podem alterar o resultado, sem copiar chaves ou configurações dos serviços de tradução.

As principais medidas são:

- `Exact`: texto idêntico à anotação;
- `Normalized exact`: comparação após a mesma normalização usada no aplicativo;
- `CER`: taxa de erro por caractere;
- `WER`: taxa de erro por palavra;
- `P50`, `P90` e `P95`: latência típica e latência de cauda;
- `Paddle fallback`: frequência com que o modo Automático precisou recorrer ao PaddleOCR.

CER, WER e latência menores são melhores. Compare resultados usando o mesmo manifesto, a mesma quantidade de repetições e o computador sem outras tarefas pesadas. Para uma decisão confiável, dê mais peso ao P95 e aos resultados por categoria do que apenas à média geral.
