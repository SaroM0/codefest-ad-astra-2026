"""Contrastes C1–C6: el corpus valida al corpus.

Las señales intrínsecas dicen si un texto *parece* sano. Los contrastes dicen si *es* el
texto correcto. Casi todos son gratis porque el corpus contiene su propia redundancia:

  C1  OCR de control sobre páginas nativas sanas → corrupción independiente del idioma
  C2  título del índice/catálogo ↔ primeras páginas → ¿es el documento correcto?
  C3  `alerta_meta` ↔ OCR del PDF de alerta → ground truth REAL sobre entidades
  C4  lit-covid CSV ↔ su XLSX gemelo → valida el parser tabular contra sí mismo
  C5  9 catálogos JSON ↔ sus 9 CSV espejo → valida el parser CSV
  C6  15 pares del gold set → test extremo-a-extremo de fidelidad

C6 se usa SÓLO como assert: no entra al corpus, no se indexa, no ajusta parámetros.
"""

from __future__ import annotations

import re
import unicodedata

from adastra.core.models.quality import CrossCheck

_WS = re.compile(r"\s+")


def _norm(text: str) -> str:
    """Normalización agresiva para comparar: sin acentos, sin puntuación, sin espacios."""
    text = unicodedata.normalize("NFD", text.lower())
    text = "".join(c for c in text if unicodedata.category(c) != "Mn")
    text = re.sub(r"[^a-z0-9áéíóúñü ]+", " ", text)
    return _WS.sub(" ", text).strip()


def _token_overlap(needle: str, haystack: str) -> float:
    a = set(_norm(needle).split())
    if not a:
        return 0.0
    b = set(_norm(haystack).split())
    return len(a & b) / len(a)


# ---------------------------------------------------------------------------------
# C2 — el título esperado aparece en el documento
# ---------------------------------------------------------------------------------
def check_title_match(
    expected_title: str | None,
    document_text: str,
    head_chars: int = 6000,
) -> CrossCheck | None:
    """¿El texto extraído corresponde al documento que el índice/catálogo dice?

    Barato y muy discriminante: si el título no aparece ni parcialmente en las primeras
    páginas, o el texto está corrupto o es otro documento.
    """
    if not expected_title or len(expected_title.strip()) < 8:
        return None
    head = document_text[:head_chars]
    if not head.strip():
        return None

    overlap = _token_overlap(expected_title, head)
    return CrossCheck(
        type="title_match",
        passed=overlap >= 0.5,
        score=round(overlap, 4),
        detail={"expected_title": expected_title[:120], "token_overlap": round(overlap, 4)},
    )


# ---------------------------------------------------------------------------------
# C3 — entidades de `alerta_meta` en el texto del PDF de alerta
# ---------------------------------------------------------------------------------
def check_alert_entities(
    alert_meta: dict,
    document_text: str,
) -> CrossCheck:
    """Ground truth REAL sobre entidades para los PDFs de Alertas Tempranas.

    Los JSON dan código (363 únicos), municipios (289 únicos) y fecha ISO. Como los PDFs
    son escaneos sin texto nativo, encontrar esas entidades en el texto extraído mide
    exactamente lo que importa: nombres propios, municipios y siglas.

    Y como el pareo JSON↔PDF sólo es posible DESPUÉS del OCR (los nombres de archivo no
    se corresponden), este contraste es simultáneamente el emparejador y la métrica.
    """
    normalized = _norm(document_text)
    detail: dict = {}

    code = str(alert_meta.get("alert_code") or "").strip()
    code_found = bool(code) and _norm(code) in normalized
    detail["alert_code"] = code
    detail["alert_code_found"] = code_found

    municipalities = alert_meta.get("municipalities") or []
    found = 0
    missing: list[str] = []
    for muni in municipalities:
        name = (muni.get("municipality") or "").strip()
        if not name:
            continue
        if _norm(name) in normalized:
            found += 1
        else:
            missing.append(name)
    detail["municipalities_found"] = f"{found}/{len(municipalities)}"
    detail["municipalities_missing"] = missing[:5]

    date = str(alert_meta.get("date") or "")
    year = date[:4]
    detail["year_found"] = bool(year) and year in document_text

    # Se puntúa lo que hay: un documento sin municipios declarados no se penaliza por
    # no encontrarlos.
    parts: list[float] = []
    if code:
        parts.append(1.0 if code_found else 0.0)
    if municipalities:
        parts.append(found / len(municipalities))
    if year:
        parts.append(1.0 if detail["year_found"] else 0.0)
    score = sum(parts) / len(parts) if parts else 0.0

    return CrossCheck(
        type="entity_crosscheck",
        passed=score >= 0.5,
        score=round(score, 4),
        detail=detail,
    )


