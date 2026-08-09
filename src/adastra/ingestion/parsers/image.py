"""Parser de imágenes.

Dos clases distintas, con tratamiento distinto:

  · **Imagen textual** → OCR normal.
  · **Gráfico de información** (matriz semáforo, tabla renderizada, infografía) → NO se
    resuelve con OCR.

Sobre las 3 figuras de datos de SWF: el análisis establece que la matriz semáforo del
resumen ejecutivo, la tabla 5-1 y las capacidades ASAT por país **no existen en ningún
formato textual del corpus** y son relevantes para q018, q024 y q026.

El fallback "OCR + bounding boxes" NO sirve para una matriz semáforo: devuelve la lista
de países y la lista de capacidades sin la relación que las une, que es el color de la
celda. Es peor que no hacer nada, porque parece contenido. Por eso estas tres se
transcriben a mano (`extraction_method="manual"`), con resultado exacto y auditable, sin
depender de un VLM ni de una decisión reglamentaria pendiente.
"""

from __future__ import annotations

import json
from pathlib import Path

from ..ocr.engine import OCRUnavailable, TesseractOCR, tesseract_available
from .base import BlockBuilder, ParseResult

# Fichero opcional con las transcripciones manuales, indexado por nombre de archivo.
MANUAL_TRANSCRIPTIONS = Path("data/manual_transcriptions.json")

# Figuras de datos identificadas: no se les aplica OCR ciego.
INFORMATION_GRAPHICS = (
    "stoplight-chart",
    "table-5-1",
    "asat-by-country",
)


def is_information_graphic(filename: str) -> bool:
    lowered = filename.lower()
    return any(marker in lowered for marker in INFORMATION_GRAPHICS)


def _load_manual(root: Path) -> dict:
    path = root / MANUAL_TRANSCRIPTIONS
    if not path.exists():
        return {}
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except (json.JSONDecodeError, OSError):
        return {}


def parse_image(
    path: Path,
    doc_id: str,
    pipeline_version: str,
    *,
    project_root: Path = Path("."),
    ocr_engine: TesseractOCR | None = None,
) -> ParseResult:
    result = ParseResult()
    builder = BlockBuilder(doc_id, pipeline_version)

    manual = _load_manual(project_root).get(path.name)
    if manual:
        text = manual.get("text", "")
        if block := builder.add(
            text,
            "table_row" if manual.get("structured_data") else "caption",
            "manual",
            structured_data=manual.get("structured_data"),
        ):
            result.blocks.append(block)
        result.metadata = {
            "schema": "image_manual_transcription",
            "source_figure": manual.get("figure"),
            "note": manual.get("note"),
        }
        return result

    if is_information_graphic(path.name):
        # Se registra explícitamente como pendiente en vez de producir un OCR que
        # parecería contenido y no lo sería.
        result.metadata = {"schema": "information_graphic"}
        result.warnings.append(
            "information_graphic__requires_manual_transcription__ocr_would_lose_"
            "cell_relationships"
        )
        return result

    if not tesseract_available():
        result.metadata = {"schema": "image"}
        result.warnings.append("ocr_needed_but_unavailable")
        return result

    engine = ocr_engine or TesseractOCR()
    try:
        ocr = engine.extract(path.read_bytes())
    except OCRUnavailable:
        result.metadata = {"schema": "image"}
        result.warnings.append("ocr_unavailable")
        return result

    text = ocr.text.strip()
    if text:
        if block := builder.add(text, "ocr", "ocr", segmentation_confidence=0.4):
            result.blocks.append(block)
    else:
        result.warnings.append("ocr_produced_no_text")

    result.metadata = {"schema": "image_ocr", "engine": ocr.engine}
    result.pages_ocr = 1
    return result
