"""Familia E — artículo de revista académica (CEEEP, 80 archivos).

Revista peruana *Seguridad y Poder Terrestre*. Esquema propio: `abstract`, `keywords`,
`doi`, `issue`, `pdf_url`. No hay cuerpo completo — el abstract ES el contenido
recuperable, y hay que decirlo explícitamente para que la capa de calidad no lo interprete
como una extracción truncada.

La fecha es sólo el año (`"2024"`), lo que da `date_confidence = "inferred"`.
"""

from __future__ import annotations

from ....normalization.metadata import clean_authors, filter_fields, normalize_date
from ....normalization.unicode_clean import clean_text, normalize_value
from ...base import BlockBuilder, ParseResult


class JournalAdapter:
    name = "journal_article"

    @staticmethod
    def matches(payload: dict) -> bool:
        if not isinstance(payload, dict):
            return False
        return "abstract" in payload and ("doi" in payload or "issue" in payload)

    def parse(
        self,
        payload: dict,
        builder: BlockBuilder,
        observatory_code: str = "CEEEP",
    ) -> ParseResult:
        result = ParseResult()

        title = str(payload.get("title") or "").strip()
        if title:
            cleaned, _ = clean_text(title, collapse_spaces=True)
            if block := builder.add(cleaned, "heading", "structured"):
                result.blocks.append(block)

        abstract = str(payload.get("abstract") or "").strip()
        if abstract:
            cleaned, _ = clean_text(abstract, collapse_spaces=True)
            if block := builder.add(cleaned, "paragraph", "structured"):
                result.blocks.append(block)

        authors, dropped = clean_authors(payload.get("authors"))
        date_iso, date_conf, date_warn = normalize_date(payload.get("date"))

        keywords = payload.get("keywords")
        if isinstance(keywords, str):
            keywords = [normalize_value(k) for k in keywords.split(",") if k.strip()]

        meta = {
            "url": payload.get("url"),
            "title": title or None,
            "authors": authors or None,
            "date": date_iso,
            "date_confidence": date_conf,
            "date_raw": payload.get("date"),
            "doi": payload.get("doi"),
            "issue": payload.get("issue"),
            "keywords": keywords or None,
            "pdf_url": payload.get("pdf_url"),
        }
        meta, warns = filter_fields(meta, observatory_code)
        result.metadata = meta
        result.metadata_warnings = warns + [f"dropped_author:{d}" for d in dropped]
        if date_warn:
            result.metadata_warnings.append(date_warn)

        # El texto recuperable es SÓLO el abstract: no es una extracción truncada, es lo
        # que la fuente publica. Se declara para que el gate de calidad no lo penalice.
        result.warnings.append("abstract_only__full_text_not_in_corpus")

        return result