# ---------------------------------------------------------------------------------
# C6 — el fragmento del gold set aparece literalmente
# ---------------------------------------------------------------------------------
def check_gold_fragment(fragment: str, document_text: str) -> CrossCheck:
    """Test extremo-a-extremo: si el fragmento citado no aparece, la extracción perdió
    contenido de ese documento.

    Se compara sobre texto normalizado (sin acentos ni espacios múltiples) porque el
    fragmento del gold set procede de un chunking previo con su propia normalización.
    Se acepta coincidencia parcial alta: los saltos de línea del PDF y el recorte del
    fragmento no tienen por qué alinearse carácter a carácter.
    """
    norm_fragment = _norm(fragment)
    norm_doc = _norm(document_text)

    if not norm_fragment or not norm_doc:
        return CrossCheck(type="gold_fragment", passed=False, score=0.0,
                          detail={"reason": "empty"})

    if norm_fragment in norm_doc:
        return CrossCheck(
            type="gold_fragment", passed=True, score=1.0,
            detail={"match": "exact_normalized", "length": len(fragment)},
        )

    # Coincidencia por ventana de n-gramas: se busca la subcadena más larga del
    # fragmento que sí esté presente.
    words = norm_fragment.split()
    best = 0
    for size in (12, 8, 5):
        if len(words) < size:
            continue
        hits = sum(
            1
            for i in range(len(words) - size + 1)
            if " ".join(words[i: i + size]) in norm_doc
        )
        total = len(words) - size + 1
        if total:
            best = max(best, hits / total)
        if best > 0.8:
            break

    return CrossCheck(
        type="gold_fragment",
        passed=best >= 0.5,
        score=round(best, 4),
        detail={"match": "ngram_coverage", "coverage": round(best, 4),
                "fragment_words": len(words)},
    )


# ---------------------------------------------------------------------------------
# C4 / C5 — espejos: mismo contenido en dos formatos
# ---------------------------------------------------------------------------------
def check_mirror(
    rows_a: list[dict],
    rows_b: list[dict],
    label: str,
) -> CrossCheck:
    """Dos representaciones del mismo dato deben coincidir en filas y en valores.

    Valida el parser contra sí mismo: `lit-covid` existe en CSV (con TAB y 8.188 saltos
    embebidos) y en XLSX; los 9 catálogos existen en JSON y en CSV espejo. Si el parser
    tabular tiene un bug, los dos lados divergen.
    """
    detail: dict = {"rows_a": len(rows_a), "rows_b": len(rows_b), "mirror": label}
    if not rows_a or not rows_b:
        return CrossCheck(type="mirror_match", passed=False, score=0.0, detail=detail)

    row_score = min(len(rows_a), len(rows_b)) / max(len(rows_a), len(rows_b))

    # Comparación de contenido sobre una muestra: se normalizan los valores a texto para
    # absorber diferencias de tipado entre formatos (el XLSX devuelve floats).
    sample = min(200, len(rows_a), len(rows_b))
    matches = 0
    for a, b in zip(rows_a[:sample], rows_b[:sample]):
        va = {_norm(str(v)) for v in a.values() if str(v).strip()}
        vb = {_norm(str(v)) for v in b.values() if str(v).strip()}
        if va and vb and len(va & vb) / len(va | vb) >= 0.6:
            matches += 1
    value_score = matches / sample if sample else 0.0

    detail["row_count_ratio"] = round(row_score, 4)
    detail["value_agreement"] = round(value_score, 4)
    score = round(0.4 * row_score + 0.6 * value_score, 4)

    return CrossCheck(
        type="mirror_match", passed=score >= 0.8, score=score, detail=detail
    )


# ---------------------------------------------------------------------------------
# C1 — acuerdo nativo ↔ OCR de control
# ---------------------------------------------------------------------------------
def check_ocr_agreement(native_text: str, ocr_text: str) -> CrossCheck:
    """OCR de control sobre una página que se considera sana.

    Es la única señal de corrupción INDEPENDIENTE DEL IDIOMA. Habría cazado el
    CEOBS-Sudán automáticamente — y también cazaría un CEOBS-Sudán en chino, donde la
    regla de palabras funcionales no sirve de nada.
    """
    a, b = _norm(native_text), _norm(ocr_text)
    if len(a) < 100 or len(b) < 100:
        return CrossCheck(
            type="ocr_agreement", passed=False, score=0.0,
            detail={"reason": "insufficient_text"},
        )

    tokens_a, tokens_b = set(a.split()), set(b.split())
    jaccard = len(tokens_a & tokens_b) / len(tokens_a | tokens_b)
    return CrossCheck(
        type="ocr_agreement",
        passed=jaccard >= 0.45,
        score=round(jaccard, 4),
        detail={"token_jaccard": round(jaccard, 4),
                "native_tokens": len(tokens_a), "ocr_tokens": len(tokens_b)},
    )
