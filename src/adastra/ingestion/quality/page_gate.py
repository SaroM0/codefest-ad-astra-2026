"""Decisión de calidad POR PÁGINA y router de OCR.

La decisión se toma página a página, no documento a documento. Eso hace que los 11 PDFs
mixtos y los 6 falsos positivos del muestreo de primeras páginas dejen de ser casos
especiales: son el caso general.

Se rechaza `chars/page < 50` como criterio único — ese umbral aprobaría el CEOBS-Sudán
(2.187 c/pág de basura) y suspendería páginas legítimamente cortas.
"""

from __future__ import annotations

from adastra.core.models.quality import PageQuality

from .. import config
from .signals import compute_signals


def evaluate_page(
    page_number: int,
    text: str,
    image_coverage: float,
    language: str | None,
    script: str | None,
) -> PageQuality:
    signals = compute_signals(text, language, script)
    chars = len(text.strip())
    reasons: list[str] = []

    # --- página vacía o casi -----------------------------------------------------
    if chars < config.PAGE_EMPTY_MAX_CHARS:
        if image_coverage >= config.IMAGE_COVERAGE_THRESHOLD:
            reasons.append(f"image_page__coverage_{image_coverage:.2f}")
            verdict = "ocr"
        elif chars == 0:
            reasons.append("empty_page__no_text_no_image")
            # Una página en blanco es legítima (separadores, reversos). No es un fallo
            # y no merece OCR: se acepta vacía y se registra.
            verdict = "accept"
        else:
            reasons.append(f"very_low_text__{chars}_chars")
            verdict = "ocr" if image_coverage > 0.2 else "accept"
        return PageQuality(
            page_number=page_number,
            verdict=verdict,
            reasons=reasons,
            signals=signals,
            characters=chars,
            image_coverage=round(image_coverage, 4),
        )

    # --- texto corrupto ----------------------------------------------------------
    # Este es el caso CEOBS-Sudán: muchísimo texto que pasa cualquier filtro de longitud
    # pero cuyas señales léxicas y de distribución lo delatan.
    corrupt: list[str] = []

    # Señal 1 — ratio de imprimibles. El CEOBS-Sudán intercala \x03/\x04 entre glifos y
    # cae a ~0,86; el texto sano está en ~0,99.
    if signals["printable_ratio"] < config.MIN_PRINTABLE_RATIO:
        corrupt.append(f"low_printable_ratio_{signals['printable_ratio']}")

    # Señal 2 — distribución de caracteres. OJO: NO detecta el CEOBS-Sudán (da 1.0),
    # porque los índices de glifo son una SUSTITUCIÓN MONOALFABÉTICA del inglés real y
    # una sustitución preserva exactamente la distribución de frecuencias. Sirve para
    # binario colado y para repetición patológica, no para cifrado por sustitución.
    if signals["char_distribution"] < config.MIN_CHAR_DISTRIBUTION_SCORE:
        corrupt.append(f"anomalous_char_distribution_{signals['char_distribution']}")

    # Señal 3 — léxico. Es la que SÍ caza el CEOBS-Sudán, en sus dos manifestaciones:
    #   (a) se detecta idioma pero apenas hay palabras funcionales (pág. 100: 0,041);
    #   (b) NO se detecta idioma pese a haber escritura latina y texto abundante
    #       (pág. 40: 1.552 caracteres, script latino, lang=None).
    # La v1 exigía `language is not None`, que exentaba justo el caso (b) — el peor.
    if script == "latin" and chars > 500:
        if language is None:
            corrupt.append("latin_script_but_no_language_detected")
        elif signals["known_word_ratio"] < config.MIN_KNOWN_WORD_RATIO_LATIN:
            corrupt.append(f"low_known_word_ratio_{signals['known_word_ratio']}")

    # Señal 4 — espaciado roto.
    if signals["single_char_token_ratio"] > 0.45 and chars > 300:
        corrupt.append(f"broken_spacing_{signals['single_char_token_ratio']}")

    # Algunas señales bastan POR SÍ SOLAS porque no tienen explicación benigna.
    # Es imprescindible: tras la limpieza de caracteres de control, el CEOBS-Sudán deja
    # de disparar `printable_ratio` (los \x03 se eliminan y sube a 1,0) y la
    # distribución de caracteres nunca lo dispara. Si se exigieran dos señales, las 176
    # páginas ilegibles se aceptarían como buenas.
    decisive = [
        r
        for r in corrupt
        if r.startswith("latin_script_but_no_language_detected")
        or (
            r.startswith("low_known_word_ratio")
            and signals["known_word_ratio"] < 0.10
            and chars > 800
        )
    ]

    # Dos señales independientes, o una decisiva → corrupción. Una sola no decisiva
    # puede ser un artefacto legítimo (una página de tabla numérica tiene pocas
    # palabras funcionales).
    if len(corrupt) >= 2 or decisive:
        return PageQuality(
            page_number=page_number,
            verdict="ocr",
            reasons=["corrupt_text"] + corrupt,
            signals=signals,
            characters=chars,
            image_coverage=round(image_coverage, 4),
        )
    if corrupt:
        reasons.extend(corrupt)
        reasons.append("single_signal_only__accepted_with_flag")

    # --- texto sano (con o sin imágenes) -----------------------------------------
    if chars < config.PAGE_LOW_TEXT_MAX_CHARS and image_coverage > 0.4:
        reasons.append(f"low_text_with_images__{chars}_chars")
        verdict = "ocr"
    else:
        verdict = "accept"

    return PageQuality(
        page_number=page_number,
        verdict=verdict,
        reasons=reasons,
        signals=signals,
        characters=chars,
        image_coverage=round(image_coverage, 4),
    )
