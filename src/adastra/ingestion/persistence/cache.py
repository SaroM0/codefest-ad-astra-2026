"""Cache incremental, con clave POR ETAPA.

La v1 usaba un `pipeline_version` global: arreglar el adaptador de CENIA invalidaba las
~970 páginas de OCR, que son la parte cara. Aquí cada etapa tiene su propia clave y sólo
depende de lo que realmente la afecta, de modo que un cambio de umbral de calidad
**re-evalúa** en vez de re-OCRizar.
"""

from __future__ import annotations

import hashlib
import json
from pathlib import Path

from .. import config


def _key(*parts: str) -> str:
    return hashlib.sha256("|".join(parts).encode("utf-8")).hexdigest()[:32]


def extract_key(source_hash: str) -> str:
    return _key("extract", source_hash, config.EXTRACTOR_VERSION)


def ocr_key(image_hash: str, lang: str) -> str:
    return _key("ocr", image_hash, lang, config.OCR_VERSION)


def segmentation_key(source_hash: str) -> str:
    return _key(
        "segmentation",
        extract_key(source_hash),
        config.SEGMENTATION_VERSION,
    )


def document_key(source_hash: str) -> str:
    """Clave del documento canónico completo: encadena todas las etapas."""
    return _key(
        "document",
        segmentation_key(source_hash),
        config.QUALITY_VERSION,
        config.PIPELINE_VERSION,
    )


class DocumentCache:
    """Cache a nivel de documento canónico."""

    def __init__(self, root: Path, enabled: bool = True) -> None:
        self.root = root
        self.enabled = enabled
        self._index_path = root / "index.json"
        self._index: dict[str, str] = {}
        if enabled and self._index_path.exists():
            try:
                self._index = json.loads(self._index_path.read_text(encoding="utf-8"))
            except (json.JSONDecodeError, OSError):
                self._index = {}

    def is_fresh(self, doc_id: str, source_hash: str) -> bool:
        if not self.enabled:
            return False
        return self._index.get(doc_id) == document_key(source_hash)

    def mark(self, doc_id: str, source_hash: str) -> None:
        if self.enabled:
            self._index[doc_id] = document_key(source_hash)

    def flush(self) -> None:
        if not self.enabled:
            return
        self.root.mkdir(parents=True, exist_ok=True)
        self._index_path.write_text(
            json.dumps(self._index, indent=0), encoding="utf-8"
        )
