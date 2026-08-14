# Contrato de embeddings para retrieval

Este documento define el contrato obligatorio entre la etapa de **embeddings** y la de **retrieval**. El objetivo es que una consulta y un chunk se codifiquen en el **mismo espacio vectorial** y que un ID de FAISS siempre pueda resolverse a su fragmento.

> **Fuente de verdad de una corrida:** `docs/artifacts/embeddings/reports/manifest.json`.
> Retrieval debe leer ese manifiesto antes de cargar el índice.

## Configuración canónica

| Propiedad | Valor |
| --- | --- |
| Modelo público | `BAAI/bge-m3` |
| Librería | `FlagEmbedding.BGEM3FlagModel` |
| Tipo de vector | Denso: `dense_vecs` |
| Dimensión | **1024** (`float32`) |
| Pooling | Representación densa nativa de BGE-M3 |
| Normalización | L2, antes de insertar/buscar en FAISS |
| Índice | `faiss.IndexFlatIP` |
| Métrica efectiva | Similitud coseno, porque los vectores tienen norma unitaria |
| Longitud máxima del encoder | `8192` tokens (`max_length`) |
| Corpus actual | 137.578 chunks, máximo 220 tokens heurísticos por chunk |

BGE-M3 es un encoder multilingüe adecuado para el corpus en español, inglés y portugués. Una consulta en español y un chunk en inglés o portugués se codifican en el mismo espacio denso.

## Artefactos producidos

Después de una corrida completa y exitosa se publican, de forma atómica:

```text
docs/artifacts/embeddings/
├── index.faiss
├── metadata.jsonl
└── reports/
    └── manifest.json
```

También se deja una copia para entrega en:

```text
docs/entrega/base_vectorial/encoder_bge_m3/
```

`manifest.json` registra, entre otros datos:

- ID público del modelo y revisión/snapshot;
- dimensión real del índice;
- cantidad de vectores y líneas de metadata;
- pooling y normalización;
- dispositivo y `use_fp16`;
- versiones de `FlagEmbedding`, `faiss-cpu`, NumPy y Torch.

No se deben asumir estos valores desde código de retrieval: se deben validar contra el manifiesto.

## Invariante de correspondencia FAISS ↔ metadata

El builder procesa los chunks en orden y, para cada batch, realiza estas dos operaciones en ese mismo orden:

1. `index.add(vectors_normalizados)`;
2. escribe los chunks correspondientes en `metadata.jsonl`.

Por tanto:

```text
FAISS ID 0  ↔ línea 0 de metadata.jsonl
FAISS ID i  ↔ línea i de metadata.jsonl
```

Antes de atender consultas, retrieval debe comprobar:

```python
assert index.ntotal == len(metadata)
assert index.d == manifest["dimension"] == 1024
assert manifest["vectors"] == manifest["metadata_lines"] == index.ntotal
```

## Codificación obligatoria de consultas

**No** se debe usar otro encoder, otro pooling ni vectores sin normalizar. Retrieval debe reutilizar las utilidades de la etapa de embeddings:

```python
import json
from pathlib import Path

import faiss
from adastra.embeddings.builder import encode_dense_texts, load_encoder

root = Path("docs/artifacts/embeddings")
manifest = json.loads((root / "reports" / "manifest.json").read_text(encoding="utf-8"))
index = faiss.read_index(str(root / "index.faiss"))

# Cuando existe, model_load_path fija exactamente el snapshot usado al indexar.
model_source = manifest["model_load_path"] or manifest["model"]
model, _, _ = load_encoder(model_source)

query = "¿Qué países realizaron pruebas ASAT en 2026?"
query_vector = encode_dense_texts(model, [query])
assert query_vector.shape == (1, manifest["dimension"])

scores, ids = index.search(query_vector, k=10)
```

`encode_dense_texts` aplica el mismo `dense_vecs`, `max_length=8192` y normalización L2 que se usaron al indexar.

## Resolver resultados

Se debe leer `metadata.jsonl` manteniendo su orden:

```python
import json

with (root / "metadata.jsonl").open(encoding="utf-8") as handle:
    metadata = [json.loads(line) for line in handle if line.strip()]

hits = []
for rank, (faiss_id, score) in enumerate(zip(ids[0], scores[0]), start=1):
    if faiss_id < 0:
        continue
    chunk = metadata[int(faiss_id)]
    hits.append({
        "rank": rank,
        "score": float(score),
        "chunk_id": chunk["chunk_id"],
        "doc_id": chunk["doc_id"],
        "text": chunk["texto"],
    })
```

Los `scores` son similitudes coseno por la combinación **L2 + IndexFlatIP**. No se debe normalizar por segunda vez el vector ya obtenido de `encode_dense_texts`.

## Requisitos de entorno

Instalar el extra del proyecto:

```bash
pip install -e '.[embeddings]'
```

Incluye como mínimo:

```text
FlagEmbedding >= 1.3.4
faiss-cpu >= 1.8.0
```

Para crear el índice se ejecuta:

```bash
PYTHONPATH=src .venv/bin/python scripts/embeddings/build.py \
  --artifacts docs/artifacts \
  --model BAAI/bge-m3 \
  --batch-size 64
```

Si se usa un snapshot local para no depender de red, conservar `--model-reference BAAI/bge-m3`; el manifiesto registrará tanto el modelo público como la revisión exacta.

## Prohibiciones

- No mezclar embeddings de otro modelo en `index.faiss`.
- No usar `SentenceTransformer` u otro encoder para las consultas si el índice fue creado con `BGEM3FlagModel`.
- No alterar, ordenar ni filtrar `metadata.jsonl` después de construir el índice.
- No indexar `docs/artifacts/evaluation/`: las consultas y el gold set son evaluación, no evidencia recuperable.
