"""Etapa 2 — CHUNKING.  `CanonicalDocument[]` → `Chunk[]`.

Aún sin implementar.

ENTRADA. No leas `artifacts/ingestion/` a mano; usa el lector compartido, que ya
resuelve la indirección `blocks_ref` de los documentos grandes:

    from adastra.core.documents import iter_documents, iter_blocks

    for doc in iter_documents():
        if doc.indexing_hint == "structured_only":
            continue                       # bibliometría: se filtra y agrega, no se embebe
        for block in iter_blocks(doc):
            ...

SALIDA. `artifacts/chunking/` (ver `adastra.core.paths.ArtifactPaths.chunking`).

Lo que la ingesta ya dejó resuelto y no hay que rehacer:

  · `block.type` distingue heading / paragraph / list_item / table_row / caption, y
    `page_text` es el fallback honesto de «no se pudo segmentar con confianza».
    Mira `segmentation_confidence` antes de fiarte del tipo.
  · `block.is_boilerplate` marca encabezados repetidos. Están MARCADOS, no borrados,
    porque en las 47 Alertas OCRizadas el encabezado contiene el código de alerta.
    Decidir si se descartan es de esta etapa.
  · `doc.quality.confidence` trae score, base y señales: un documento en cuarentena o
    de confianza baja no debería pesar igual en el índice.
  · `doc.source` trae idioma, escritura, URL y fecha — metadatos de cita que cada chunk
    debe arrastrar para que retrieval pueda citar.
"""
