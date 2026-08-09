"""Bloque de contenido: la unidad estructural del documento canónico."""

from __future__ import annotations

from typing import Literal

from pydantic import BaseModel

BlockType = Literal[
    "heading",
    "paragraph",
    "list_item",
    "table_row",
    "table_text",
    "caption",
    # Fallback honesto: no se pudo segmentar con confianza. NUNCA etiquetar como
    # `paragraph` algo que no se sabe que lo sea — una mentira en el tipo se propaga
    # a todas las capas siguientes.
    "page_text",
]

ExtractionMethod = Literal[
    "native_reading_order",  # pdftotext modo por defecto (orden de lectura)
    "native_layout",         # pdftotext -layout (tablas / una columna)
    "native_tagged",         # PyMuPDF sobre PDF con estructura de accesibilidad
    "ocr",
    "structured",            # CSV / XLSX / JSON
    "manual",                # las 3 figuras de datos de SWF
]


class ContentBlock(BaseModel):
    """Un bloque de contenido con procedencia completa.

    `structured_data` preserva la semántica original (tipos, nombres de campo) mientras
    `text` queda disponible para embedding. No son alternativas: son complementarios.
    """

    block_id: str
    type: BlockType
    text: str
    order: int

    page: int | None = None
    row: int | None = None
    bbox: tuple[float, float, float, float] | None = None

    structured_data: dict | None = None
    extraction_method: ExtractionMethod

    # Marcado, NUNCA eliminado: en las 47 Alertas OCRizadas el encabezado repetido
    # contiene el código de alerta, que es lo que permite el emparejamiento con los
    # JSON y la trazabilidad oficial.
    is_boilerplate: bool = False

    # Qué tan fiable es el TIPO del bloque (no su texto).
    segmentation_confidence: float = 1.0
