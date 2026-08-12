"""Etapa 2 — CHUNKING.  `CanonicalDocument[]` → `Chunk[]`.

El paquete expone un chunker determinista y en streaming que consume la salida de
ingesta y escribe la base para embeddings en `artifacts/chunking/`.
"""

from .processor import ChunkRecord, build_chunks, chunk_documents, main, write_chunks

__all__ = ["ChunkRecord", "build_chunks", "chunk_documents", "main", "write_chunks"]