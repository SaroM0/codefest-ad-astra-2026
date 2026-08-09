"""Carga del índice maestro `Indice_Datos_Codefest.xlsx`.

El pipeline NO empieza con glob("**/*"). Empieza aquí, porque el `DOC_ID`
(`F{n}-{CÓDIGO}-{NNN}`) es el único identificador estable del corpus y el que usa el reto.

Se lee el XLSX como ZIP de XML en vez de con openpyxl: es una dependencia menos en la ruta
crítica y el formato de la hoja es trivial (sin fórmulas, sin estilos relevantes).
"""

from __future__ import annotations

import zipfile
from dataclasses import dataclass
from pathlib import Path
from xml.etree.ElementTree import Element

# Los XLSX vienen de la organización, no de nosotros: parser endurecido.
from defusedxml import ElementTree as ET

NS = "{http://schemas.openxmlformats.org/spreadsheetml/2006/main}"


@dataclass(frozen=True)
class IndexRecord:
    doc_id: str
    phenomenon: str
    observatory: str
    observatory_code: str
    filename: str
    folder: str
    declared_type: str

    @property
    def relative_path(self) -> str:
        return f"{self.folder}/{self.filename}" if self.folder else self.filename


def _shared_strings(z: zipfile.ZipFile) -> list[str]:
    if "xl/sharedStrings.xml" not in z.namelist():
        return []
    root = ET.fromstring(z.read("xl/sharedStrings.xml"))
    return ["".join(t.text or "" for t in si.iter(NS + "t")) for si in root]


def _sheet_path(z: zipfile.ZipFile, sheet_name: str) -> str:
    """Resuelve nombre de hoja → xl/worksheets/sheetN.xml vía workbook + rels."""
    wb = ET.fromstring(z.read("xl/workbook.xml"))
    rels = ET.fromstring(z.read("xl/_rels/workbook.xml.rels"))
    rid_to_target = {
        r.get("Id"): r.get("Target", "") for r in rels
    }
    rid_attr = "{http://schemas.openxmlformats.org/officeDocument/2006/relationships}id"
    for sheet in wb.iter(NS + "sheet"):
        if sheet.get("name") == sheet_name:
            target = rid_to_target.get(sheet.get(rid_attr, ""), "")
            if target:
                return target if target.startswith("xl/") else f"xl/{target.lstrip('/')}"
    raise KeyError(f"Hoja no encontrada en el índice maestro: {sheet_name!r}")


def _cell_value(cell: Element, sst: list[str]) -> str:
    if cell.get("t") == "inlineStr":
        return "".join(t.text or "" for t in cell.iter(NS + "t"))
    v = cell.find(NS + "v")
    if v is None or v.text is None:
        return ""
    if cell.get("t") == "s":
        try:
            return sst[int(v.text)]
        except (ValueError, IndexError):
            return ""
    return v.text


def _col_letter(ref: str) -> str:
    """'C12' -> 'C'. La referencia de celda es la única forma fiable de saber en qué
    columna está un valor: las filas de un XLSX son DISPERSAS — una fila sin valor en A
    simplemente no emite la celda A, y emparejar por posición desalinea todo."""
    return "".join(ch for ch in ref if ch.isalpha())


def _rows(z: zipfile.ZipFile, sheet: str, sst: list[str]) -> list[dict[str, str]]:
    """Devuelve cada fila como {letra_de_columna: valor}, respetando huecos."""
    root = ET.fromstring(z.read(sheet))
    out: list[dict[str, str]] = []
    for row in root.iter(NS + "row"):
        cells: dict[str, str] = {}
        for c in row:
            ref = c.get("r") or ""
            if not ref:
                continue
            value = _cell_value(c, sst)
            if value:
                cells[_col_letter(ref)] = value
        out.append(cells)
    return out


