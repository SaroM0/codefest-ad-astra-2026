"""Catalog join: recupera la procedencia que el índice maestro no trae.

El índice maestro da DOC_ID, fenómeno, observatorio y ruta — pero **no da URL de origen,
ni fecha de publicación, ni título original**. Para 760 PDFs, esa información sólo existe
en los catálogos del scraper. Sin esta etapa, un reto que exige citar evidencia se queda
sin la referencia web de sus documentos.

El problema: los catálogos citan nombres del servidor (`ATLAS-2024-ESP.pdf`) pero el
corpus fue renombrado a `{CÓDIGO}_{slug}`. Una búsqueda literal falla en el 100% de los
casos. La regla de normalización de abajo resuelve el 99,5%.
"""

from __future__ import annotations

import json
import os
import re
import unicodedata
import urllib.parse
from dataclasses import dataclass, field
from pathlib import Path

from .. import config


def nombre_estandarizado(url: str, observatory_code: str) -> str:
    """Convierte la URL de un catálogo al nombre real en disco.

    Tasa de acierto verificada: 99,5% sobre 220 referencias.
    """
    base = os.path.basename(urllib.parse.unquote(urllib.parse.urlparse(url).path))
    # Alguna URL trae un espacio codificado al final (`...ESP.pdf%20`): tras unquote,
    # splitext devolvería la extensión ".pdf " y el candidato no casaría con nada.
    base = base.strip()
    stem, ext = os.path.splitext(base)
    ext = ext.strip()
    s = "".join(
        c
        for c in unicodedata.normalize("NFD", stem)
        if unicodedata.category(c) != "Mn"  # quitar acentos
    )
    s = s.lower().replace("_", "-").replace(" ", "-")
    s = re.sub(r"[^a-z0-9.-]", "-", s)
    s = re.sub(r"-+", "-", s).strip("-")
    c = observatory_code.lower()
    if s.startswith(c + "-"):  # quitar prefijo redundante: daio-study… -> study…
        s = s[len(c) + 1:]
    return f"{observatory_code}_{s}{ext.lower() or '.pdf'}"


@dataclass
class CatalogRef:
    catalog: str
    observatory_code: str
    url: str
    candidate: str
    resolved_path: str | None = None
    match_kind: str | None = None  # exact | suffix-2 | prefix | basename
    title: str | None = None
    date: str | None = None


# Estados que indican descarga exitosa. Un catálogo documenta sus PROPIOS fallos:
# MAPP-OEA reporta 63×404 y 5×503 sobre 78 intentos. Esas 68 referencias no son
# "sin resolver por la regla de renombrado" — nunca produjeron un archivo en disco.
# Contarlas como fallo del join sería el error que §4.4 del análisis advierte.
_SUCCESS_STATUS = {"ok", "200", "true", "success", "downloaded"}


def _is_successful(record: dict) -> bool:
    status = record.get("status")
    if status is None:
        return True  # sin campo de estado: se asume intento válido
    return str(status).strip().lower() in _SUCCESS_STATUS


@dataclass
class JoinResult:
    by_path: dict[str, CatalogRef] = field(default_factory=dict)
    refs: list[CatalogRef] = field(default_factory=list)
    unresolved: list[CatalogRef] = field(default_factory=list)
    per_catalog: dict[str, dict[str, int]] = field(default_factory=dict)
    # Descargas que el propio catálogo declara fallidas: documentan huecos de cobertura
    # del corpus, no fallos del join. Se reportan aparte.
    failed_downloads: list[dict] = field(default_factory=list)

    @property
    def total_refs(self) -> int:
        return len(self.refs)

    @property
    def resolved(self) -> int:
        return sum(1 for r in self.refs if r.resolved_path)


def _iter_records(payload) -> list[dict]:
    """Los catálogos son listas de objetos… salvo SIPRI_catalog-2 y CEOBS_catalog-2,
    que son objetos de resumen con contadores agregados."""
    if isinstance(payload, list):
        return [r for r in payload if isinstance(r, dict)]
    if isinstance(payload, dict):
        for value in payload.values():
            if isinstance(value, list) and value and isinstance(value[0], dict):
                return value
    return []


def _first(record: dict, keys: tuple[str, ...]) -> str | None:
    for k in keys:
        v = record.get(k)
        if isinstance(v, str) and v.strip():
            return v.strip()
        if isinstance(v, (int, float)) and k in config.CATALOG_DATE_FIELDS:
            return str(v)
    return None


def _index_disk(paths: list[str]) -> tuple[dict[str, list[str]], dict[str, list[str]]]:
    """Índices auxiliares: basename → rutas, y stem-sin-sufijo → rutas."""
    by_name: dict[str, list[str]] = {}
    by_stem: dict[str, list[str]] = {}
    for p in paths:
        name = p.rsplit("/", 1)[-1]
        by_name.setdefault(name.lower(), []).append(p)
        stem = name.rsplit(".", 1)[0].lower()
        by_stem.setdefault(stem, []).append(p)
    return by_name, by_stem


