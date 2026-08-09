# Ad Astra — CODEFEST 2026

Sistema RAG sobre el **CORPUS CODEFEST AD ASTRA 2026**: 1.848 archivos, 3,0 GB, tres
fenómenos, 21 observatorios, ocho idiomas y un formato distinto casi por fuente.

El pipeline son cuatro etapas encadenadas. Cada una consume el artefacto de la anterior
y no sabe nada de cómo se produjo:

```
corpus crudo → INGESTA → CHUNKING → EMBEDDINGS → RETRIEVAL → respuesta + cita
                  ✅         ⬜           ⬜           ⬜
```

| Etapa | Código | Entrada → salida | Estado |
|---|---|---|---|
| 1 · Ingesta | [`src/adastra/ingestion/`](src/adastra/ingestion/) | corpus → `CanonicalDocument[]` | ✅ [arquitectura](docs/ARCHITECTURE_INGESTION.md) |
| 2 · Chunking | [`src/adastra/chunking/`](src/adastra/chunking/) | `CanonicalDocument[]` → `Chunk[]` | ⬜ pendiente |
| 3 · Embeddings | [`src/adastra/embeddings/`](src/adastra/embeddings/) | `Chunk[]` → vectores + índice | ⬜ pendiente |
| 4 · Retrieval | [`src/adastra/retrieval/`](src/adastra/retrieval/) | pregunta → chunks + cita | ⬜ pendiente |

---

## Arranque

```bash
make setup        # venv de Python 3.11 + dependencias (requiere uv)
make ocr          # opcional: motor OCR, sin sudo
make check-env    # ¿están poppler, el venv y el corpus?
make              # todos los objetivos disponibles
```

El **corpus no está en el repositorio** (3 GB). Se coloca descomprimido en la raíz como
`CORPUS CODEFEST AD ASTRA 2026/`, o se apunta a otra ruta:

```bash
export CODEFEST_CORPUS=/ruta/al/corpus
```

Requisito de sistema: `sudo apt install poppler-utils`.

## Cómo está organizado

```
src/adastra/
├── core/           COMPARTIDO — el contrato entre etapas
│   ├── models/     CanonicalDocument · ContentBlock · calidad
│   ├── paths.py    dónde escribe y lee cada etapa dentro de artifacts/
│   ├── jsonl.py    lectura en streaming / escritura de JSONL
│   └── documents.py cargar documentos ya ingeridos (resuelve blocks_ref)
├── ingestion/      etapa 1
├── chunking/       etapa 2
├── embeddings/     etapa 3
└── retrieval/      etapa 4

make/<etapa>.mk     los objetivos `make` de cada etapa
scripts/<etapa>/    utilidades de línea de comandos de cada etapa
docs/               un ARCHITECTURE_<ETAPA>.md por etapa
data/               entradas hechas a mano (NO derivadas: van al repo)
artifacts/          TODA la salida — derivada, reproducible, fuera del repo
```

Tres reglas que mantienen esto ordenado cuando trabajan cuatro personas a la vez:

1. **Una etapa nunca importa de otra etapa.** Importa de `core`. Si dos etapas necesitan
   lo mismo, sube a `core` — así el grafo de dependencias no puede formar ciclos.
2. **Relativo dentro de una etapa, absoluto entre etapas.** Dentro de `ingestion/` se
   escribe `from ..models import X`; para cruzar la frontera, `from adastra.core.models
   import X`. Se ve de un vistazo cuándo una línea atraviesa un límite del diseño.
3. **Cada etapa tiene su `make/<etapa>.mk`, su `scripts/<etapa>/` y su doc.** Son los
   ficheros que todo el mundo edita a la vez; separados, no hay conflictos de merge.

### Añadir una etapa

Rellena su `src/adastra/<etapa>/`, crea `make/<etapa>.mk` con
`HELP_TARGETS += help-<etapa>` y un objetivo `help-<etapa>` — el `Makefile` raíz lo
recoge solo. Escribe siempre bajo `ArtifactPaths().<etapa>`.

## Artefactos

Todo lo que produce el pipeline vive en `artifacts/` y **está en `.gitignore`**: son
~550 MB por corrida y son derivados. Si algo de `artifacts/` no se puede regenerar desde
el corpus, es un bug del pipeline, no un fichero que versionar.

```
artifacts/
├── ingestion/    documents · reports · quarantine · cache · registry · manifest
├── chunking/     ⬜
├── embeddings/   ⬜
├── retrieval/    ⬜
└── evaluation/   gold set y preguntas — FUERA de las etapas (invariante I10)
```

`evaluation/` cuelga de la raíz a propósito: el gold set y las 50 preguntas no pueden
acabar mezclados con nada indexable. Leerlos para medir es correcto; indexarlos es fuga.

## Estado de la etapa 1

Última corrida completa sobre los 1.848 archivos:

| | |
|---|---|
| documentos escritos | 1.731 |
| reconciliación | 1.826 índice + 13 extras + 9 ruido = 1.848 ✓ |
| invariantes | 11 / 11 ✓ |
| gold set (C6) | 15 / 15 fragmentos localizados ✓ |
| páginas PDF | 36.822 · 35.688 nativas · 1.134 OCR |
| idiomas | en 1.003 · es 625 · pt 63 · zh 9 · ar 5 · ru 5 · ja 2 · ko 2 |
| cuarentena | 5 (escaneos sin OCR disponible) |

Reproducible con `make ingest && make check`. Detalle completo en
[`docs/ARCHITECTURE_INGESTION.md`](docs/ARCHITECTURE_INGESTION.md), incluida la sección
«Implementado pero inactivo» — léela antes de dar por hecha una capacidad.

## Documentación

[`docs/ARCHITECTURE_INGESTION.md`](docs/ARCHITECTURE_INGESTION.md) — la arquitectura real
de la etapa 1, escrita desde el código y verificada contra los artefactos: el corpus en
cifras, el flujo, cada parser, cómo se mide la calidad, las 11 invariantes, qué está
implementado pero desconectado y qué hereda la etapa siguiente.

Es el único documento de diseño del repositorio. Los planes previos (`PLAN.md`,
`PLAN_INGESTA.md`, `ANALISIS_PLAN.md`, `ANALISIS_CORPUS.md`) se eliminaron: varios estaban
deprecados o describían decisiones que no se siguieron, y mantener cinco documentos que se
contradicen es peor que no tener ninguno. Lo que seguía siendo cierto está incorporado.

Cuando cierres una etapa, añade su `docs/ARCHITECTURE_<ETAPA>.md` con el mismo criterio:
lo que el código hace, no lo que se planeó.
