"""Agregación a `ExtractionConfidence`.

Sustituye al `quality_score: float` opaco. Un 0.94 sin procedencia no es accionable; un
objeto que dice qué señales lo produjeron y qué contraste lo respalda, sí.

Dos principios:
  · los CONTRASTES mandan sobre las señales intrínsecas — una señal dice si el texto
    parece sano, un contraste dice si es el texto correcto;
  · cuando nada pudo comprobarse, se declara `unverified`. No se esconde.
"""

from __future__ import annotations

import statistics
from collections import defaultdict

from adastra.core.models.quality import (
    ConfidenceBasis,
    CrossCheck,
    ExtractionConfidence,
    SignalValue,
)

# Prioridad del `basis`: qué evidencia respalda la confianza publicada.
_BASIS_PRIORITY: tuple[tuple[str, ConfidenceBasis], ...] = (
    ("entity_crosscheck", "entity_crosscheck"),
    ("gold_fragment", "gold_fragment"),
    ("ocr_agreement", "ocr_agreement"),
    ("mirror_match", "mirror_match"),
    ("title_match", "title_match"),
)

# Cuánto puede mover cada contraste la confianza final.
_CROSSCHECK_WEIGHT = {
    "entity_crosscheck": 0.55,
    "gold_fragment": 0.55,
    "ocr_agreement": 0.45,
    "mirror_match": 0.50,
    "title_match": 0.30,
}


class SignalCalibrator:
    """Calibra señales por percentil dentro de su grupo (observatorio × escritura).

    Nada de constantes globales: un PDF de UNOOSA en árabe y una alerta OCRizada no
    comparten distribución de `average_word_length`. Lo que importa es si un documento es
    atípico *respecto a sus pares*, no respecto a un número inventado.
    """

    def __init__(self) -> None:
        self._values: dict[tuple[str, str, str], list[float]] = defaultdict(list)

    def observe(
        self, observatory: str, script: str | None, signals: dict[str, float]
    ) -> None:
        for name, value in signals.items():
            self._values[(observatory, script or "unknown", name)].append(value)

    def percentile(
        self, observatory: str, script: str | None, name: str, value: float
    ) -> float | None:
        population = self._values.get((observatory, script or "unknown", name))
        if not population or len(population) < 8:
            return None  # muestra insuficiente: mejor no calibrar que calibrar mal
        below = sum(1 for v in population if v < value)
        return round(below / len(population), 4)

    def group_sizes(self) -> dict[str, int]:
        sizes: dict[str, int] = {}
        for (obs, script, name), values in self._values.items():
            if name == "known_word_ratio":
                sizes[f"{obs}/{script}"] = len(values)
        return sizes


def _intrinsic_score(signals: dict[str, float], script: str | None) -> float:
    """Puntuación base a partir de las señales intrínsecas. [0,1]."""
    known = signals.get("known_word_ratio", 0.5)
    printable = signals.get("printable_ratio", 1.0)
    distribution = signals.get("char_distribution", 0.5)
    single_char = signals.get("single_char_token_ratio", 0.0)
    repetition = signals.get("repetition_ratio", 0.0)

    # `known_word_ratio` tiene escalas distintas por familia de escritura: en latinas un
    # 0,30 es excelente (las palabras funcionales son ~30% del texto); en CJK mide
    # proporción de caracteres en rango y lo esperable es ~0,95.
    if script in ("han", "kana", "hangul", "arabic", "hebrew"):
        known_component = min(known / 0.85, 1.0)
    else:
        known_component = min(known / 0.28, 1.0)

    score = (
        0.40 * known_component
        + 0.20 * min(printable / 0.99, 1.0)
        + 0.20 * distribution
        + 0.10 * (1.0 - min(single_char / 0.5, 1.0))
        + 0.10 * (1.0 - min(repetition, 1.0))
    )
    return max(0.0, min(1.0, score))


def build_confidence(
    signals: dict[str, float],
    crosschecks: list[CrossCheck],
    *,
    observatory: str,
    script: str | None,
    calibrator: SignalCalibrator | None = None,
    extra_flags: list[str] | None = None,
) -> ExtractionConfidence:
    flags = list(extra_flags or [])

    calibrated: dict[str, SignalValue] = {}
    for name, value in signals.items():
        pct = (
            calibrator.percentile(observatory, script, name, value)
            if calibrator
            else None
        )
        flag = None
        if pct is not None and pct <= 0.05 and name in (
            "known_word_ratio",
            "char_distribution",
            "printable_ratio",
        ):
            flag = "outlier_low_in_source"
            flags.append(f"{name}_outlier_in_{observatory}")
        calibrated[name] = SignalValue(
            value=round(value, 4), pctile_in_source=pct, flag=flag
        )

    base = _intrinsic_score(signals, script)

    # Los contrastes mandan: mueven la confianza hacia su propio veredicto.
    basis: ConfidenceBasis = "intrinsic_only"
    by_type = {c.type: c for c in crosschecks}
    for key, candidate_basis in _BASIS_PRIORITY:
        if key in by_type:
            basis = candidate_basis
            break

    score = base
    if crosschecks:
        weighted: list[tuple[float, float]] = []
        for check in crosschecks:
            weight = _CROSSCHECK_WEIGHT.get(check.type, 0.3)
            weighted.append((weight, check.score if check.score is not None else 0.0))
            if not check.passed:
                flags.append(f"crosscheck_failed:{check.type}")
        total_weight = sum(w for w, _ in weighted)
        crosscheck_score = sum(w * s for w, s in weighted) / total_weight
        # La confianza publicada mezcla lo intrínseco con lo contrastado, dando más peso
        # a lo segundo cuanto más fuerte es el contraste.
        alpha = min(0.7, total_weight)
        score = (1 - alpha) * base + alpha * crosscheck_score

    if not signals.get("characters"):
        basis = "unverified"
        score = 0.0
        flags.append("no_text_extracted")

    return ExtractionConfidence(
        score=round(max(0.0, min(1.0, score)), 4),
        basis=basis,
        signals=calibrated,
        crosschecks=crosschecks,
        flags=sorted(set(flags)),
    )


def summarize_scores(scores: list[float]) -> dict[str, float]:
    if not scores:
        return {}
    ordered = sorted(scores)
    return {
        "n": len(ordered),
        "min": round(ordered[0], 4),
        "p25": round(ordered[len(ordered) // 4], 4),
        "median": round(statistics.median(ordered), 4),
        "p75": round(ordered[3 * len(ordered) // 4], 4),
        "max": round(ordered[-1], 4),
        "mean": round(statistics.fmean(ordered), 4),
    }