def join_catalogs(
    corpus_root: Path,
    catalog_paths: list[str],
    disk_paths: list[str],
) -> JoinResult:
    """Cruza todos los catálogos contra el disco.

    Se cruzan TODOS, no uno: leer un solo catálogo da una imagen falsa de la cobertura.
    `CSIS_catalog-2.json` declara destinos en `csis_pdfs/` pero los 3 PDFs están en
    `pdfs_full/Space_Threat_Assessment/`; MAPP-OEA reporta 68 fallos sobre 78 intentos y
    sin embargo hay 31 informes por la otra ruta.
    """
    by_name, by_stem = _index_disk(disk_paths)
    result = JoinResult()

    for cat_rel in sorted(catalog_paths):
        cat_path = corpus_root / cat_rel
        cat_name = cat_path.name
        try:
            payload = json.loads(cat_path.read_text(encoding="utf-8"))
        except (json.JSONDecodeError, OSError):
            continue

        records = _iter_records(payload)
        if not records:
            continue

        # El código de observatorio se deduce de la carpeta del catálogo.
        code = _observatory_code_for(cat_rel)
        if not code:
            continue

        stats = {
            "refs": 0,
            "exact": 0,
            "suffix2": 0,
            "prefix": 0,
            "unresolved": 0,
            "failed_download": 0,
        }

        for rec in records:
            # ADVERTENCIA 1: usar el campo de URL, NO el de ruta local. Con `dest`/`path`
            # la tasa de acierto cae a 0% en CSIS y RutaN.
            url = _first(rec, config.CATALOG_URL_FIELDS)
            if not url or not url.lower().startswith(("http://", "https://")):
                continue

            clean = urllib.parse.unquote(url.split("?")[0]).strip().lower()
            if not clean.endswith((".pdf", ".doc", ".docx")):
                continue

            # Una descarga fallida no tiene archivo con el que casar: es un hueco de
            # cobertura del corpus, no un fallo de la regla de renombrado.
            if not _is_successful(rec):
                stats["failed_download"] += 1
                result.failed_downloads.append(
                    {
                        "catalog": cat_name,
                        "url": url,
                        "status": str(rec.get("status")),
                        "title": _first(rec, config.CATALOG_TITLE_FIELDS),
                    }
                )
                continue

            stats["refs"] += 1
            candidate = nombre_estandarizado(url, code)
            ref = CatalogRef(
                catalog=cat_name,
                observatory_code=code,
                url=url,
                candidate=candidate,
                title=_first(rec, config.CATALOG_TITLE_FIELDS),
                date=_first(rec, config.CATALOG_DATE_FIELDS),
            )

            resolved, kind = _resolve(candidate, code, by_name, by_stem)
            if resolved and kind:
                ref.resolved_path, ref.match_kind = resolved, kind
                stats[{"exact": "exact", "suffix-2": "suffix2", "prefix": "prefix"}[kind]] += 1
                # Si dos refs apuntan al mismo archivo, gana la primera (orden estable).
                result.by_path.setdefault(resolved, ref)
            else:
                stats["unresolved"] += 1
                result.unresolved.append(ref)

            result.refs.append(ref)

        if stats["refs"]:
            result.per_catalog[cat_name] = stats

    return result


def _observatory_code_for(catalog_rel_path: str) -> str | None:
    parts = catalog_rel_path.split("/")
    for code, folder in config.OBSERVATORY_CODES.items():
        if folder in parts:
            return code
    return None


def _resolve(
    candidate: str,
    code: str,
    by_name: dict[str, list[str]],
    by_stem: dict[str, list[str]],
) -> tuple[str | None, str | None]:
    """Resuelve el nombre candidato contra el disco, probando las variantes conocidas."""
    lowered = candidate.lower()

    if hits := by_name.get(lowered):
        return hits[0], "exact"

    # ADVERTENCIA 2: 10 estudios de DAIO se guardaron como `DAIO_study23NN-2.pdf` por
    # colisión de nombre. Hay que probar ambas variantes.
    stem, dot, ext = lowered.rpartition(".")
    if dot:
        if hits := by_name.get(f"{stem}-2.{ext}"):
            return hits[0], "suffix-2"
        # Variante sin el prefijo de observatorio (o con él, si faltaba).
        bare = stem[len(code) + 1:] if stem.startswith(code.lower() + "_") else stem
        for probe in (bare, f"{code.lower()}_{bare}"):
            if hits := by_stem.get(probe):
                return hits[0], "prefix"

    return None, None


def assert_join(result: JoinResult, strict: bool = True) -> list[str]:
    """La tabla esperada es un TEST: cualquier desviación es un bug del join,
    no un dato nuevo."""
    problems: list[str] = []

    if result.total_refs != config.EXPECTED_CATALOG_TOTAL_REFS:
        problems.append(
            f"refs con URL de PDF: {result.total_refs}, "
            f"esperadas {config.EXPECTED_CATALOG_TOTAL_REFS}"
        )
    if result.resolved < config.EXPECTED_CATALOG_RESOLVED:
        problems.append(
            f"resueltas: {result.resolved}, esperadas ≥{config.EXPECTED_CATALOG_RESOLVED} "
            f"(sin resolver: {[r.candidate for r in result.unresolved]})"
        )

    for cat, expected in config.EXPECTED_CATALOG_RESOLUTION.items():
        got = result.per_catalog.get(cat)
        if got is None:
            problems.append(f"catálogo no procesado: {cat}")
            continue
        if got["refs"] != expected["refs"]:
            problems.append(
                f"{cat}: {got['refs']} refs, esperadas {expected['refs']}"
            )
        got_resolved = got["refs"] - got["unresolved"]
        if got_resolved != expected["resolved"]:
            problems.append(
                f"{cat}: {got_resolved} resueltas, esperadas {expected['resolved']}"
            )

    if problems and strict:
        raise AssertionError("Catalog join fallido:\n  - " + "\n  - ".join(problems))
    return problems
