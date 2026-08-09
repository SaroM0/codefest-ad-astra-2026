"""Detección de escritura Unicode.

Esto va SIEMPRE antes de cualquier heurística léxica. El corpus tiene 8 idiomas y 20 PDFs
predominantemente en escrituras no latinas (árabe, ruso, coreano, japonés, chino). Un
detector que busque `the`/`of`/`and` los marcará como corruptos — y un analizador de
calidad que los mande a cuarentena habrá perdido documentos perfectamente extraídos.
"""

from __future__ import annotations

import unicodedata

# Rangos por escritura. Se comprueban en orden; el primero que casa gana.
_RANGES: tuple[tuple[str, tuple[tuple[int, int], ...]], ...] = (
    ("latin", ((0x0041, 0x024F), (0x1E00, 0x1EFF))),
    ("greek", ((0x0370, 0x03FF), (0x1F00, 0x1FFF))),
    ("cyrillic", ((0x0400, 0x04FF), (0x0500, 0x052F))),
    ("hebrew", ((0x0590, 0x05FF),)),
    ("arabic", ((0x0600, 0x06FF), (0x0750, 0x077F), (0xFB50, 0xFDFF), (0xFE70, 0xFEFF))),
    ("devanagari", ((0x0900, 0x097F),)),
    ("thai", ((0x0E00, 0x0E7F),)),
    ("hangul", ((0x1100, 0x11FF), (0x3130, 0x318F), (0xAC00, 0xD7AF))),
    ("kana", ((0x3040, 0x309F), (0x30A0, 0x30FF))),
    ("han", ((0x4E00, 0x9FFF), (0x3400, 0x4DBF), (0xF900, 0xFAFF))),
)


def _script_of(ch: str) -> str | None:
    cp = ord(ch)
    for name, ranges in _RANGES:
        for lo, hi in ranges:
            if lo <= cp <= hi:
                return name
    return None


def script_distribution(text: str, sample: int = 200_000) -> dict[str, float]:
    """Proporción de cada escritura sobre los caracteres con letra.

    Se muestrea: para un PDF de 1.330 páginas no hace falta recorrer 4 M de caracteres
    para saber que está en inglés.
    """
    chunk = text[:sample]
    counts: dict[str, int] = {}
    total = 0
    for ch in chunk:
        if not ch.isalpha():
            continue
        name = _script_of(ch)
        if name is None:
            # Letra fuera de los rangos conocidos: se clasifica por nombre Unicode.
            try:
                name = unicodedata.name(ch).split()[0].lower()
            except ValueError:
                continue
        counts[name] = counts.get(name, 0) + 1
        total += 1

    if total == 0:
        return {}
    return {k: v / total for k, v in sorted(counts.items(), key=lambda x: -x[1])}


def dominant_script(dist: dict[str, float]) -> str | None:
    if not dist:
        return None
    # Japonés: kana + han conviven. Si hay kana significativo, la escritura es japonesa
    # aunque el han sea mayoritario (el PDF de CSIS tiene 1.022 CJK + 540 hiragana).
    if dist.get("kana", 0) >= 0.05:
        return "kana"
    return max(dist.items(), key=lambda x: x[1])[0]


def script_family(script: str | None) -> str:
    """Familia para elegir el recurso léxico de validación de calidad."""
    if script is None:
        return "unknown"
    if script in ("latin", "greek", "cyrillic"):
        return "alphabetic"
    if script in ("arabic", "hebrew"):
        return "abjad"
    if script in ("han", "kana", "hangul"):
        return "cjk"
    return "other"
