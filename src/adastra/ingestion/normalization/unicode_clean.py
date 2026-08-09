"""Normalización de texto — MÍNIMA.

Sólo se corrige lo que es inequívocamente corrupción de transporte. Nada de paráfrasis,
traducción, resumen, corrección gramatical ni reescritura con LLM (invariante I9): el reto
exige citar evidencia, y un texto reescrito ya no es evidencia.
"""

from __future__ import annotations

import re
import unicodedata

# Espacios "duros" que `str.strip()` NO elimina. Hay 4.561 NBSP en 13 CSV del corpus,
# concentrados en la columna `Age` de ClinicalTrials.
_SPACE_LIKE = {
    " ",  # NBSP
    " ",  # figure space
    " ",  # narrow NBSP
    "⁠",  # word joiner
    "﻿",  # BOM / ZWNBSP
}

# U+2028 (LS) y U+2029 (PS) rompen `str.splitlines()`: en 4 CSV de PubMed convierten
# 111.775 filas en 111.777 con 4 desalineadas. Se normalizan a salto de línea.
_LINE_SEPARATORS = {" ", " "}

_CONTROL_KEEP = {"\n", "\t"}

_MULTI_SPACE = re.compile(r"[ \t]{2,}")
_MULTI_NEWLINE = re.compile(r"\n{3,}")


def strip_nul(text: str) -> tuple[str, int]:
    """Elimina bytes NUL. Los 6 informes ESA traen hasta 38.337 por archivo.

    Verificado: tras quitarlos el texto es correcto (6.207 palabras funcionales inglesas
    en `i9r0`). No es mojibake y no requiere OCR.
    """
    n = text.count("\x00")
    return (text.replace("\x00", ""), n) if n else (text, 0)


def clean_text(text: str, collapse_spaces: bool = False) -> tuple[str, dict[str, int]]:
    """Limpieza mínima. Devuelve el texto y el recuento de lo corregido."""
    stats = {"nul": 0, "control": 0, "nbsp": 0, "line_sep": 0}

    text, stats["nul"] = strip_nul(text)

    out: list[str] = []
    for ch in text:
        if ch in _SPACE_LIKE:
            out.append(" ")
            stats["nbsp"] += 1
            continue
        if ch in _LINE_SEPARATORS:
            out.append("\n")
            stats["line_sep"] += 1
            continue
        if ch in _CONTROL_KEEP:
            out.append(ch)
            continue
        if ch == "\r":
            out.append("\n")
            continue
        # \f (form feed) se DESCARTA como separador visual, pero jamás se usa para
        # paginar: 6 informes ESA tienen form feeds espurios y partir por \f infla el
        # recuento del corpus en +955 páginas (invariante I5).
        if ch == "\f":
            out.append("\n")
            continue
        if unicodedata.category(ch) in ("Cc", "Cf", "Co", "Cs"):
            stats["control"] += 1
            continue
        out.append(ch)

    text = "".join(out)

    if collapse_spaces:
        # Sólo para prosa. NUNCA sobre texto tabular: la alineación por espacios ES la
        # información en las páginas maquetadas como tabla.
        text = _MULTI_SPACE.sub(" ", text)

    text = _MULTI_NEWLINE.sub("\n\n", text)
    return text.strip(), stats


def normalize_value(value: str) -> str:
    """Normalización de un valor de celda tabular: NBSP primero, strip después."""
    for ch in _SPACE_LIKE:
        value = value.replace(ch, " ")
    return value.strip()
