"""Señales intrínsecas de calidad de texto.

El caso CEOBS-Sudán demuestra que muchos caracteres ≠ texto válido: 393.686 caracteres en
180 páginas, de las que 176 devuelven índices de glifo en vez de Unicode (fuente sin tabla
`ToUnicode`). Pasa cualquier filtro de longitud.

Por eso ninguna decisión se toma con una sola señal. Y por eso se añade una que el plan v1
no tenía: la **distribución de frecuencia de caracteres**, que detecta corrupción de forma
INDEPENDIENTE DEL IDIOMA. `functional-word frequency` sólo funciona en escrituras latinas;
un CEOBS-Sudán en chino se le escaparía.
"""

from __future__ import annotations

import math
import unicodedata
from collections import Counter

from ..language.detector import STOPWORDS, tokenize
from ..language.scripts import script_family

# Entropía normalizada típica del texto natural. Muy por debajo → repetición patológica;
# muy plana y alta → índices de glifo o binario interpretado como texto.
_NATURAL_ENTROPY_LO = 3.2
_NATURAL_ENTROPY_HI = 5.2


def printable_ratio(text: str) -> float:
    if not text:
        return 0.0
    ok = sum(
        1
        for c in text
        if c in "\n\t " or not unicodedata.category(c).startswith("C")
    )
    return ok / len(text)


def alphabetic_ratio(text: str) -> float:
    if not text:
        return 0.0
    return sum(1 for c in text if c.isalpha()) / len(text)


def char_distribution_score(text: str, sample: int = 50_000) -> float:
    """Cuán "natural" es la distribución de frecuencia de caracteres. [0,1].

    Señal independiente del idioma. El texto natural de cualquier escritura tiene una
    distribución muy marcada (unos pocos caracteres muy frecuentes, cola larga). Los
    índices de glifo del CEOBS-Sudán producen una distribución anómala.
    """
    chunk = [c.lower() for c in text[:sample] if c.isalpha()]
    if len(chunk) < 100:
        return 0.5  # texto insuficiente: ni confirma ni desmiente

    counts = Counter(chunk)
    total = len(chunk)
    entropy = -sum((n / total) * math.log2(n / total) for n in counts.values())

    if _NATURAL_ENTROPY_LO <= entropy <= _NATURAL_ENTROPY_HI:
        base = 1.0
    elif entropy < _NATURAL_ENTROPY_LO:
        base = max(0.0, entropy / _NATURAL_ENTROPY_LO)
    else:
        base = max(0.0, 1.0 - (entropy - _NATURAL_ENTROPY_HI) / 3.0)

    # Segunda señal: el carácter más frecuente de un texto natural concentra bastante
    # masa. En una secuencia de índices de glifo la masa está mucho más repartida.
    top_share = counts.most_common(1)[0][1] / total
    top_penalty = 1.0 if 0.05 <= top_share <= 0.30 else 0.6

    return round(base * top_penalty, 4)


def known_word_ratio(text: str, language: str | None, script: str | None) -> float:
    """Fracción de tokens reconocibles. Recurso léxico POR FAMILIA de escritura.

    Sin esta discriminación, los 20 PDFs en árabe/ruso/coreano/japonés/chino entran en
    cuarentena por construcción: no contienen `the`, `of` ni `and`.
    """
    family = script_family(script)

    if family == "cjk":
        # En CJK no hay tokens separados por espacio: se mide la proporción de
        # caracteres en rangos válidos, que es la señal equivalente.
        cjk = sum(
            1
            for c in text[:20_000]
            if 0x3040 <= ord(c) <= 0x9FFF or 0xAC00 <= ord(c) <= 0xD7AF
        )
        alpha = sum(1 for c in text[:20_000] if c.isalpha())
        return round(cjk / alpha, 4) if alpha else 0.0

    if family == "abjad":
        arabic = sum(1 for c in text[:20_000] if 0x0600 <= ord(c) <= 0x06FF)
        alpha = sum(1 for c in text[:20_000] if c.isalpha())
        return round(arabic / alpha, 4) if alpha else 0.0

    if language not in STOPWORDS:
        return 0.5  # escritura alfabética sin léxico disponible: no penalizar

    tokens = tokenize(text, limit=20_000)
    if len(tokens) < 20:
        return 0.5
    stop = STOPWORDS[language]
    return round(sum(1 for t in tokens if t in stop) / len(tokens), 4)


def average_word_length(text: str) -> float:
    tokens = tokenize(text, limit=20_000)
    if not tokens:
        return 0.0
    return round(sum(len(t) for t in tokens) / len(tokens), 3)


def single_char_token_ratio(text: str) -> float:
    """Tokens de un solo carácter: la firma del espaciado roto."""
    tokens = tokenize(text, limit=20_000)
    if not tokens:
        return 0.0
    return round(sum(1 for t in tokens if len(t) == 1) / len(tokens), 4)


def repetition_ratio(text: str) -> float:
    """Fracción de líneas duplicadas: bucles de extracción o boilerplate masivo."""
    lines = [line.strip() for line in text.split("\n") if len(line.strip()) > 15]
    if len(lines) < 5:
        return 0.0
    return round(1.0 - len(set(lines)) / len(lines), 4)


def compute_signals(
    text: str,
    language: str | None,
    script: str | None,
) -> dict[str, float]:
    """Todas las señales intrínsecas de un texto."""
    return {
        "characters": float(len(text)),
        "printable_ratio": round(printable_ratio(text), 4),
        "alphabetic_ratio": round(alphabetic_ratio(text), 4),
        "char_distribution": char_distribution_score(text),
        "known_word_ratio": known_word_ratio(text, language, script),
        "average_word_length": average_word_length(text),
        "single_char_token_ratio": single_char_token_ratio(text),
        "repetition_ratio": repetition_ratio(text),
        "nul_count": float(text.count("\x00")),
    }
