#!/usr/bin/env python3
"""Auditoría de fidelidad: ¿el texto persistido conserva lo que ve poppler?

Compara, PDF a PDF, los caracteres **no-espacio y sin controles** de los bloques
canónicos contra los de `pdftotext`. Esa normalización es la que hace la comparación
honesta:

  · sin espacios, porque `-layout` acolcha cada línea con relleno para preservar
    posiciones físicas (un informe de RESDAL pasa de 27.515 a 56.871 caracteres siendo
    el mismo texto);
  · sin caracteres de control, porque los informes de ESA vienen contaminados con miles
    de bytes C0 y los PDFs árabes con controles bidi, y ninguno de los dos es texto.

Uso:  python scripts/ingestion/audit_extraction.py [--threshold 0.95] [--workers 10]
"""

from __future__ import annotations

import argparse
import json
import subprocess
import sys
from concurrent.futures import ProcessPoolExecutor, as_completed
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[2] / "src"))

from adastra.core.paths import ArtifactPaths  # noqa: E402
from adastra.ingestion import config  # noqa: E402

PATHS = ArtifactPaths()
CORPUS = config.DEFAULT_CORPUS
DOCS = PATHS.documents
MANIFEST = PATHS.manifest

G, Y, R, B, DIM, END = "\033[32m", "\033[33m", "\033[31m", "\033[1m", "\033[2m", "\033[0m"


def normalize(text: str) -> str:
    """Sólo lo que es texto: sin espacios y sin caracteres de control."""
    kept = (c for c in text if c == "\n" or c == "\t" or ord(c) >= 32)
    return "".join("".join(kept).split())


def reference_chars(rel: str) -> tuple[str, int]:
    """El mejor de los dos modos de poppler: lo máximo que se podía haber extraído."""
    path = CORPUS / rel
    best = 0
    for args in (
        ["pdftotext", "-layout", "-enc", "UTF-8", str(path), "-"],
        ["pdftotext", "-enc", "UTF-8", str(path), "-"],
    ):
        try:
            out = subprocess.run(args, capture_output=True, timeout=900).stdout
        except (subprocess.SubprocessError, OSError):
            continue
        best = max(best, len(normalize(out.decode("utf-8", "replace"))))
    return rel, best


def load_blocks(doc_id: str) -> list[dict]:
    path = DOCS / f"{doc_id}.json"
    doc = json.loads(path.read_text(encoding="utf-8"))
    if ref := doc.get("blocks_ref"):
        return [json.loads(l) for l in (DOCS / ref).open(encoding="utf-8") if l.strip()]
    return doc.get("blocks") or []


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--threshold", type=float, default=0.95)
    ap.add_argument("--workers", type=int, default=10)
    ap.add_argument("--json", type=Path, default=None, help="volcar el detalle")
    args = ap.parse_args()

    if not MANIFEST.exists():
        print(f"{R}No existe {MANIFEST}. Ejecuta `make ingest` primero.{END}", file=sys.stderr)
        return 1

    manifest = [json.loads(l) for l in MANIFEST.open(encoding="utf-8") if l.strip()]
    pdfs = [
        m for m in manifest
        if m["input_format"] == "pdf" and m["role"] == "retrievable" and m["status"] == "success"
    ]
    if not pdfs:
        print(f"{Y}No hay PDFs procesados con éxito que auditar.{END}")
        return 0

    print(f"{B}Auditando {len(pdfs)} PDFs…{END}")

    mine = {m["relative_path"]: len(normalize("".join(b["text"] for b in load_blocks(m["doc_id"]))))
            for m in pdfs}

    ref: dict[str, int] = {}
    with ProcessPoolExecutor(max_workers=args.workers) as pool:
        futures = [pool.submit(reference_chars, m["relative_path"]) for m in pdfs]
        for i, future in enumerate(as_completed(futures), 1):
            rel, n = future.result()
            ref[rel] = n
            if i % 150 == 0:
                print(f"  {DIM}{i}/{len(futures)}{END}", flush=True)

    total_ref = sum(ref.values())
    total_mine = sum(mine.get(k, 0) for k in ref)
    fidelity = total_mine / total_ref if total_ref else 1.0

    colour = G if fidelity >= 0.99 else (Y if fidelity >= 0.95 else R)
    print(f"\n{B}FIDELIDAD GLOBAL{END}")
    print(f"  referencia (poppler)  {total_ref:>14,}")
    print(f"  extraído (bloques)    {total_mine:>14,}")
    print(f"  {colour}fidelidad             {fidelity * 100:>13.2f}%{END}")

    low = [(k, ref[k], mine.get(k, 0)) for k in ref
           if ref[k] > 2000 and mine.get(k, 0) / ref[k] < args.threshold]
    low.sort(key=lambda x: x[2] / x[1])

    below = R if low else G
    print(f"\n  {below}documentos por debajo del {args.threshold:.0%}: "
          f"{len(low)} de {len(ref)}{END}")
    for rel, r, m in low[:25]:
        print(f"    {m / r * 100:>6.1f}%  ref={r:>9,} ext={m:>9,}  {Path(rel).name[:52]}")

    if args.json:
        args.json.parent.mkdir(parents=True, exist_ok=True)
        args.json.write_text(json.dumps({
            "total_reference": total_ref, "total_extracted": total_mine,
            "fidelity": round(fidelity, 6), "threshold": args.threshold,
            "below_threshold": [{"path": k, "reference": r, "extracted": m,
                                 "ratio": round(m / r, 4)} for k, r, m in low],
        }, ensure_ascii=False, indent=2), encoding="utf-8")
        print(f"\n  {DIM}detalle → {args.json}{END}")

    # Falla si se pierde más del 1% del texto del corpus.
    return 0 if fidelity >= 0.99 else 1


if __name__ == "__main__":
    raise SystemExit(main())
