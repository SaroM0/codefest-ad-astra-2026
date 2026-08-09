"""Elección del modo de extracción POR PÁGINA.

Corrige una regla que los planes previos daban por
"no negociable" y que está invertida:

    `pdftotext -layout` NO arregla el multicolumna: lo provoca.

El modo por defecto de poppler SÍ hace análisis de layout y emite orden de lectura;
`-layout` preserva posiciones FÍSICAS, así que en una página a dos columnas ambas
columnas quedan lado a lado en la misma línea de salida y al leerla linealmente se
intercalan. Verificado en `CSET_center-for-security-and-emerging-technology-2.pdf` p.5:

    DEFAULT : "As CSET enters its seventh year, I am struck by / how far we've come..."
    -layout : "As CSET enters its seventh year, I am struck by    best and most uniquely
               hard-hitting defense AI"

Y el efecto depende de la PÁGINA, no del documento: en SWF-2026 y AI-Index-2025 el 15% de
las líneas largas de la salida `-layout` presentan hueco columnar; en otras páginas del
mismo PDF, 0%. Una regla global falla en ambas direcciones.

Solución: extraer de las dos formas y puntuar ambas con la MISMA métrica de continuidad
lingüística, registrando ambos scores y el margen. `-layout` se conserva a propósito para
páginas tabulares, donde la alineación física ES la información.
"""

from __future__ import annotations

import re
from collections import Counter

from ... import config
from ...language.detector import STOPWORDS, tokenize
from ...language.scripts import script_family

_COLUMN_GAP = re.compile(r"\S {" + str(config.COLUMN_GAP_MIN_SPACES) + r",}\S")
_HYPHEN_BREAK = re.compile(r"(\w+)-\n(\w+)")
_SENTENCE_END = re.compile(r"[.!?:;]\s*$")


def columnar_gap_ratio(text: str) -> float:
    """Fracción de líneas largas con un hueco central de ≥8 espacios.

    Es la firma de dos columnas puestas lado a lado por `-layout`… y también la de una
    tabla. Distinguirlas es el trabajo de `looks_tabular`.
    """
    lines = [
        line
        for line in text.split("\n")
        if len(line.strip()) > config.COLUMN_GAP_MIN_LINE_LEN
    ]
    if not lines:
        return 0.0
    return sum(1 for line in lines if _COLUMN_GAP.search(line)) / len(lines)


