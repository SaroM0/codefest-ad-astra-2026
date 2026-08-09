"""Modelos de calidad.

Sustituyen al `quality_score: float` opaco: un 0.94 sin procedencia no es accionable.
Aquí toda confianza declara en qué se basa y qué señales la produjeron.
"""

from __future__ import annotations

from typing import Literal

from pydantic import BaseModel, Field

ConfidenceBasis = Literal[
    "entity_crosscheck",  # C3 — el más fuerte: entidades verificables del propio corpus
    "gold_fragment",      # C6 — el fragmento citado aparece literalmente
    "ocr_agreement",      # C1 — nativo vs OCR de control
    "title_match",        # C2 — el título del índice/catálogo aparece en el documento
    "mirror_match",       # C4/C5 — espejo CSV/XLSX o CSV/JSON
    "intrinsic_only",     # sólo señales internas
    "unverified",         # nada pudo comprobarse — se declara, no se esconde
]

QualityVerdict = Literal["accept", "ocr", "review", "reject"]


class SignalValue(BaseModel):
    """Una señal con su calibración relativa al grupo (observatorio × escritura).

    El percentil importa más que el valor absoluto: un PDF de UNOOSA en árabe y una
    alerta OCRizada no comparten distribución de `average_word_length`.
    """

    value: float
    pctile_in_source: float | None = None
    flag: str | None = None


class CrossCheck(BaseModel):
    type: str
    passed: bool
    detail: dict = Field(default_factory=dict)
    score: float | None = None


class ExtractionConfidence(BaseModel):
    score: float
    basis: ConfidenceBasis
    signals: dict[str, SignalValue] = Field(default_factory=dict)
    crosschecks: list[CrossCheck] = Field(default_factory=list)
    flags: list[str] = Field(default_factory=list)


class PageQuality(BaseModel):
    page_number: int
    verdict: QualityVerdict
    reasons: list[str] = Field(default_factory=list)
    signals: dict[str, float] = Field(default_factory=dict)
    characters: int = 0
    image_coverage: float = 0.0


class DocumentQuality(BaseModel):
    confidence: ExtractionConfidence
    usable: bool

    pages_total: int | None = None
    pages_native: int = 0
    pages_ocr: int = 0
    pages_quarantined: int = 0

    characters: int = 0
    warnings: list[str] = Field(default_factory=list)
