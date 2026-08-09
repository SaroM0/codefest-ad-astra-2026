"""Escritura de documentos canónicos, manifest y reportes.

Regla de tamaño: los bloques van inline salvo que superen `INLINE_BLOCK_LIMIT`, en cuyo
caso viven en `{DOC_ID}.blocks.jsonl`. `F1-AIINDEX-056` es un solo DOC_ID con 111.775
filas: inline serían ~200 MB de JSON que habría que cargar entero para leer un bloque,
invirtiendo exactamente la ventaja que justifica un archivo por documento.

El *dónde* de cada artefacto no se decide aquí sino en `adastra.core.paths`: este módulo
sólo decide el *cómo*. Las etapas siguientes leen esos mismos artefactos y no pueden
depender de un layout que viva dentro del escritor de la ingesta.
"""

from __future__ import annotations

import json
from pathlib import Path

from adastra.core.jsonl import write_line
from adastra.core.models import CanonicalDocument, ContentBlock
from adastra.core.paths import ArtifactPaths

from .. import config


class ArtifactWriter:
    def __init__(self, output_root: Path) -> None:
        paths = ArtifactPaths(Path(output_root))

        self.root = paths.root
        self.ingestion = paths.ingestion.root
        self.documents = paths.documents
        self.reports = paths.ingestion.reports
        self.quarantine = paths.quarantine
        self.cache = paths.cache
        # FUERA de ingestion/: los artefactos de evaluación no pueden acabar mezclados
        # con el corpus recuperable (invariante I10).
        self.evaluation = paths.evaluation

        for path in (
            self.documents,
            self.reports,
            self.quarantine,
            self.cache,
            self.evaluation,
        ):
            path.mkdir(parents=True, exist_ok=True)

    # -- documentos -----------------------------------------------------------------
    def write_document(
        self, doc: CanonicalDocument, blocks: list[ContentBlock]
    ) -> None:
        doc.block_count = len(blocks)

        if len(blocks) > config.INLINE_BLOCK_LIMIT:
            ref = f"{doc.doc_id}.blocks.jsonl"
            doc.blocks = None
            doc.blocks_ref = ref
            with (self.documents / ref).open("w", encoding="utf-8") as f:
                for block in blocks:
                    write_line(f, block)
        else:
            doc.blocks = blocks
            doc.blocks_ref = None

        (self.documents / f"{doc.doc_id}.json").write_text(
            doc.model_dump_json(indent=2, exclude_none=True), encoding="utf-8"
        )

    # -- líneas JSONL ----------------------------------------------------------------
    def open_jsonl(self, relative: str):
        path = self.ingestion / relative
        path.parent.mkdir(parents=True, exist_ok=True)
        return path.open("w", encoding="utf-8")

    write_line = staticmethod(write_line)

    # -- reportes --------------------------------------------------------------------
    def write_report(self, name: str, payload: object) -> None:
        (self.reports / name).write_text(
            json.dumps(payload, ensure_ascii=False, indent=2, default=str),
            encoding="utf-8",
        )

    def write_evaluation(self, name: str, payload: object) -> None:
        (self.evaluation / name).write_text(
            json.dumps(payload, ensure_ascii=False, indent=2, default=str),
            encoding="utf-8",
        )
