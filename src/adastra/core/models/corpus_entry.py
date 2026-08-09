"""Entrada del registry: un registro por archivo del disco (1.848)."""

from __future__ import annotations

from typing import Literal

from pydantic import BaseModel, Field

Role = Literal["retrievable", "metadata", "evaluation", "noise"]

TerminalStatus = Literal[
    "pending",
    "success",
    "intentional_skip",
    "invalid_source",
    "quarantined",
    "failure",
]


class CorpusEntry(BaseModel):
    """Un archivo del disco, con su identidad y su destino en el pipeline.

    La identidad física es `relative_path`, NUNCA el basename: hay 47 colisiones de
    basename en CSET (`Reports/` vs `Translation/`) que son documentos completamente
    distintos, verificado por MD5.
    """

    # Del índice maestro. None para los 13 extras y los 9 .DS_Store.
    doc_id: str | None = None
    phenomenon: str | None = None
    observatory: str | None = None
    observatory_code: str | None = None
    declared_type: str | None = None

    # Del filesystem.
    relative_path: str
    filename: str
    extension: str
    size_bytes: int
    sha256: str

    # De la clasificación.
    detected_format: str | None = None
    format_mismatch: bool = False

    role: Role = "retrievable"
    role_reason: str = ""

    status: TerminalStatus = "pending"
    status_reason: str = ""

    # Señal para la capa de retrieval: los datasets bibliométricos no se responden
    # recuperando una fila suelta; su valor es filtrado estructurado.
    indexing_hint: Literal["full", "structured_only"] = "full"

    warnings: list[str] = Field(default_factory=list)

    @property
    def in_index(self) -> bool:
        return self.doc_id is not None
