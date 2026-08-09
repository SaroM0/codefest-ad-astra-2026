"""Familia B — página institucional (CENIA, 15 archivos).

Esquema con `sections` ({heading, paragraphs}), `lists`, `links`, `pdf_links`, `images` y
el booleano `contenido_limitado`, que la propia fuente usa para marcar extracción
incompleta. Sólo 11 de 15 traen `sections` con contenido.

Que la fuente declare su propia incompletitud es información valiosa: se propaga como
warning en vez de descubrirse más tarde como "documento raro".
"""

from __future__ import annotations

from ....normalization.metadata import filter_fields
from ....normalization.unicode_clean import clean_text
from ...base import BlockBuilder, ParseResult


class CENIAAdapter:
    name = "institutional_page"

    @staticmethod
    def matches(payload: dict) -> bool:
        return isinstance(payload, dict) and (
            isinstance(payload.get("sections"), list)
            or "contenido_limitado" in payload
        )

    def parse(
        self,
        payload: dict,
        builder: BlockBuilder,
        observatory_code: str = "CENIA",
    ) -> ParseResult:
        result = ParseResult()

        title = str(payload.get("title") or "").strip()
        if title:
            cleaned, _ = clean_text(title, collapse_spaces=True)
            if block := builder.add(cleaned, "heading", "structured"):
                result.blocks.append(block)

        for section in payload.get("sections") or []:
            if not isinstance(section, dict):
                continue
            heading = str(section.get("heading") or "").strip()
            if heading:
                cleaned, _ = clean_text(heading, collapse_spaces=True)
                if block := builder.add(cleaned, "heading", "structured"):
                    result.blocks.append(block)
            for para in section.get("paragraphs") or []:
                if not isinstance(para, str):
                    continue
                cleaned, _ = clean_text(para, collapse_spaces=True)
                if not cleaned:
                    continue
                if block := builder.add(cleaned, "paragraph", "structured"):
                    result.blocks.append(block)

        for item in payload.get("lists") or []:
            entries = item if isinstance(item, list) else [item]
            for entry in entries:
                if not isinstance(entry, str):
                    continue
                cleaned, _ = clean_text(entry, collapse_spaces=True)
                if not cleaned:
                    continue
                if block := builder.add(cleaned, "list_item", "structured"):
                    result.blocks.append(block)

        meta = {
            "url": payload.get("url"),
            "title": title or None,
            "pdf_links": payload.get("pdf_links") or None,
            "content_limited": payload.get("contenido_limitado"),
        }
        meta, warns = filter_fields(meta, observatory_code)
        result.metadata = meta
        result.metadata_warnings = warns

        if payload.get("contenido_limitado"):
            result.warnings.append("source_declares_limited_content")
        if not result.blocks:
            result.warnings.append("no_extractable_text")

        return result
