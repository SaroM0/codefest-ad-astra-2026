"""Ad Astra — pipeline RAG sobre el CORPUS CODEFEST AD ASTRA 2026.

Cuatro etapas encadenadas, cada una con su propio subpaquete:

    ingestion  → chunking → embeddings → retrieval

`core` es lo que comparten: el modelo canónico que viaja entre ellas, dónde viven
los artefactos y cómo se leen. Una etapa NUNCA importa de otra etapa: importa de
`core`. Si dos etapas necesitan lo mismo, sube a `core`.
"""

__version__ = "2.0.0"
