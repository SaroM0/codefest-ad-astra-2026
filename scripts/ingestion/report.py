#!/usr/bin/env python3
"""Lectura humana de los artefactos de ingesta.

    python scripts/ingestion/report.py summary      resumen operativo + invariantes
    python scripts/ingestion/report.py coverage     matriz de cobertura de verificación
    python scripts/ingestion/report.py quarantine   qué no se pudo extraer y por qué
    python scripts/ingestion/report.py warnings     avisos agregados
    python scripts/ingestion/report.py doc <ID>     un documento canónico en detalle
    python scripts/ingestion/report.py find <texto> buscar documentos por ruta o título
"""

from __future__ import annotations

import json
import sys
from collections import Counter
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[2] / "src"))

from adastra.core.jsonl import load_jsonl as _jsonl  # noqa: E402
from adastra.core.paths import ArtifactPaths  # noqa: E402

PATHS = ArtifactPaths()
ART = PATHS.ingestion.root
DOCS = PATHS.documents

G, Y, R, B, DIM, END = "\033[32m", "\033[33m", "\033[31m", "\033[1m", "\033[2m", "\033[0m"


def _fail(msg: str) -> None:
    print(f"{R}{msg}{END}", file=sys.stderr)
    raise SystemExit(1)


def _load(path: Path) -> dict:
    if not path.exists():
        _fail(f"No existe {path}. ¿Has ejecutado `make ingest`?")
    return json.loads(path.read_text(encoding="utf-8"))


def _rule(title: str) -> None:
    print(f"\n{B}{title}{END}\n{DIM}{'─' * 72}{END}")


# ---------------------------------------------------------------------------------
def summary() -> int:
    s = _load(ART / "reports" / "summary.json")

    _rule("INVARIANTES")
    problems = s.get("invariant_problems") or {}
    if problems:
        for scope, items in problems.items():
            for item in items:
                print(f"  {R}✗{END} [{scope}] {item}")
    else:
        print(f"  {G}✓ las 11 invariantes se cumplen{END}")

    _rule("RECONCILIACIÓN")
    c = s["corpus"]
    print(f"  disco {c['files_on_disk']} = índice {c['in_master_index']}"
          f" + extras {c['extras_explained']} + ruido {c['noise']}")
    total = sum(s["status"].values())
    for status, n in sorted(s["status"].items(), key=lambda x: -x[1]):
        colour = G if status == "success" else (Y if status != "failure" else R)
        print(f"    {colour}{status:<20}{END}{n:>6}")
    print(f"    {'suma':<20}{total:>6}  (índice: {c['in_master_index']})")

    _rule("EXTRACCIÓN")
    print(f"  documentos escritos      {s['documents_written']:>8,}")
    p = s.get("pdf", {})
    if p:
        print(f"  páginas PDF              {p['pages_total']:>8,}")
        print(f"    nativas                {p['pages_native']:>8,}")
        print(f"    OCR aplicado           {p['pages_ocr_applied']:>8,}")
        flagged = p["pages_flagged_for_ocr_not_applied"]
        mark = R if flagged else G
        print(f"    {mark}marcadas sin OCR       {flagged:>8,}{END}")
        print(f"  modo orden de lectura    {p['pages_reading_order_mode']:>8,}")
        print(f"  modo layout (tablas)     {p['pages_layout_mode']:>8,}")

    _rule("IDIOMAS")
    print("  " + " · ".join(f"{k} {v}" for k, v in s["languages"].items()))

    _rule("CALIDAD")
    conf = s["quality"]["confidence"]
    print(f"  confianza  mediana {conf['median']}  media {conf['mean']}"
          f"  p25 {conf['p25']}  min {conf['min']}")
    coverage(indent=True)

    if s.get("warnings"):
        _rule("AVISOS (top 10)")
        for k, v in list(s["warnings"].items())[:10]:
            print(f"  {v:>6}  {k}")

    print(f"\n{DIM}duración {s['duration_s']}s · pipeline {s['pipeline_version']}{END}")
    return 1 if problems else 0


def coverage(indent: bool = False) -> int:
    s = _load(ART / "reports" / "summary.json")
    cov = s["quality"]["coverage"]
    if not indent:
        _rule("COBERTURA DE VERIFICACIÓN")
    total = sum(v for k, v in cov.items() if k != "by_basis")
    rows = [
        ("contraste fuerte (C3 entidades / C6 gold)", cov["verified_strong_crosscheck"], G),
        ("contraste débil (C1 OCR / C2 título / C4-C5 espejo)", cov["verified_weak_crosscheck"], G),
        ("sólo señales intrínsecas", cov["intrinsic_signals_only"], Y),
        ("SIN VERIFICAR", cov["unverified"], R),
    ]
    for label, n, colour in rows:
        pct = n / total * 100 if total else 0
        bar = "█" * int(pct / 3)
        print(f"  {colour}{label:<52}{n:>6}  {pct:>5.1f}% {bar}{END}")
    return 0


