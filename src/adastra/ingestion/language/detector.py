"""Detección de idioma condicionada por la escritura.

Pipeline: escritura Unicode → familia candidata → detector → sanity check del idioma.

Para escrituras latinas basta distinguir es/en/pt (los tres idiomas latinos del corpus)
con frecuencias de palabras funcionales. No se usa fastText: el modelo pesa 126 MB, hay
que descargarlo, y el problema aquí es de tres clases con vocabularios muy separados.
Determinista y sin dependencias es preferible.
"""

from __future__ import annotations

import re

from .scripts import dominant_script, script_distribution

_WORD_RE = re.compile(r"[^\W\d_]+", re.UNICODE)

# Palabras funcionales. Son también el recurso del `known_word_ratio` de calidad, que es
# lo que detecta el caso CEOBS-Sudán (393 K caracteres con CERO apariciones de `the`).
STOPWORDS: dict[str, frozenset[str]] = {
    "es": frozenset(
        """de la que el en y a los del se las por un para con no una su al lo como más
        pero sus le ya o este sí porque esta entre cuando muy sin sobre también me hasta
        hay donde quien desde todo nos durante todos uno les ni contra otros ese eso ante
        ellos e esto mí antes algunos qué unos yo otro otras otra él tanto esa estos mucho
        quienes nada muchos cual sea poco ella estar haber estas estaba estamos algunas
        algo nosotros""".split()
    ),
    "en": frozenset(
        """the of and to in a is that for it as was with be by on not he i this are or
        his from at which but have an they one you were all we there her she would their
        will been has when who more if no other so what its about into than them can only
        some could time these two may then do first any my now such like our over man me
        even most made after also did many before must through back years where much your
        way well down should because each just those people mr how too little state good
        very make world still own see men work long get here between both life being under
        never day same another know while last might us great old year off come since
        against go came right used take three""".split()
    ),
    "pt": frozenset(
        """de a o que e do da em um para com não uma os no se na por mais as dos como mas
        ao ele das à seu sua ou quando muito nos já eu também só pelo pela até isso ela
        entre depois sem mesmo aos seus quem nas me esse eles você essa num nem suas meu
        às minha numa pelos elas qual nós lhe deles essas esses pelas este dele tu te
        vocês vos lhes meus minhas teu tua""".split()
    ),
}

# Sanity check por idioma: caracteres que casi obligan a una lengua concreta.
_DIACRITIC_HINTS = {
    "es": frozenset("ñáéíóúü¿¡"),
    "pt": frozenset("ãõçáéíóúâêô"),
    "en": frozenset(),
}

_SCRIPT_TO_LANG = {
    "cyrillic": "ru",
    "arabic": "ar",
    "hangul": "ko",
    "kana": "ja",
    "han": "zh",
    "greek": "el",
    "hebrew": "he",
}


def tokenize(text: str, limit: int = 40_000) -> list[str]:
    return [m.group(0).lower() for m in _WORD_RE.finditer(text[:limit])]


def stopword_ratio(tokens: list[str], lang: str) -> float:
    """Fracción de tokens que son palabras funcionales del idioma dado."""
    if not tokens:
        return 0.0
    sw = STOPWORDS.get(lang)
    if not sw:
        return 0.0
    return sum(1 for t in tokens if t in sw) / len(tokens)


def detect(text: str) -> tuple[str | None, float, dict[str, float], str | None]:
    """Devuelve (idioma, confianza, distribución de escritura, escritura dominante)."""
    dist = script_distribution(text)
    script = dominant_script(dist)

    if script is None:
        return None, 0.0, dist, None

    # Escrituras no latinas: la escritura ya determina el idioma con alta confianza.
    if script in _SCRIPT_TO_LANG:
        # Japonés vs chino: el kana es la señal decisiva.
        if script == "han" and dist.get("kana", 0) >= 0.02:
            return "ja", 0.9, dist, script
        return _SCRIPT_TO_LANG[script], 0.9, dist, script

    if script != "latin":
        return None, 0.0, dist, script

    tokens = tokenize(text)
    if len(tokens) < 15:
        return None, 0.0, dist, script  # texto insuficiente para decidir

    scores = {lang: stopword_ratio(tokens, lang) for lang in STOPWORDS}
    chars = set(text[:20_000].lower())
    for lang, hints in _DIACRITIC_HINTS.items():
        if hints & chars:
            scores[lang] = scores.get(lang, 0.0) + 0.02

    best, best_score = max(scores.items(), key=lambda x: x[1])
    if best_score < 0.03:
        return None, best_score, dist, script

    runner_up = sorted(scores.values(), reverse=True)[1] if len(scores) > 1 else 0.0
    confidence = min(1.0, best_score * 3) * (1 - min(0.9, runner_up / max(best_score, 1e-9)))
    return best, round(max(confidence, 0.1), 3), dist, script
