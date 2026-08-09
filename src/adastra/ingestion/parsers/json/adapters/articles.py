"""Familia A — artículo web scrapeado (485 archivos, 7 fuentes).

Núcleo común: `url`, `title`, `date`, `body_paragraphs` y `body_text`.
`body_text` es la concatenación de `body_paragraphs` con `\\n\\n`: son representaciones
redundantes y sólo se conserva la lista, que además ya viene segmentada en párrafos.

Los metadatos (url, date, authors, topics) NO se incorporan al texto: quedan como
metadata salvo que más adelante se decida explícitamente enriquecer.
"""

from __future__ import annotations

from .... import config
from ....normalization.metadata import clean_authors, filter_fields, normalize_date
from ....normalization.unicode_clean import clean_text
from ...base import BlockBuilder, ParseResult

_TEXT_FIELDS = ("body_paragraphs", "paragraphs", "content")


class ArticleAdapter:
    """Adapter de artículo web. Las particularidades por fuente van en config."""

    name = "web_article"

    @staticmethod
    def matches(payload: dict) -> bool:
        if not isinstance(payload, dict):
            return False
        has_text = any(isinstance(payload.get(f), list) for f in _TEXT_FIELDS)
        return has_text and ("title" in payload or "url" in payload)

    def parse(
        self,
        payload: dict,
        builder: BlockBuilder,
        observatory_code: str,
    ) -> ParseResult:
        result = ParseResult()

        title = str(payload.get("title") or "").strip()
        if title:
            cleaned, _ = clean_text(title, collapse_spaces=True)
            if block := builder.add(cleaned, "heading", "structured"):
                result.blocks.append(block)

        paragraphs: list = []
        for field in _TEXT_FIELDS:
            value = payload.get(field)
            if isinstance(value, list) and value:
                paragraphs = value
                break

        for para in paragraphs:
            if not isinstance(para, str):
                continue
            cleaned, _ = clean_text(para, collapse_spaces=True)
            if not cleaned:
                continue
            if block := builder.add(cleaned, "paragraph", "structured"):
                result.blocks.append(block)

        # `excerpt` sólo se emite si no duplica el primer párrafo.
        excerpt = str(payload.get("excerpt") or "").strip()
        if excerpt and not any(excerpt[:60] in b.text for b in result.blocks):
            cleaned, _ = clean_text(excerpt, collapse_spaces=True)
            if block := builder.add(cleaned, "caption", "structured"):
                result.blocks.append(block)

        # --- metadata -------------------------------------------------------------
        authors, dropped = clean_authors(payload.get("authors"))
        date_iso, date_conf, date_warn = normalize_date(payload.get("date"))

        meta = {
            "url": payload.get("url"),
            "title": title or None,
            "authors": authors or None,
            "topics": payload.get("topics") or payload.get("categories") or None,
            "date_raw": payload.get("date"),
            "date": date_iso,
            "date_confidence": date_conf,
            "pdf_links": payload.get("pdf_links") or None,
            "science_links": payload.get("science_links") or None,
        }
        meta, warns = filter_fields(meta, observatory_code)
        result.metadata = meta
        result.metadata_warnings = warns + [f"dropped_author:{d}" for d in dropped]
        if date_warn:
            result.metadata_warnings.append(date_warn)

        # CSIS tiene body_text de 60 a 297.739 caracteres; los de ~60 son placeholders
        # sin contenido, no fallos de extracción. Se marcan para que el gate decida.
        if result.characters and result.characters < config.PLACEHOLDER_MAX_CHARS:
            result.warnings.append("possible_placeholder__body_too_short")

        return result