def indentation_clusters(text: str) -> tuple[float, int]:
    """Detecta multicolumna por SANGRÍA BIMODAL, no por hueco interno.

    En la salida `-layout` de una página a dos columnas, cada línea contiene texto de UNA
    sola columna, rellenada con espacios a la izquierda si es la columna derecha:

        Letter from the Executive Director
                                              industry leaders, philanthropists, and
                                              policymakers, recognizing that technological
        As CSET enters its seventh year...

    No hay ningún `\\S␣␣␣␣␣␣␣␣\\S` que detectar: la firma es que las líneas arrancan en
    dos posiciones muy distintas y van alternándose. Devuelve (masa de la 2ª moda,
    nº de alternancias).
    """
    starts: list[int] = []
    for line in text.split("\n"):
        if len(line.strip()) < 20:
            continue
        starts.append(len(line) - len(line.lstrip()))

    if len(starts) < 6:
        return 0.0, 0

    # Se agrupa en bloques de 6 columnas para absorber ruido de kerning.
    buckets = Counter(s // 6 for s in starts)
    if len(buckets) < 2:
        return 0.0, 0

    ordered = buckets.most_common()
    first_bucket, first_n = ordered[0]
    second_bucket, second_n = ordered[1]

    # Las dos modas deben estar realmente separadas (≥ 4 buckets ≈ 24 caracteres).
    if abs(first_bucket - second_bucket) < 4:
        return 0.0, 0

    second_mass = second_n / len(starts)

    # Alternancia: cuántas veces se salta de una moda a la otra en líneas consecutivas.
    alternations = 0
    prev: int | None = None
    for s in starts:
        b = s // 6
        current = 0 if b == first_bucket else (1 if b == second_bucket else None)
        if current is None:
            continue
        if prev is not None and current != prev:
            alternations += 1
        prev = current

    return round(second_mass, 4), alternations


def looks_multicolumn(text: str) -> bool:
    """Dos columnas puestas lado a lado: sangría bimodal Y alternancia real.

    Exigir alternancia evita confundirlo con una cita larga sangrada o con un bloque de
    código, que también tienen sangría bimodal pero no alternan.
    """
    mass, alternations = indentation_clusters(text)
    return mass >= 0.15 and alternations >= 4


def looks_tabular(text: str) -> bool:
    """Tabla vs dos columnas: en una tabla los huecos se ALINEAN entre líneas.

    En texto a dos columnas el hueco cae donde termina cada línea de la columna
    izquierda, es decir, en posiciones distintas. En una tabla las columnas empiezan
    siempre en la misma posición.
    """
    lines = [
        line
        for line in text.split("\n")
        if len(line.strip()) > config.COLUMN_GAP_MIN_LINE_LEN
    ]
    if len(lines) < 4:
        return False

    gap_starts: dict[int, int] = {}
    with_gap = 0
    for line in lines:
        match = _COLUMN_GAP.search(line)
        if not match:
            continue
        with_gap += 1
        # Se redondea a bloques de 4 columnas para absorber ruido de kerning.
        bucket = (match.start() + 1) // 4
        gap_starts[bucket] = gap_starts.get(bucket, 0) + 1

    if with_gap / len(lines) < config.TABULAR_GAP_RATIO:
        return False
    if not gap_starts:
        return False

    # Si más de la mitad de los huecos caen en el mismo bucket, es una tabla.
    return max(gap_starts.values()) / with_gap >= 0.5


def reading_continuity(text: str, language: str | None, script: str | None) -> float:
    """Puntúa la coherencia del orden de lectura. Mismo criterio para ambos candidatos.

    Tres señales, todas baratas y deterministas:
      1. proporción de palabras funcionales del idioma (el texto intercalado las conserva,
         pero rompe su distribución entre líneas contiguas);
      2. guiones de corte de línea que se resuelven a palabra conocida;
      3. penalización por líneas que empiezan en minúscula tras una línea terminada en
         punto — la firma del intercalado de columnas.
    """
    if not text.strip():
        return 0.0

    family = script_family(script)
    if family != "alphabetic" or language not in STOPWORDS:
        # Sin léxico aplicable (CJK, árabe): sólo se usa la continuidad estructural.
        return _structural_continuity(text)

    stop = STOPWORDS[language]
    tokens = tokenize(text, limit=20_000)
    if len(tokens) < 20:
        return _structural_continuity(text)

    stop_ratio = sum(1 for t in tokens if t in stop) / len(tokens)

    # Guiones de corte: en el modo correcto, `infraestruc-\ntura` se recompone a una
    # palabra real. En el intercalado, casi nunca.
    joins = _HYPHEN_BREAK.findall(text[:20_000])
    hyphen_score = 0.5
    if joins:
        resolved = sum(1 for a, b in joins if (a + b).lower() in stop or len(a + b) > 5)
        hyphen_score = resolved / len(joins)

    return round(
        0.55 * min(stop_ratio / 0.30, 1.0)
        + 0.15 * hyphen_score
        + 0.30 * _structural_continuity(text),
        4,
    )


def _structural_continuity(text: str) -> float:
    """Fracción de saltos de línea que NO parecen una discontinuidad de lectura."""
    lines = [line.rstrip() for line in text.split("\n") if line.strip()]
    if len(lines) < 3:
        return 0.5

    bad = 0
    for prev, cur in zip(lines, lines[1:]):
        stripped = cur.lstrip()
        if not stripped:
            continue
        starts_lower = stripped[0].islower()
        prev_ends_sentence = bool(_SENTENCE_END.search(prev))
        # Una línea que empieza en minúscula justo después de una frase cerrada es la
        # firma del salto entre columnas.
        if starts_lower and prev_ends_sentence:
            bad += 1
    return round(1.0 - bad / max(len(lines) - 1, 1), 4)


def choose(
    default_text: str,
    layout_text: str,
    language: str | None,
    script: str | None,
) -> tuple[str, str, dict[str, float], bool]:
    """Devuelve (texto elegido, método, scores, es_tabular).

    Orden de decisión (importa):
      1. ¿Tabla? → `-layout`: la alineación física ES la información.
      2. ¿Multicolumna? → modo por defecto: `-layout` intercalaría las columnas.
      3. Si no → puntuar ambos y quedarse con el mejor.

    El paso 2 va ANTES de puntuar porque la métrica de continuidad no puede distinguir
    los dos casos: en la salida `-layout` las líneas de cada columna quedan contiguas
    entre sí, así que la continuidad local parece buena aunque el orden global sea
    incorrecto.
    """
    mass, alternations = indentation_clusters(layout_text)
    base_scores = {
        "gap_ratio": round(columnar_gap_ratio(layout_text), 4),
        "indent_second_mass": mass,
        "indent_alternations": float(alternations),
    }

    if looks_tabular(layout_text):
        return (
            layout_text,
            "native_layout",
            {**base_scores, "default": 0.0, "layout": 1.0, "margin": 1.0,
             "decision": 1.0},  # 1 = tabular
            True,
        )

    if looks_multicolumn(layout_text):
        return (
            default_text,
            "native_reading_order",
            {**base_scores, "default": 1.0, "layout": 0.0, "margin": 1.0,
             "decision": 2.0},  # 2 = multicolumna detectada
            False,
        )

    score_default = reading_continuity(default_text, language, script)
    score_layout = reading_continuity(layout_text, language, script)
    scores = {
        **base_scores,
        "default": score_default,
        "layout": score_layout,
        "margin": round(abs(score_default - score_layout), 4),
        "decision": 3.0,  # 3 = decidido por puntuación
    }

    # Empate o margen despreciable → modo por defecto, que es el que respeta el orden
    # de lectura declarado por el PDF.
    if score_layout > score_default + 0.02:
        return layout_text, "native_layout", scores, False
    return default_text, "native_reading_order", scores, False
