"""Parser CSV.

`csv.reader` con `newline=""`. Nunca `splitlines()`, nunca pandas como primer parser,
nunca `csv.Sniffer`. Cuatro trampas verificadas en el corpus:

1. Un CSV usa TAB pese a la extensión `.csv` (`lit-covid`).
2. Ese mismo tiene 8.188 saltos de línea DENTRO de campos entrecomillados: 8.866 filas
   lógicas frente a 17.054 líneas físicas. Leer línea a línea duplica y corrompe.
3. U+2028/U+2029 en 4 CSV de PubMed: `splitlines()` parte por ellos y devuelve 111.777
   filas en vez de 111.775, con 4 desalineadas. `csv.reader` con `newline=""` no.
4. 4.561 NBSP en 13 archivos, concentrados en la columna `Age`. `.strip()` no los quita.
"""

from __future__ import annotations

import csv
import sys
from pathlib import Path

from ... import config
from ...normalization.unicode_clean import normalize_value
from ..base import BlockBuilder, ParseResult

# Un campo de un CSV del corpus puede ser enorme (abstracts completos).
csv.field_size_limit(min(sys.maxsize, 2**31 - 1))


def schema_for(filename: str) -> dict:
    """Config determinista por archivo. Preferimos esto a adivinar con Sniffer."""
    lowered = filename.lower()
    # El más específico primero: `pubmed-nlp` tiene 11 columnas, sus hermanos 12.
    for key in sorted(config.CSV_SCHEMAS, key=len, reverse=True):
        if key in lowered:
            return config.CSV_SCHEMAS[key]
    return config.CSV_DEFAULT


def read_rows(path: Path, delimiter: str) -> tuple[list[str], list[list[str]]]:
    """Devuelve (cabecera, filas). `newline=""` es obligatorio, no cosmético."""
    with path.open("r", encoding="utf-8", newline="") as f:
        reader = csv.reader(f, delimiter=delimiter)
        rows = list(reader)
    if not rows:
        return [], []
    return rows[0], rows[1:]


def row_to_text(header: list[str], values: list[str]) -> str:
    """Serializa una fila preservando el nombre de cada campo.

    No se convierte la tabla entera en prosa: cada fila es su propio bloque, y el nombre
    del campo va en el texto para que el embedding posterior tenga contexto.
    """
    parts = []
    for name, value in zip(header, values):
        value = normalize_value(value)
        if not value:
            continue
        parts.append(f"{normalize_value(name) or '?'}: {value}")
    return "; ".join(parts)


def _typed(value: str) -> object:
    """Conversión conservadora: sólo enteros y flotantes inequívocos."""
    value = normalize_value(value)
    if not value:
        return None
    if value.lstrip("-").isdigit():
        try:
            return int(value)
        except ValueError:
            return value
    return value


def parse_csv(
    path: Path,
    doc_id: str,
    pipeline_version: str,
    *,
    multivalue_fields: bool = True,
) -> ParseResult:
    schema = schema_for(path.name)
    header, rows = read_rows(path, schema["delimiter"])

    result = ParseResult()
    builder = BlockBuilder(doc_id, pipeline_version)

    if not header:
        result.warnings.append("empty_csv")
        return result

    header = [normalize_value(h) for h in header]
    expected = schema.get("expected_cols")
    if expected and len(header) != expected:
        # No es fatal, pero concatenar esquemas desalineados desplaza todos los campos.
        result.warnings.append(
            f"unexpected_column_count:{len(header)}!={expected}"
        )

    irregular = 0
    for i, values in enumerate(rows, start=1):
        if not any(v.strip() for v in values):
            continue
        if len(values) != len(header):
            irregular += 1

        structured: dict[str, object] = {}
        for name, value in zip(header, values):
            typed = _typed(value)
            if typed is None:
                continue
            if (
                multivalue_fields
                and isinstance(typed, str)
                and config.MULTIVALUE_SEPARATOR in typed
            ):
                typed = [
                    normalize_value(p)
                    for p in typed.split(config.MULTIVALUE_SEPARATOR)
                    if p.strip()
                ]
            structured[name or "?"] = typed

        if block := builder.add(
            row_to_text(header, values),
            "table_row",
            "structured",
            row=i,
            structured_data=structured or None,
        ):
            result.blocks.append(block)

    if irregular:
        result.warnings.append(f"irregular_row_widths:{irregular}")

    result.metadata = {
        "schema": "csv_table",
        "header": header,
        "delimiter": "\\t" if schema["delimiter"] == "\t" else schema["delimiter"],
        "logical_rows": len(result.blocks),
        "physical_lines": sum(1 for _ in path.open("rb")),
    }
    return result
