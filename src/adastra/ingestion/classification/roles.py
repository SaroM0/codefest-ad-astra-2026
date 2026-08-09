"""Asignación de rol y de estado terminal.

Cuatro roles. El que más importa es `evaluation`: las 50 preguntas y el gold set deben
quedar FUERA del corpus recuperable (invariante I10). Un pipeline que los ingiera como
documentos normales contamina la evaluación con las respuestas.
"""

from __future__ import annotations

import re

from adastra.core.models import CorpusEntry

from .. import config
from .magic import detect_format, is_mismatch

_CATALOG_RE = re.compile(
    r"(_catalog[-_.]|_catalogo\.|_registro\.|-catalog\.|tiles-index)", re.IGNORECASE
)


def _is_catalog(entry: CorpusEntry) -> bool:
    if entry.extension not in (".json", ".csv"):
        return False
    return bool(_CATALOG_RE.search(entry.filename))


def classify(entry: CorpusEntry, magic: bytes) -> CorpusEntry:
    """Puebla `detected_format`, `role`, `status` e `indexing_hint` de una entrada."""
    if entry.role == "noise":
        return entry

    entry.detected_format = detect_format(magic, entry.extension)
    entry.format_mismatch = is_mismatch(entry.detected_format, entry.extension)

    rel = entry.relative_path

    # --- evaluation: I10, anti-leakage ------------------------------------------------
    if rel == config.QUESTIONS_PDF or rel == config.GOLD_SET_XLSX:
        entry.role = "evaluation"
        entry.role_reason = "challenge_artifact__must_not_enter_retrieval"
        entry.status = "intentional_skip"
        entry.status_reason = "evaluation_artifact"
        return entry

    # --- metadata: alimenta el catalog join, no produce documento ---------------------
    if rel == config.MASTER_INDEX:
        entry.role = "metadata"
        entry.role_reason = "master_index"
        entry.status = "intentional_skip"
        entry.status_reason = "master_index"
        return entry

    if _is_catalog(entry):
        entry.role = "metadata"
        entry.role_reason = "catalog_or_pipeline_registry__consumed_by_catalog_join"
        entry.status = "intentional_skip"
        entry.status_reason = "metadata_source"
        return entry

    # --- retrievable ------------------------------------------------------------------
    entry.role = "retrievable"
    entry.role_reason = "corpus_document"

    # Fuente inválida: los 2 HTML disfrazados de .pdf. Descargas fallidas, no
    # documentos HTML legítimos equivalentes al PDF: no se rescatan como contenido.
    if entry.extension == ".pdf" and entry.detected_format != "pdf":
        entry.status = "invalid_source"
        entry.status_reason = (
            f"declared_pdf_but_detected_{entry.detected_format}__failed_download"
        )
        return entry

    # Skips deliberados, cada uno con motivo (I7).
    if reason := config.SKIP_FILENAMES.get(entry.filename):
        entry.status = "intentional_skip"
        entry.status_reason = reason
        return entry

    if reason := config.SKIP_EXTENSIONS.get(entry.extension):
        entry.status = "intentional_skip"
        entry.status_reason = reason
        return entry

    # Señal para retrieval: los datasets bibliométricos no se responden recuperando una
    # fila suelta. Su valor es filtrado/agregación, no embedding.
    lowered = entry.filename.lower()
    if any(p in lowered for p in config.STRUCTURED_ONLY_PATTERNS):
        entry.indexing_hint = "structured_only"

    return entry


def assert_classification(entries: list[CorpusEntry], strict: bool = True) -> list[str]:
    """Comprueba las expectativas verificadas de la clasificación."""
    problems: list[str] = []

    invalid = {e.relative_path for e in entries if e.status == "invalid_source"}
    if invalid != set(config.KNOWN_INVALID_SOURCES):
        problems.append(
            "invalid_source no coincide con lo verificado.\n"
            f"    detectados: {sorted(invalid)}\n"
            f"    esperados : {sorted(config.KNOWN_INVALID_SOURCES)}"
        )

    n_eval = sum(1 for e in entries if e.role == "evaluation")
    if n_eval != 2:
        problems.append(f"evaluation: {n_eval} archivos, esperados 2")

    counts: dict[str, int] = {}
    for e in entries:
        counts[e.role] = counts.get(e.role, 0) + 1
    total = sum(counts.values())
    if total != config.EXPECTED_TOTAL_FILES:
        problems.append(
            f"I1: los roles suman {total}, esperado {config.EXPECTED_TOTAL_FILES}"
        )

    if problems and strict:
        raise AssertionError("Clasificación fallida:\n  - " + "\n  - ".join(problems))
    return problems
