#!/usr/bin/env python3
"""Extrae los DOC_ID con algún contraste fallido, para el reintento dirigido.

    python scripts/ingestion/failed_docs.py                  # lista a stdout
    python scripts/ingestion/failed_docs.py --diagnose       # además, agrupa por causa

Se usa como entrada de `make retry`, que sólo reprocesa esos documentos.
"""

from __future__ import annotations

import argparse
import collections
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[2] / "src"))

from adastra.core.jsonl import read_jsonl  # noqa: E402
from adastra.core.paths import ArtifactPaths  # noqa: E402

PATHS = ArtifactPaths()
DOCS = PATHS.documents


def failed() -> list[tuple[str, dict, list[dict]]]:
    out: list[tuple[str, dict, list[dict]]] = []
    for m in read_jsonl(PATHS.manifest):
        doc_id = m.get("doc_id")
        if not doc_id or m.get("status") not in ("success", "quarantined"):
            continue
        path = DOCS / f"{doc_id}.json"
        if not path.exists():
            if m.get("status") == "quarantined":
                out.append((doc_id, m, []))
            continue
        d = json.loads(path.read_text(encoding="utf-8"))
        bad = [c for c in d["quality"]["confidence"].get("crosschecks") or [] if not c["passed"]]
        if bad or d["quality"]["confidence"]["basis"] == "unverified":
            out.append((doc_id, m, bad))
    return out


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--diagnose", action="store_true")
    args = ap.parse_args()

    rows = failed()
    if not args.diagnose:
        print("\n".join(doc_id for doc_id, _, _ in rows))
        return 0

    print(f"{len(rows)} documentos con contraste fallido o sin verificar\n")
    by_type: collections.Counter[str] = collections.Counter()
    by_obs: collections.Counter[str] = collections.Counter()
    for doc_id, m, bad in rows:
        by_obs[m["relative_path"].split("/")[1]] += 1
        for c in bad:
            by_type[c["type"]] += 1
        if not bad:
            by_type["unverified"] += 1
    print("por tipo de contraste: ", dict(by_type))
    print("por observatorio:      ", dict(by_obs.most_common(10)))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