def quarantine() -> int:
    rows = _jsonl(ART / "quarantine" / "quarantine.jsonl")
    _rule(f"CUARENTENA — {len(rows)} documentos")
    if not rows:
        print(f"  {G}ninguno{END}")
        return 0
    print(f"  {DIM}«no confío en esta extracción» — no es exclusión permanente{END}\n")
    for action, n in Counter(r["recommended_action"] for r in rows).most_common():
        print(f"  acción recomendada · {action:<10}{n:>5}")
    print()
    for reason, n in Counter(r["reason"] for r in rows).most_common(10):
        print(f"  {n:>5}  {reason[:88]}")
    print(f"\n{DIM}  detalle completo: {ART}/quarantine/quarantine.jsonl{END}")
    return 0


def warnings() -> int:
    rows = _jsonl(ART / "reports" / "warnings.jsonl")
    _rule(f"AVISOS — {len(rows)} registros")
    counts: Counter[str] = Counter()
    for r in rows:
        if w := r.get("warning"):
            counts[w.split(":")[0]] += 1
        elif r.get("invariant_violations"):
            counts["invariant_violation"] += 1
    for k, v in counts.most_common(25):
        print(f"  {v:>6}  {k}")
    return 0


def doc(doc_id: str) -> int:
    path = DOCS / f"{doc_id}.json"
    if not path.exists():
        _fail(f"No existe {path}")
    d = json.loads(path.read_text(encoding="utf-8"))

    _rule(f"{d['doc_id']}  ({d['source']['observatory']})")
    src = d["source"]
    for key in ("relative_path", "original_format", "source_url", "original_title",
                "published_date", "date_confidence", "language", "dominant_script"):
        if src.get(key) is not None:
            print(f"  {key:<20} {src[key]}")

    q = d["quality"]
    conf = q["confidence"]
    colour = G if conf["score"] >= 0.7 else (Y if conf["score"] >= 0.35 else R)
    print(f"\n  {B}confianza{END}            {colour}{conf['score']}{END}  "
          f"(basis: {conf['basis']}, usable: {q['usable']})")
    if conf.get("flags"):
        print(f"  flags                {', '.join(conf['flags'])}")
    for check in conf.get("crosschecks", []):
        mark = f"{G}✓{END}" if check["passed"] else f"{R}✗{END}"
        print(f"    {mark} {check['type']:<20} score={check.get('score')}  {check.get('detail')}")

    print(f"\n  bloques              {d['block_count']:,}"
          + (f"  → {d['blocks_ref']}" if d.get("blocks_ref") else ""))
    print(f"  caracteres           {q['characters']:,}")
    if q.get("pages_total"):
        print(f"  páginas              {q['pages_total']} "
              f"(nativas {q['pages_native']}, OCR {q['pages_ocr']})")
    print(f"  indexing_hint        {d['indexing_hint']}")

    if d.get("metadata"):
        print(f"\n  {B}metadata{END}")
        print("    " + json.dumps(d["metadata"], ensure_ascii=False, indent=2)[:700]
              .replace("\n", "\n    "))

    blocks = d.get("blocks")
    if blocks is None and d.get("blocks_ref"):
        blocks = [json.loads(l) for l in (DOCS / d["blocks_ref"]).open(encoding="utf-8")][:5]
    if blocks:
        print(f"\n  {B}primeros bloques{END}")
        for b in blocks[:5]:
            bp = " [boilerplate]" if b.get("is_boilerplate") else ""
            print(f"    {DIM}{b['type']:<11} p{b.get('page') or '-'} "
                  f"conf={b['segmentation_confidence']} {b['extraction_method']}{bp}{END}")
            print(f"      {b['text'][:150].replace(chr(10), ' ')}")
    return 0


def find(needle: str) -> int:
    rows = _jsonl(ART / "manifest.jsonl")
    hits = [r for r in rows if needle.lower() in (r.get("relative_path") or "").lower()
            or needle.lower() in (r.get("doc_id") or "").lower()]
    _rule(f"{len(hits)} coincidencias para «{needle}»")
    for r in hits[:40]:
        colour = G if r["status"] == "success" else Y
        conf = r.get("extraction_confidence")
        print(f"  {colour}{r['status']:<16}{END}{r.get('doc_id') or '-':<20}"
              f"conf={conf if conf is not None else '-':<8}{Path(r['relative_path']).name[:48]}")
    if len(hits) > 40:
        print(f"  {DIM}… y {len(hits) - 40} más{END}")
    return 0


COMMANDS = {
    "summary": summary, "coverage": coverage, "quarantine": quarantine,
    "warnings": warnings,
}


def main(argv: list[str]) -> int:
    if not argv or argv[0] in ("-h", "--help", "help"):
        print(__doc__)
        return 0
    cmd, *rest = argv
    if cmd == "doc":
        return doc(rest[0]) if rest else _fail("uso: report.py doc <DOC_ID>") or 1
    if cmd == "find":
        return find(rest[0]) if rest else _fail("uso: report.py find <texto>") or 1
    if cmd not in COMMANDS:
        _fail(f"comando desconocido: {cmd}\n{__doc__}")
    return COMMANDS[cmd]()


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))
