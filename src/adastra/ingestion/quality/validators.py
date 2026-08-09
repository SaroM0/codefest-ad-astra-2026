"""Invariantes I1–I11. Cada una es un test automático sobre el resultado final."""

from __future__ import annotations

from adastra.core.models import CanonicalDocument, CorpusEntry


def validate_document(doc: CanonicalDocument, blocks: list) -> list[str]:
    """Invariantes por documento. Devuelve la lista de violaciones."""
    problems: list[str] = []

    # I8 — IDs únicos y orden monótono.
    ids = [b.block_id for b in blocks]
    if len(ids) != len(set(ids)):
        problems.append("I8: block_id duplicado")
    orders = [b.order for b in blocks]
    if orders != sorted(orders):
        problems.append("I8: orden de bloques no monótono")

    # I4 — ningún texto persistido contiene NUL.
    if any("\x00" in b.text for b in blocks):
        problems.append("I4: NUL en texto persistido")

    # Texto vacío: sólo legítimo en `table_row` con datos estructurados.
    for b in blocks:
        if not b.text.strip() and not (b.type == "table_row" and b.structured_data):
            problems.append(f"bloque vacío sin structured_data: {b.block_id}")
            break

    # I6 — todo documento recuperable lleva confianza con procedencia.
    if doc.quality.confidence.basis is None:
        problems.append("I6: confianza sin basis")

    # I5 — la paginación viene del inspector, no de contar form feeds.
    if doc.source.original_format == "pdf":
        if doc.quality.pages_total is None or doc.quality.pages_total < 1:
            problems.append("I5: pdf sin page_count válido")
        pages = {b.page for b in blocks if b.page is not None}
        if pages and doc.quality.pages_total and max(pages) > doc.quality.pages_total:
            problems.append(
                f"I5: bloque en página {max(pages)} > page_count "
                f"{doc.quality.pages_total}"
            )

    return problems


def validate_corpus(
    entries: list[CorpusEntry],
    documents_written: int,
    expected_total: int,
) -> list[str]:
    """Invariantes globales I1, I2, I3, I10."""
    problems: list[str] = []

    # I1 — todo archivo tiene rol y aparece en el reporte.
    if len(entries) != expected_total:
        problems.append(
            f"I1: {len(entries)} entradas registradas, esperadas {expected_total}"
        )

    # I3 — ningún DOC_ID del índice queda sin estado terminal.
    pending = [e.doc_id for e in entries if e.in_index and e.status == "pending"]
    if pending:
        problems.append(f"I3: {len(pending)} DOC_ID sin estado terminal: {pending[:5]}")

    # I7 — todo descarte tiene motivo.
    silent = [
        e.relative_path
        for e in entries
        if e.status in ("intentional_skip", "invalid_source", "failure")
        and not e.status_reason
    ]
    if silent:
        problems.append(f"I7: {len(silent)} descartes sin motivo: {silent[:5]}")

    # I10 — anti-leakage: nada de rol `evaluation` produce documento.
    leaked = [
        e.relative_path
        for e in entries
        if e.role == "evaluation" and e.status == "success"
    ]
    if leaked:
        problems.append(f"I10 LEAKAGE: artefactos de evaluación ingeridos: {leaked}")

    # Reconciliación de estados sobre los documentos del índice.
    in_index = [e for e in entries if e.in_index]
    by_status: dict[str, int] = {}
    for e in in_index:
        by_status[e.status] = by_status.get(e.status, 0) + 1
    total = sum(by_status.values())
    if total != len(in_index):
        problems.append(f"suma de estados {total} != {len(in_index)} del índice")

    success = by_status.get("success", 0)
    if documents_written != success:
        problems.append(
            f"documentos escritos ({documents_written}) != status=success ({success})"
        )

    return problems


def check_id_stability(
    documents: dict[str, list[tuple[str, str]]],
    previous: dict[str, list[tuple[str, str]]],
) -> list[str]:
    """Test de estabilidad de IDs: (block_id → sha256(text)) no debe cambiar entre
    corridas con la misma versión de pipeline.

    Sin esto, un cambio de segmentación renumera los bloques y las referencias guardadas
    por capas posteriores apuntan en silencio a otro contenido: no falla, miente.
    """
    problems: list[str] = []
    for doc_id, pairs in documents.items():
        old = previous.get(doc_id)
        if old is None:
            continue
        if dict(old) != dict(pairs):
            changed = [
                bid
                for bid, h in pairs
                if dict(old).get(bid) not in (None, h)
            ]
            problems.append(
                f"IDs inestables en {doc_id}: {len(changed)} bloques cambiaron de "
                f"contenido con el mismo block_id"
            )
    return problems
