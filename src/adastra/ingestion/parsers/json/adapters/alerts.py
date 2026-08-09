"""Familia C — Alertas Tempranas (363 archivos). El núcleo de F3.

`alerta_meta` está relleno al 100% en los 363 archivos y es el mejor metadato del corpus:
código oficial, tipo, fecha ISO (el ÚNICO campo de fecha ya normalizado del corpus),
tema clave y municipios.

Estos metadatos no son sólo enriquecimiento: son el ground truth con el que se mide la
calidad del OCR de los 47 PDFs escaneados de esta misma fuente (contraste C3). Los PDFs se
llaman `ALERTAS_informesNNN.pdf` y los JSON `ALERTAS_{codigo}-{detail_id}.json`, así que
NO hay pareo por nombre: el código sólo aparece dentro del escaneo, y por tanto emparejar
sólo es posible después del OCR. Eso convierte el pareo en la métrica de calidad del OCR.
"""

from __future__ import annotations

import re

from .... import config
from ....normalization.metadata import filter_fields, normalize_date
from ....normalization.unicode_clean import clean_text, normalize_value
from ...base import BlockBuilder, ParseResult

# `municipios` viene como "Cartagena de Indias (Bolívar); Quibdó (Chocó)".
_MUNICIPALITY_RE = re.compile(r"\s*([^(;,]+?)\s*\(([^)]+)\)\s*")

# 21 alertas tienen menos de 50 palabras (mínimo 189 caracteres). No son fallos de
# extracción: son resúmenes mínimos. Se marcan, no se mandan a cuarentena.
_SHORT_DOCUMENT_WORDS = 50


def parse_municipalities(raw: object) -> list[dict[str, str]]:
    """Devuelve [{'municipality': ..., 'department': ...}]. 289 valores únicos."""
    if raw is None:
        return []
    if isinstance(raw, list):
        text = "; ".join(str(x) for x in raw)
    else:
        text = str(raw)

    out: list[dict[str, str]] = []
    seen: set[tuple[str, str]] = set()
    for match in _MUNICIPALITY_RE.finditer(text):
        muni = normalize_value(match.group(1))
        dept = normalize_value(match.group(2))
        if not muni:
            continue
        key = (muni.lower(), dept.lower())
        if key in seen:
            continue
        seen.add(key)
        out.append({"municipality": muni, "department": dept})

    if not out and text.strip():
        # Formato inesperado: se preserva crudo en vez de perderlo.
        for chunk in re.split(r"[;,]", text):
            value = normalize_value(chunk)
            if value:
                out.append({"municipality": value, "department": ""})
    return out


class AlertasAdapter:
    name = "alerta_temprana"

    @staticmethod
    def matches(payload: dict) -> bool:
        return isinstance(payload, dict) and isinstance(
            payload.get("alerta_meta"), dict
        )

    def parse(
        self,
        payload: dict,
        builder: BlockBuilder,
        observatory_code: str = "ALERTAS",
    ) -> ParseResult:
        result = ParseResult()
        alerta = payload.get("alerta_meta") or {}

        title = str(payload.get("title") or "").strip()
        if title:
            cleaned, _ = clean_text(title, collapse_spaces=True)
            if block := builder.add(cleaned, "heading", "structured"):
                result.blocks.append(block)

        # El tema clave es el resumen narrativo del escenario de riesgo: es contenido,
        # no metadata, y en muchas alertas es el grueso del texto útil.
        topic = normalize_value(str(alerta.get("tema_clave") or ""))
        if topic:
            if block := builder.add(topic, "paragraph", "structured"):
                result.blocks.append(block)

        for para in payload.get("body_paragraphs") or []:
            if not isinstance(para, str):
                continue
            cleaned, _ = clean_text(para, collapse_spaces=True)
            if not cleaned or cleaned == topic:
                continue
            if block := builder.add(cleaned, "paragraph", "structured"):
                result.blocks.append(block)

        municipalities = parse_municipalities(alerta.get("municipios"))
        date_iso, date_conf, date_warn = normalize_date(alerta.get("fecha_emision"))

        meta = {
            "alert_code": normalize_value(str(alerta.get("codigo") or "")) or None,
            "alert_type": normalize_value(str(alerta.get("tipo") or "")) or None,
            "date": date_iso,
            "date_confidence": date_conf,
            "key_topic": topic or None,
            "municipalities": municipalities or None,
            "departments": sorted({m["department"] for m in municipalities if m["department"]})
            or None,
            "detail_url": alerta.get("detail_url"),
            "detail_id": alerta.get("detail_id"),
            "url": payload.get("url"),
        }
        # fields / pdf_links / doc_links están vacíos en los 363: se omiten.
        meta, warns = filter_fields(meta, observatory_code)
        result.metadata = meta
        result.metadata_warnings = warns
        if date_warn:
            result.metadata_warnings.append(date_warn)

        words = sum(len(b.text.split()) for b in result.blocks)
        if words < _SHORT_DOCUMENT_WORDS:
            result.warnings.append("short_document__summary_not_full_report")

        if not meta.get("alert_code"):
            result.warnings.append("missing_alert_code__breaks_C3_crosscheck")

        return result
