"""Etapa 4 — RETRIEVAL.  pregunta → chunks relevantes + cita.

Aún sin implementar.

ENTRADA:  `artifacts/embeddings/` (`adastra.core.paths.ArtifactPaths.embeddings`)
SALIDA:   `artifacts/retrieval/`  (`adastra.core.paths.ArtifactPaths.retrieval`)

Evaluación: `artifacts/evaluation/` tiene el gold set (15 pares pregunta→fragmento→
documento) y las 50 preguntas. Vive FUERA de las etapas por la invariante I10 — nunca
debe entrar al índice. Leerlo para medir es correcto; indexarlo es fuga.

Los datasets bibliométricos (`indexing_hint == "structured_only"`) no se responden
recuperando una fila suelta de PubMed: necesitan filtrado y agregación estructurada.
"""
