"""Normalización de metadatos.

La v1 del plan sólo normalizaba texto y dejaba los metadatos crudos. Pero el corpus tiene
cinco formatos de fecha incompatibles, autores contaminados con cargos y campos que nunca
se poblaron. Sin esta capa, el filtrado temporal y la atribución por autor son inservibles.
"""

from __future__ import annotations

import re
from datetime import datetime

from .. import config
from .unicode_clean import normalize_value

DateConf = str  # "exact" | "inferred" | "ambiguous" | "absent"

_MONTHS = {
    m: i
    for i, names in enumerate(
        [
            ("january", "jan", "enero", "ene", "janeiro"),
            ("february", "feb", "febrero", "fevereiro", "fev"),
            ("march", "mar", "marzo", "março"),
            ("april", "apr", "abril", "abr"),
            ("may", "mayo", "maio"),
            ("june", "jun", "junio", "junho"),
            ("july", "jul", "julio", "julho"),
            ("august", "aug", "agosto", "ago"),
            ("september", "sep", "sept", "septiembre", "setembro", "set"),
            ("october", "oct", "octubre", "outubro", "out"),
            ("november", "nov", "noviembre", "novembro"),
            ("december", "dec", "diciembre", "dic", "dezembro", "dez"),
        ],
        start=1,
    )
    for m in names
}

_ISO = re.compile(r"^(\d{4})-(\d{2})-(\d{2})")
_SLASH = re.compile(r"^(\d{1,2})/(\d{1,2})/(\d{4})$")
_TEXTUAL = re.compile(r"^([A-Za-zÀ-ÿ]+)\.?\s+(\d{1,2}),?\s+(\d{4})$")
_TEXTUAL_ES = re.compile(r"^(\d{1,2})\s+de\s+([A-Za-zÀ-ÿ]+)\s+de\s+(\d{4})$", re.I)
_YEAR_ONLY = re.compile(r"^(\d{4})$")


def normalize_date(raw: object) -> tuple[str | None, DateConf, str | None]:
    """Devuelve (fecha ISO, confianza, aviso).

    La fecha de ESA (`01/04/2025`) NO es normalizable sin decidir: es 1-abr o 4-ene.
    Se marca `ambiguous` y se conserva el valor original. Nunca se adivina en silencio.
    """
    if raw is None:
        return None, "absent", None
    text = normalize_value(str(raw))
    if not text:
        return None, "absent", None

    if m := _ISO.match(text):
        y, mo, d = (int(g) for g in m.groups())
        try:
            return datetime(y, mo, d).strftime("%Y-%m-%d"), "exact", None
        except ValueError:
            return None, "absent", f"invalid_iso_date:{text}"

    if m := _TEXTUAL.match(text):
        month_name, day, year = m.group(1).lower(), int(m.group(2)), int(m.group(3))
        if (mo := _MONTHS.get(month_name)) :
            try:
                return datetime(year, mo, day).strftime("%Y-%m-%d"), "exact", None
            except ValueError:
                pass

    if m := _TEXTUAL_ES.match(text):
        day, month_name, year = int(m.group(1)), m.group(2).lower(), int(m.group(3))
        if (mo := _MONTHS.get(month_name)) :
            try:
                return datetime(year, mo, day).strftime("%Y-%m-%d"), "exact", None
            except ValueError:
                pass

    if m := _SLASH.match(text):
        a, b, year = int(m.group(1)), int(m.group(2)), int(m.group(3))
        if a > 12 and b <= 12:  # sólo puede ser d/m
            return f"{year:04d}-{b:02d}-{a:02d}", "exact", None
        if b > 12 and a <= 12:  # sólo puede ser m/d
            return f"{year:04d}-{a:02d}-{b:02d}", "exact", None
        # Ambos ≤12: irresoluble. Se conserva el original y se marca.
        return None, "ambiguous", f"ambiguous_day_month:{text}"

    if m := _YEAR_ONLY.match(text):
        return f"{m.group(1)}-01-01", "inferred", f"year_only:{text}"

    return None, "absent", f"unparsed_date:{text}"


# Marcadores de que una entrada de `authors` es en realidad un cargo o una biografía.
_ROLE_MARKERS = (
    "fellow", "director", "researcher", "professor", "analyst", "associate",
    "senior", "junior", "chair", "president", "advisor", "adviser", "officer",
    "intern", "scholar", "lecturer", "head of", "member of", "expert",
    "investigador", "director", "profesor", "analista", "miembro",
)
_SENTENCE_MARKERS = (" is ", " was ", " es ", " era ", " at ", " en el ", " de la ")

# Nombres de usuario de CMS que se colaron como autor (p.ej. 'sscott' en Atlantic).
_USERNAME_RE = re.compile(r"^[a-z]{2,}\d*$")


def clean_authors(raw: object) -> tuple[list[str], list[str]]:
    """Separa personas de cargos y biografías. Devuelve (autores, descartados).

    Atlantic Council lista 9 "autores" que son 4 personas + 5 títulos; SIPRI incluye
    'Dr Michal Krelina is an Associate Senior Researcher at SIPRI.'.
    Lo descartado se REGISTRA, no se borra.
    """
    if raw is None:
        return [], []
    items = raw if isinstance(raw, list) else [raw]

    authors: list[str] = []
    dropped: list[str] = []
    for item in items:
        if not isinstance(item, str):
            continue
        value = normalize_value(item)
        if not value:
            continue
        low = value.lower()

        if any(mark in low for mark in _SENTENCE_MARKERS) and len(value.split()) > 5:
            dropped.append(f"biography:{value}")
        elif any(low.startswith(m) or low == m for m in _ROLE_MARKERS):
            dropped.append(f"role:{value}")
        elif _USERNAME_RE.match(value) and " " not in value:
            dropped.append(f"cms_username:{value}")
        elif len(value) > 90:
            dropped.append(f"too_long:{value[:60]}…")
        else:
            authors.append(value)

    return authors, dropped


def filter_fields(payload: dict, observatory_code: str) -> tuple[dict, list[str]]:
    """Quita campos verificados como siempre vacíos, redundantes o no fiables.

    El esquema no debe prometer lo que nunca existe: persistir `ESA.tags: null` en los 16
    documentos es ruido que las capas siguientes tendrán que volver a filtrar.
    """
    warnings: list[str] = []
    out = dict(payload)

    for field in config.REDUNDANT_FIELDS:
        if field in out:
            del out[field]

    for field in config.ALWAYS_EMPTY_FIELDS.get(observatory_code, ()):
        if field in out:
            del out[field]
            warnings.append(f"dropped_always_empty:{field}")

    for field in config.UNRELIABLE_FIELDS.get(observatory_code, ()):
        if field in out:
            del out[field]
            warnings.append(f"dropped_unreliable:{field}")

    # Campos vacíos genéricos: no aportan y engordan el manifest.
    for key in [k for k, v in out.items() if v in (None, "", [], {})]:
        del out[key]

    return out, warnings
