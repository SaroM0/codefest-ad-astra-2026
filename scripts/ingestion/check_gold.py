#!/usr/bin/env python3
"""Contraste C6 — el test de aceptación de la extracción.

`FASE ORDENADA CODEFEST.xlsx` aporta 15 pares pregunta→fragmento→documento verificados.
Cada fragmento es literalmente una cita del texto que este pipeline debe producir: si no
aparece en el documento citado, la extracción perdió contenido.

Se usa SÓLO como assert. No entra al corpus, no se indexa, no ajusta ningún parámetro.
El emparejamiento se hace por TEXTO del fragmento, nunca por índice de pregunta: el gold
set usa dos numeraciones incompatibles (`2,3,4` en F1, `q0047`–`q0052` en F3) y ninguna
coincide con `q001`–`q050`.

Uso:  python scripts/ingestion/check_gold.py [--from-artifacts]

  sin flags        re-extrae los documentos citados (comprueba el parser actual)
  --from-artifacts lee de artifacts/ (comprueba lo que quedó realmente persistido)
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[2] / "src"))

from adastra.core.paths import ArtifactPaths  # noqa: E402
from adastra.ingestion import config  # noqa: E402
from adastra.ingestion.quality.crosschecks import check_gold_fragment  # noqa: E402
from adastra.ingestion.registry.catalog_join import nombre_estandarizado  # noqa: E402
from adastra.ingestion.registry.index_loader import load_gold_set, load_index  # noqa: E402

CORPUS = config.DEFAULT_CORPUS
DOCS = ArtifactPaths().documents

G, Y, R, B, DIM, END = "\033[32m", "\033[33m", "\033[31m", "\033[1m", "\033[2m", "\033[0m"


def resolve(gold: list[dict], records) -> tuple[dict, list[dict]]:
    """Resuelve la cita del gold set al archivo real aplicando la regla de renombrado.

    El gold set cita nombres del servidor (`daio_study2529_guarding...pdf`) y el corpus
    almacena `DAIO_study2529-guarding-...pdf`.
    """
    by_name: dict[str, object] = {}
    for r in records:
        by_name.setdefault(r.filename.lower(), r)

    resolved: dict[str, list[dict]] = {}
    unresolved: list[dict] = []
    for pair in gold:
        name = pair.get("document") or ""
        rec = by_name.get(name.lower())
        if rec is None:
            for code in config.OBSERVATORY_CODES:
                candidate = nombre_estandarizado(f"http://x/{name}", code)
                if hit := by_name.get(candidate.lower()):
                    rec = hit
                    break
        if rec is None:
            unresolved.append(pair)
        else:
            resolved.setdefault(rec.relative_path, []).append(pair)  # type: ignore[attr-defined]
    return resolved, unresolved


def text_from_artifacts(rel: str, records) -> str | None:
    doc_id = next((r.doc_id for r in records if r.relative_path == rel), None)
    if not doc_id:
        return None
    path = DOCS / f"{doc_id}.json"
    if not path.exists():
        return None
    doc = json.loads(path.read_text(encoding="utf-8"))
    if ref := doc.get("blocks_ref"):
        blocks = [json.loads(l) for l in (DOCS / ref).open(encoding="utf-8") if l.strip()]
    else:
        blocks = doc.get("blocks") or []
    return "\n\n".join(b["text"] for b in blocks)


def text_from_parser(rel: str) -> str:
    from adastra.ingestion.parsers.pdf.parser import parse_pdf

    result = parse_pdf(CORPUS / rel, "GOLD", config.PIPELINE_VERSION, enable_ocr=False)
    return "\n\n".join(b.text for b in result.blocks)


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--from-artifacts", action="store_true")
    args = ap.parse_args()

    records = load_index(CORPUS / config.MASTER_INDEX, config.INVENTORY_SHEET)
    gold = load_gold_set(CORPUS / config.GOLD_SET_XLSX)
    resolved, unresolved = resolve(gold, records)

    source = "artifacts/" if args.from_artifacts else "parser en vivo"
    print(f"{B}C6 · gold set{END}  {DIM}({source}){END}")
    print(f"  {len(gold)} pares · {len(resolved)} documentos citados"
          + (f" · {R}{len(unresolved)} sin resolver{END}" if unresolved else ""))
    for pair in unresolved:
        print(f"    {R}✗{END} sin resolver: {pair['document']}")

    exact = partial = failed = missing = 0
    print()
    for rel, pairs in resolved.items():
        text = text_from_artifacts(rel, records) if args.from_artifacts else text_from_parser(rel)
        if text is None:
            missing += len(pairs)
            print(f"  {Y}?{END} sin artefacto para {Path(rel).name[:52]}")
            continue
        for pair in pairs:
            check = check_gold_fragment(pair["fragment"], text)
            if check.score is not None and check.score >= 0.95:
                exact += 1
                mark, colour = "✓", G
            elif check.passed:
                partial += 1
                mark, colour = "~", Y
            else:
                failed += 1
                mark, colour = "✗", R
            print(f"  {colour}{mark}{END} score={check.score:<7} "
                  f"{pair['sheet']}/{pair.get('question_id') or '-':<7} "
                  f"{Path(rel).name[:46]}")
            if not check.passed:
                print(f"      {DIM}{pair['fragment'][:110]}…{END}")

    total = exact + partial + failed + missing
    print(f"\n  {G}exactos {exact}{END} · {Y}parciales {partial}{END} · "
          f"{R}fallos {failed}{END}" + (f" · {Y}sin artefacto {missing}{END}" if missing else "")
          + f"  (de {total})")

    if failed or unresolved:
        print(f"\n  {R}C6 FALLA: la extracción pierde contenido citado por el gold set.{END}")
        return 1
    print(f"\n  {G}C6 PASA: todos los fragmentos citados aparecen en su documento.{END}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
