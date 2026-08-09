"""Adapter específico de Amazon Underworld.

4.369 filas × 32 columnas, pero **sólo 999 tienen datos**: las otras 3.370 son teselas de
zoom bajo con geometría y sin atributos. Tras deduplicar por municipio quedan 986 únicos.

Dos precisiones semánticas que un pipeline ingenuo aplana:
  · las columnas de grupo son cadenas 'SI'/'NO', NO booleanos;
  · `au_no_info = SI` significa "sin información", NO "ningún grupo presente" (324
    municipios). Convertirlo a `grupos: []` sería inventar un dato.
"""

from __future__ import annotations

from pathlib import Path

from ...normalization.unicode_clean import normalize_value
from ..base import BlockBuilder, ParseResult
from .csv_parser import read_rows

_GROUP_PREFIX = "grupo_"

# El dataset trae su propio identificador de municipio. Usarlo en vez de reconstruir una
# clave da 986 municipios únicos (la cifra verificada); una clave derivada de
# (país, nivel1, nivel2) da 987, y (país, nivel2) da 981 porque 6 municipios comparten
# nombre entre departamentos ('Puerto Rico' existe en Caquetá y en Meta).
_ID_COL = "au_ID_concatenated"
_FALLBACK_KEY_COLS = ("au_country", "au_level1", "au_level2")


def _has_data(row: dict[str, str]) -> bool:
    """Una fila útil tiene al menos país y municipio."""
    return bool(row.get("au_country") and row.get("au_level2"))


def parse_amazon_underworld(
    path: Path,
    doc_id: str,
    pipeline_version: str,
) -> ParseResult:
    header, raw_rows = read_rows(path, ",")
    header = [normalize_value(h) for h in header]

    result = ParseResult()
    builder = BlockBuilder(doc_id, pipeline_version)

    geometry_only = 0
    # Clave de deduplicación: país + nivel1 + nivel2.
    merged: dict[tuple[str, ...], dict] = {}

    for i, values in enumerate(raw_rows, start=1):
        row = {h: normalize_value(v) for h, v in zip(header, values)}
        if not _has_data(row):
            geometry_only += 1
            continue

        official_id = row.get(_ID_COL, "")
        key = (
            (official_id,)
            if official_id
            else tuple(row.get(c, "") for c in _FALLBACK_KEY_COLS)
        )
        record = merged.setdefault(
            key,
            {
                "municipality_id": official_id or None,
                "country": row.get("au_country"),
                "level1": row.get("au_level1"),
                "level2": row.get("au_level2"),
                "adm1_pcode": row.get("b_ADM1_PCODE") or None,
                "adm2_pcode": row.get("b_ADM2_PCODE") or None,
                "area_km2": row.get("au_area_km2") or None,
                "population": row.get("au_population") or None,
                # 'SI' / 'NO' como cadena: se preserva el valor original.
                "no_info": row.get("au_no_info") or None,
                "groups_present": [],
                "groups_detail_es": row.get("grupos_detalle_ES") or None,
                "total_groups": row.get("total_grupos_presentes") or None,
                # Trazabilidad: qué filas del CSV se colapsaron en este registro.
                "source_rows": [],
            },
        )
        record["source_rows"].append(i)

        for col, value in row.items():
            if col.startswith(_GROUP_PREFIX) and value.upper() == "SI":
                group = col[len(_GROUP_PREFIX):]
                if group not in record["groups_present"]:
                    record["groups_present"].append(group)

    for record in merged.values():
        no_info = (record.get("no_info") or "").upper() == "SI"
        parts = [
            f"Municipio: {record['level2']}",
            f"Departamento/Estado: {record['level1']}",
            f"País: {record['country']}",
        ]
        if no_info:
            # Redacción explícita: "sin información" ≠ "sin grupos".
            parts.append("Presencia de grupos armados: SIN INFORMACIÓN disponible")
        elif record["groups_present"]:
            parts.append(
                "Grupos armados con presencia registrada: "
                + ", ".join(record["groups_present"])
            )
        else:
            parts.append("Grupos armados con presencia registrada: ninguno")
        if record.get("groups_detail_es"):
            parts.append(f"Detalle: {record['groups_detail_es']}")

        if block := builder.add(
            "; ".join(parts),
            "table_row",
            "structured",
            row=record["source_rows"][0],
            structured_data=record,
        ):
            result.blocks.append(block)

    countries: dict[str, int] = {}
    for record in merged.values():
        c = record["country"] or "?"
        countries[c] = countries.get(c, 0) + 1

    result.metadata = {
        "schema": "amazon_underworld_municipalities",
        "raw_rows": len(raw_rows),
        "geometry_only_rows": geometry_only,
        "unique_municipalities": len(merged),
        "municipalities_by_country": dict(sorted(countries.items(), key=lambda x: -x[1])),
        "no_info_count": sum(
            1 for r in merged.values() if (r.get("no_info") or "").upper() == "SI"
        ),
        "note_no_info": "au_no_info=SI significa SIN INFORMACIÓN, no ausencia de grupos",
    }
    # El dataset es regional amazónico: sólo 87 municipios colombianos, insuficiente por
    # sí solo para q041-q043 (Chocó, Norte de Santander y Arauca no son amazónicos).
    result.warnings.append(
        f"regional_amazon_scope__colombia_only_{countries.get('Colombia', 0)}_municipalities"
    )
    return result
