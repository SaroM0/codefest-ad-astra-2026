"""Parser TXT. Un solo archivo del corpus: `SWF_full-text.txt`.

Es el único archivo que SÍ necesita limpieza agresiva de boilerplate: arrastra el menú de
navegación completo del sitio ("News & Media / About / Reports / Events…") antes del
contenido real. En todos los demás formatos el boilerplate se marca; aquí se recorta,
porque no es contenido del documento sino cromo del sitio web.
"""

from __future__ import annotations

import re
from pathlib import Path

from ..normalization.unicode_clean import clean_text
from .base import BlockBuilder, ParseResult
from .pdf.segmentation import segment_plain_text

_HEADER_FIELD = re.compile(r"^(SOURCE|SCRAPED|URL|TITLE|DATE)\s*:\s*(.+)$", re.I)

# Entradas de menú de navegación típicas del sitio de SWF.
_NAV_ITEMS = {
    "news & media", "about", "reports", "events", "publications", "home",
    "contact", "donate", "search", "menu", "skip to content", "our work",
    "resources", "staff", "careers", "newsletter", "privacy policy",
}


def parse_text(path: Path, doc_id: str, pipeline_version: str) -> ParseResult:
    raw = path.read_text(encoding="utf-8", errors="replace")
    result = ParseResult()
    builder = BlockBuilder(doc_id, pipeline_version)

    lines = raw.split("\n")
    metadata: dict = {"schema": "plain_text"}
    body_start = 0

    # Cabecera `SOURCE:` / `SCRAPED:` → metadata, no texto.
    for i, line in enumerate(lines[:20]):
        if match := _HEADER_FIELD.match(line.strip()):
            metadata[match.group(1).lower()] = match.group(2).strip()
            body_start = i + 1
        elif line.strip() and i > 0 and body_start:
            break

    # Recorte del menú: se descartan las líneas iniciales que son entradas de navegación
    # hasta encontrar la primera línea que parece prosa real.
    body = lines[body_start:]
    trimmed = 0
    while body:
        candidate = body[0].strip()
        if not candidate:
            body.pop(0)
            trimmed += 1
            continue
        if candidate.lower() in _NAV_ITEMS or (
            len(candidate) < 40 and len(candidate.split()) <= 4
        ):
            body.pop(0)
            trimmed += 1
            continue
        break

    if trimmed:
        result.warnings.append(f"site_navigation_trimmed:{trimmed}_lines")

    cleaned, _ = clean_text("\n".join(body), collapse_spaces=True)
    result.blocks = segment_plain_text(
        cleaned, page=1, builder=builder, method="structured", boilerplate=frozenset()
    )
    result.metadata = metadata
    return result
