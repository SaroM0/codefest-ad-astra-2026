"""Etapa 3 — EMBEDDINGS.  `Chunk[]` → vectores + índice.

Aún sin implementar.

ENTRADA:  `artifacts/chunking/`   (`adastra.core.paths.ArtifactPaths.chunking`)
SALIDA:   `artifacts/embeddings/` (`adastra.core.paths.ArtifactPaths.embeddings`)

Restricción que viene del corpus y conviene tener presente desde el principio: el
corpus es multilingüe (es/en/pt, más 20 PDFs en árabe, ruso, coreano, japonés y chino).
Cada documento trae `source.language` y `source.dominant_script` ya detectados; el
modelo de embedding tiene que ser multilingüe o hay que declarar qué se deja fuera.
"""
