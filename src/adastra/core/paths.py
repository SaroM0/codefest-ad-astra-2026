"""Dónde vive cada artefacto.

Única fuente de verdad del layout de `artifacts/`. Antes de este módulo cada script
llevaba su propio `Path("artifacts/ingestion")` hardcodeado: cuatro copias que había
que cambiar a la vez, y que impedían apuntar la revisión a una corrida distinta.

Layout:

    artifacts/
    ├── ingestion/    documents · reports · quarantine · cache · registry · manifest
    ├── chunking/     chunks · reports
    ├── embeddings/   vectors · index · reports
    ├── retrieval/    runs · reports
    └── evaluation/   FUERA de las etapas — invariante I10 (anti-leakage)

`evaluation/` cuelga de la raíz a propósito: el gold set y las preguntas no pueden
acabar mezclados con nada indexable. Si algún día es un subdirectorio de una etapa,
alguien terminará glob-eando la etapa entera y metiéndolo al índice.
"""

from __future__ import annotations

import os
from dataclasses import dataclass
from pathlib import Path

DEFAULT_ARTIFACTS = Path(os.environ.get("ADASTRA_ARTIFACTS", "artifacts")).expanduser()


@dataclass(frozen=True)
class StagePaths:
    """Directorio de una etapa. `reports/` es la convención común a las cuatro."""

    root: Path

    def __truediv__(self, relative: str | Path) -> Path:
        return self.root / relative

    @property
    def reports(self) -> Path:
        return self.root / "reports"

    def ensure(self, *subdirs: str) -> StagePaths:
        """Crea el directorio de la etapa y los subdirectorios indicados."""
        self.root.mkdir(parents=True, exist_ok=True)
        for name in subdirs:
            (self.root / name).mkdir(parents=True, exist_ok=True)
        return self


@dataclass(frozen=True)
class ArtifactPaths:
    root: Path = DEFAULT_ARTIFACTS

    # -- etapas -------------------------------------------------------------------
    @property
    def ingestion(self) -> StagePaths:
        return StagePaths(self.root / "ingestion")

    @property
    def chunking(self) -> StagePaths:
        return StagePaths(self.root / "chunking")

    @property
    def embeddings(self) -> StagePaths:
        return StagePaths(self.root / "embeddings")

    @property
    def retrieval(self) -> StagePaths:
        return StagePaths(self.root / "retrieval")

    # -- fuera de las etapas (I10) --------------------------------------------------
    @property
    def evaluation(self) -> Path:
        return self.root / "evaluation"

    # -- atajos de ingesta ----------------------------------------------------------
    # Los consumen los scripts de revisión y las etapas siguientes; son la superficie
    # pública de la ingesta, así que se nombran una sola vez aquí.
    @property
    def documents(self) -> Path:
        return self.ingestion.root / "documents"

    @property
    def manifest(self) -> Path:
        return self.ingestion.root / "manifest.jsonl"

    @property
    def registry(self) -> Path:
        return self.ingestion.root / "registry.jsonl"

    @property
    def quarantine(self) -> Path:
        return self.ingestion.root / "quarantine"

    @property
    def cache(self) -> Path:
        return self.ingestion.root / "cache"

    @property
    def summary(self) -> Path:
        return self.ingestion.reports / "summary.json"
