"""Documento canónico: el producto de la ingesta."""

from __future__ import annotations

from typing import Literal

from pydantic import BaseModel, Field

from .block import ContentBlock, ExtractionMethod
from .quality import DocumentQuality, PageQuality

DateConfidence = Literal["exact", "inferred", "ambiguous", "absent"]


class SourceMetadata(BaseModel):
    """Procedencia. Los campos de catálogo los puebla la etapa CATALOG JOIN."""

    phenomenon: str
    observatory: str
    observatory_code: str
    relative_path: str
    original_format: str

    # Poblados por catalog_join (§6). El índice maestro NO trae URL ni fecha:
    # sin esta etapa, los 760 PDFs quedan sin procedencia web.
    source_url: str | None = None
    original_filename: str | None = None
    published_date: str | None = None
    date_confidence: DateConfidence = "absent"
    original_title: str | None = None
    catalog_source: str | None = None

    # Escritura ANTES que idioma: 20 PDFs en árabe/ruso/coreano/japonés/chino que un
    # detector léxico latino marcaría como corruptos.
    script: dict[str, float] = Field(default_factory=dict)
    dominant_script: str | None = None
    language: str | None = None
    language_confidence: float | None = None


class PageContent(BaseModel):
    """Unidad mínima del PDF. La decisión native/OCR es POR PÁGINA.

    Así los 11 PDFs mixtos y los 6 falsos positivos del muestreo de primeras páginas
    dejan de ser casos especiales: son el caso general.
    """

    page_number: int
    text: str
    extraction_method: ExtractionMethod
    quality: PageQuality

    # Trazabilidad de la decisión de orden de lectura (§7.3): ambos scores y el margen.
    reading_order_scores: dict[str, float] = Field(default_factory=dict)
    is_tabular: bool = False
    warnings: list[str] = Field(default_factory=list)


class CanonicalDocument(BaseModel):
    doc_id: str
    pipeline_version: str

    source: SourceMetadata

    # Los bloques van inline salvo que superen INLINE_BLOCK_LIMIT, en cuyo caso viven
    # en `{DOC_ID}.blocks.jsonl`. F1-AIINDEX-056 es un solo DOC_ID con 111.775 filas.
    blocks: list[ContentBlock] | None = None
    blocks_ref: str | None = None
    block_count: int = 0

    metadata: dict = Field(default_factory=dict)
    metadata_warnings: list[str] = Field(default_factory=list)

    quality: DocumentQuality

    indexing_hint: Literal["full", "structured_only"] = "full"
    related_doc_ids: list[str] = Field(default_factory=list)
    potential_overlap_group: str | None = None


class ManifestEntry(BaseModel):
    """Traza por archivo. I7: nada desaparece en silencio."""

    doc_id: str | None
    relative_path: str
    role: str
    input_format: str
    detected_format: str | None = None
    status: str
    status_reason: str = ""

    pages: int | None = None
    native_pages: int = 0
    ocr_pages: int = 0
    blocks: int = 0
    characters: int = 0

    language: str | None = None
    dominant_script: str | None = None

    extraction_confidence: float | None = None
    confidence_basis: str | None = None

    warnings: list[str] = Field(default_factory=list)
    duration_ms: int = 0
