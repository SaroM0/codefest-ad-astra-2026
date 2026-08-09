"""Segmentación: texto de página → bloques tipados.

Este es el eslabón que el plan v1 no escribía. `pdftotext` no devuelve párrafos: devuelve
líneas con saltos duros. Sin este paso, cada "párrafo" es una línea suelta de ~70
caracteres y el chunker recibe confeti.

Tres rutas, en orden de preferencia:

  A. PDF etiquetado (361 de 760) → PyMuPDF `get_text("dict")` da tamaños de fuente y
     bounding boxes: se puede emitir `heading` y `table_row` con fundamento.
  B. Texto plano de poppler → reglas explícitas de unión de líneas y corte de párrafo.
  C. Fallback honesto → un bloque `page_text` por página con confianza baja.

La regla que gobierna las tres: **nunca etiquetar como `paragraph` algo que no se sabe que
lo sea**. Una mentira en el tipo se propaga a todas las capas siguientes.
"""

from __future__ import annotations

import re
import statistics
from collections import Counter

from adastra.core.models.block import BlockType, ExtractionMethod

from ..base import BlockBuilder

_BULLET = re.compile(r"^\s*([•·–—\-\*o]|\(?[a-z0-9]{1,3}[.)])\s+")
_SECTION_NUM = re.compile(r"^\s*(\d+(\.\d+)*|[IVXLC]+)[.)]?\s+\S")
_PAGE_NUMBER = re.compile(r"^\s*(page\s+)?\d{1,4}\s*$", re.IGNORECASE)
_HYPHEN_BREAK = re.compile(r"(\w{2,})-\s*$")
_SENTENCE_END = re.compile(r"[.!?:;»”\")\]]\s*$")

_SHORT_LINE = 55
_MIN_HEADING_WORDS = 1
_MAX_HEADING_WORDS = 14


# ---------------------------------------------------------------------------------
# Ruta B — texto plano
# ---------------------------------------------------------------------------------
def _looks_heading(line: str, next_line: str | None, at_block_start: bool) -> bool:
    """Encabezado en texto plano, con criterio ESTRICTO.

    Un criterio laxo produce miles de falsos encabezados: la primera versión marcaba
    1.304 headings en un informe de ESA y 1.257 en el AI Index chino, simplemente porque
    cualquier línea corta que precede a una larga los disparaba. Un tipo inflado es peor
    que un tipo genérico, porque las capas siguientes se lo creen.

    Se exige que el encabezado ABRA un bloque (venga tras línea en blanco) más una señal
    positiva: numeración de sección o mayúsculas dominantes.
    """
    stripped = line.strip()
    if not stripped or len(stripped) > 100:
        return False
    words = stripped.split()
    if not (_MIN_HEADING_WORDS <= len(words) <= _MAX_HEADING_WORDS):
        return False

    # La numeración de sección es señal suficiente por sí sola.
    if _SECTION_NUM.match(stripped) and len(stripped) <= _SHORT_LINE:
        return True

    # El resto exige abrir bloque: si viene en mitad de un párrafo, es una línea normal.
    if not at_block_start:
        return False
    if _SENTENCE_END.search(stripped):
        return False

    letters = [c for c in stripped if c.isalpha()]
    if len(letters) < 3:
        return False

    # Mayúsculas dominantes: la señal más fiable en texto sin información de fuente.
    if sum(1 for c in letters if c.isupper()) / len(letters) > 0.75:
        return True

    # Título capitalizado, corto, seguido del párrafo que encabeza.
    if (
        next_line
        and len(next_line.strip()) > _SHORT_LINE
        and stripped[0].isupper()
        and len(stripped) <= _SHORT_LINE
        and sum(1 for w in words if w[:1].isupper()) / len(words) >= 0.6
    ):
        return True

    return False


def _join_lines(lines: list[str]) -> str:
    """Une líneas de un párrafo resolviendo guiones de corte."""
    out: list[str] = []
    for line in lines:
        piece = line.strip()
        if not piece:
            continue
        if out and (match := _HYPHEN_BREAK.search(out[-1])):
            # `infraestruc-` + `tura` → `infraestructura`. Se elimina el guion sólo si
            # la parte previa tiene ≥2 caracteres (evita romper guiones legítimos).
            out[-1] = out[-1][: match.start(1) + len(match.group(1))]
            out[-1] += piece
            continue
        out.append(piece if not out else " " + piece)
    return "".join(out).strip()