def load_index(xlsx_path: Path, sheet_name: str) -> list[IndexRecord]:
    """Devuelve los 1.826 registros del `Inventario de Archivos`."""
    with zipfile.ZipFile(xlsx_path) as z:
        sst = _shared_strings(z)
        rows = list(_rows(z, _sheet_path(z, sheet_name), sst))

    if not rows:
        raise ValueError(f"Hoja vacía: {sheet_name}")

    # La cabecera puede no empezar en la columna A: se mapea nombre → letra de columna.
    header_row = rows[0]
    col = {name.strip(): letter for letter, name in header_row.items()}
    required = [
        "Fenómeno",
        "Observatorio",
        "Código Observatorio",
        "DOC_ID",
        "Nombre estandarizado",
        "Carpeta",
        "Tipo",
    ]
    missing = [c for c in required if c not in col]
    if missing:
        raise ValueError(f"Faltan columnas en el índice maestro: {missing}")

    def get(row: dict[str, str], name: str) -> str:
        return row.get(col[name], "").strip()

    records: list[IndexRecord] = []
    for row in rows[1:]:
        doc_id = get(row, "DOC_ID")
        if not doc_id:
            continue
        records.append(
            IndexRecord(
                doc_id=doc_id,
                phenomenon=get(row, "Fenómeno"),
                observatory=get(row, "Observatorio"),
                observatory_code=get(row, "Código Observatorio"),
                filename=get(row, "Nombre estandarizado"),
                folder=get(row, "Carpeta"),
                declared_type=get(row, "Tipo"),
            )
        )
    return records


def load_gold_set(xlsx_path: Path) -> list[dict]:
    """Lee `FASE ORDENADA CODEFEST.xlsx` → pares pregunta→fragmento→documento.

    Sólo 15 de las 25 filas tienen fragmento no vacío; cubren 8 preguntas.
    OJO: usa dos numeraciones incompatibles (`2,3,4` en F1; `q0047`–`q0052` en F3) y
    ninguna coincide con `q001`–`q050`. El emparejamiento debe hacerse por TEXTO.
    """
    pairs: list[dict] = []
    with zipfile.ZipFile(xlsx_path) as z:
        sst = _shared_strings(z)
        wb = ET.fromstring(z.read("xl/workbook.xml"))
        for sheet in wb.iter(NS + "sheet"):
            name = sheet.get("name") or ""
            try:
                path = _sheet_path(z, name)
            except KeyError:
                continue
            rows = _rows(z, path, sst)

            # La cabecera no está necesariamente en la primera fila (en la hoja F1 está
            # en la fila 2 y empieza en la columna B).
            col: dict[str, str] = {}
            body_start = 0
            for i, row in enumerate(rows):
                found = {
                    key: letter
                    for letter, value in row.items()
                    for key in ("PREGUNTA", "FRAGMENTO", "DOCUMENTO")
                    if key in value.strip().upper()
                }
                if "FRAGMENTO" in found and "DOCUMENTO" in found:
                    col, body_start = found, i + 1
                    break
            if not col:
                continue

            # Las filas de continuación traen sólo FRAGMENTO+DOCUMENTO y pertenecen a la
            # última pregunta vista: la misma pregunta puede citar varios fragmentos.
            current_q = ""
            current_id = ""
            for row in rows[body_start:]:
                question = row.get(col.get("PREGUNTA", ""), "").strip()
                if question:
                    current_q = question
                    # La columna de número de pregunta no siempre tiene encabezado
                    # (hoja F1) o se llama '# 1' (hoja F3): se toma la columna A.
                    current_id = row.get("A", "").strip()

                fragment = row.get(col["FRAGMENTO"], "").strip()
                if not fragment:
                    continue  # q0051 sin fragmento; y 10 filas de F3 vacías

                # El campo DOCUMENTO trae "archivo.pdf\nDOC-0300-chunk-0052": el ID de
                # chunk procede de un chunking previo cuyo mapeo NO está en el corpus.
                raw_doc = row.get(col["DOCUMENTO"], "").strip()
                parts = [p.strip() for p in raw_doc.splitlines() if p.strip()]
                pairs.append(
                    {
                        "sheet": name,
                        "question_id": current_id,
                        "question": current_q,
                        "fragment": fragment,
                        "document": parts[0] if parts else "",
                        "legacy_chunk_id": parts[1] if len(parts) > 1 else None,
                    }
                )
    return pairs