def segment_plain_text(
    text: str,
    page: int,
    builder: BlockBuilder,
    method: ExtractionMethod,
    boilerplate: frozenset[str],
    *,
    tabular: bool = False,
) -> list:
    """Ruta B. Devuelve la lista de bloques de una página."""
    blocks = []

    if tabular:
        # En una página tabular la alineación por espacios ES la información: se emite
        # como un bloque `table_text` sin trocear, para no destruir la relación
        # fila↔cabecera antes de que el chunker pueda verla.
        cleaned = text.strip("\n")
        if cleaned.strip():
            if block := builder.add(
                cleaned,
                "table_text",
                method,
                page=page,
                is_boilerplate=False,
                segmentation_confidence=0.7,
            ):
                blocks.append(block)
        return blocks

    lines = text.split("\n")
    buffer: list[str] = []

    def flush(block_type: BlockType = "paragraph", confidence: float = 0.8):
        if not buffer:
            return
        joined = _join_lines(buffer)
        buffer.clear()
        if not joined:
            return
        if block := builder.add(
            joined,
            block_type,
            method,
            page=page,
            is_boilerplate=joined.strip() in boilerplate,
            segmentation_confidence=confidence,
        ):
            blocks.append(block)

    for i, raw in enumerate(lines):
        line = raw.rstrip()
        stripped = line.strip()
        nxt = lines[i + 1] if i + 1 < len(lines) else None

        if not stripped:
            flush()
            continue

        # Números de página y cabeceras/pies repetidos: se MARCAN, no se eliminan.
        # En las 47 Alertas OCRizadas el encabezado repetido contiene el código de
        # alerta, que es lo que permite el emparejamiento con los JSON (contraste C3).
        if _PAGE_NUMBER.match(stripped) or stripped in boilerplate:
            flush()
            if block := builder.add(
                stripped,
                "caption",
                method,
                page=page,
                is_boilerplate=True,
                segmentation_confidence=0.9,
            ):
                blocks.append(block)
            continue

        if _BULLET.match(line):
            flush()
            buffer.append(line)
            flush("list_item", 0.75)
            continue

        # `at_block_start`: el buffer está vacío, es decir, la línea abre bloque tras
        # una línea en blanco. Es la señal estructural más fuerte disponible en texto
        # plano y la que evita marcar como encabezado la última línea de un párrafo.
        if _looks_heading(line, nxt, at_block_start=not buffer):
            flush()
            buffer.append(line)
            flush("heading", 0.6)
            continue

        buffer.append(line)

        # Corte de párrafo: línea corta que cierra frase y siguiente que empieza en
        # mayúscula → final de párrafo.
        if (
            len(stripped) < _SHORT_LINE
            and _SENTENCE_END.search(stripped)
            and nxt
            and nxt.strip()
            and nxt.strip()[0].isupper()
        ):
            flush()

    flush()
    return blocks


# ---------------------------------------------------------------------------------
# Ruta A — PDF etiquetado
# ---------------------------------------------------------------------------------
def segment_tagged_page(
    page,
    page_number: int,
    builder: BlockBuilder,
    boilerplate: frozenset[str],
) -> list:
    """Ruta A: usa tamaños de fuente y bounding boxes de PyMuPDF.

    PyMuPDF ya devuelve bloques en orden de lectura, así que esta ruta evita el problema
    del multicolumna por construcción — y además permite tipar `heading` con fundamento
    en vez de por heurística de mayúsculas.
    """
    blocks = []
    try:
        data = page.get_text("dict")
    except Exception:
        return blocks

    raw_blocks = [b for b in data.get("blocks", []) if b.get("type") == 0]
    if not raw_blocks:
        return blocks

    # Tamaño de fuente modal de la página = el del cuerpo de texto.
    sizes: list[float] = []
    for b in raw_blocks:
        for line in b.get("lines", []):
            for span in line.get("spans", []):
                if span.get("text", "").strip():
                    sizes.append(round(float(span.get("size", 0)), 1))
    if not sizes:
        return blocks
    body_size = Counter(sizes).most_common(1)[0][0]
    max_size = max(sizes)

    for b in raw_blocks:
        lines_text: list[str] = []
        block_sizes: list[float] = []
        for line in b.get("lines", []):
            piece = "".join(span.get("text", "") for span in line.get("spans", []))
            if piece.strip():
                lines_text.append(piece)
            for span in line.get("spans", []):
                if span.get("text", "").strip():
                    block_sizes.append(float(span.get("size", 0)))

        if not lines_text:
            continue

        text = _join_lines(lines_text)
        if not text:
            continue

        avg_size = statistics.mean(block_sizes) if block_sizes else body_size
        bbox = tuple(round(float(v), 2) for v in b.get("bbox", (0, 0, 0, 0)))

        block_type: BlockType = "paragraph"
        confidence = 0.9
        # Encabezado: fuente sensiblemente mayor que el cuerpo y bloque corto.
        if avg_size >= body_size * 1.15 and len(text.split()) <= _MAX_HEADING_WORDS:
            block_type = "heading"
            confidence = 0.95 if avg_size >= max_size * 0.9 else 0.85
        elif _BULLET.match(lines_text[0]):
            block_type = "list_item"
            confidence = 0.85
        elif _PAGE_NUMBER.match(text.strip()):
            block_type = "caption"

        if block := builder.add(
            text,
            block_type,
            "native_tagged",
            page=page_number,
            bbox=bbox if len(bbox) == 4 else None,
            is_boilerplate=text.strip() in boilerplate
            or bool(_PAGE_NUMBER.match(text.strip())),
            segmentation_confidence=confidence,
        ):
            blocks.append(block)

    return blocks


# ---------------------------------------------------------------------------------
# Boilerplate: se detecta, se MARCA, jamás se elimina
# ---------------------------------------------------------------------------------
def detect_boilerplate(pages: list[str], min_pages: int = 4) -> frozenset[str]:
    """Líneas que se repiten en la mayoría de páginas: cabeceras, pies, marcas de agua.

    Se devuelven para MARCARLAS. Eliminarlas borraría el código de alerta del encabezado
    de las Alertas Tempranas — el dato que hace posible el contraste C3.
    """
    if len(pages) < min_pages:
        return frozenset()

    counts: Counter[str] = Counter()
    for text in pages:
        seen = set()
        for line in text.split("\n"):
            stripped = line.strip()
            if 3 <= len(stripped) <= 120 and stripped not in seen:
                seen.add(stripped)
                counts[stripped] += 1

    threshold = max(min_pages, int(len(pages) * 0.6))
    return frozenset(
        line
        for line, n in counts.items()
        if n >= threshold and not _PAGE_NUMBER.match(line)
    )
