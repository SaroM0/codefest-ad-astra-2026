"""Script de prueba rápido para el chunker (ubicado en scripts/chunking).

Prepara un documento de ejemplo bajo `artifacts/ingestion/documents/` y ejecuta
el chunker mínimo (`python -m adastra.chunking`). Imprime OK si el chunker
genera `artifacts/chunking/encoder_default/chunks.jsonl` y `metadata.jsonl`.
"""
from pathlib import Path
import json
import subprocess
import sys


ROOT = Path("artifacts")
DOCS = ROOT / "ingestion" / "documents"
DOCS.mkdir(parents=True, exist_ok=True)

doc = {
    "doc_id": "TEST-0001",
    "pipeline_version": "0.0",
    "source": {
        "phenomenon": "1",
        "observatory": "TEST",
        "observatory_code": "TST",
        "relative_path": "dummy.pdf",
        "original_format": "pdf",
        "published_date": "2023-01-01",
        "original_title": "Documento de prueba",
        "language": "es",
    },
    "blocks": [
        {
            "block_id": "b1",
            "type": "paragraph",
            "text": "Este es un párrafo de prueba. Contiene varias oraciones.",
            "order": 0,
            "extraction_method": "native_reading_order",
        },
        {
            "block_id": "b2",
            "type": "paragraph",
            "text": "Segundo párrafo de prueba para el chunker.",
            "order": 1,
            "extraction_method": "native_reading_order",
        },
    ],
    "quality": {"confidence": {"score": 1.0, "basis": "intrinsic_only"}, "usable": True},
}

path = DOCS / f"{doc['doc_id']}.json"
path.write_text(json.dumps(doc, ensure_ascii=False, indent=2), encoding="utf-8")

print("Wrote sample document:", path)

cmd = [sys.executable, "-m", "adastra.chunking", "--encoder", "default", "--artifacts", "artifacts"]
print("Running:", " ".join(cmd))
res = subprocess.run(cmd, capture_output=True, text=True)
print(res.stdout)
if res.returncode != 0:
    print(res.stderr, file=sys.stderr)
    raise SystemExit(2)

encoder_dir = ROOT / "chunking" / "encoder_default"
chunks = encoder_dir / "chunks.jsonl"
meta = encoder_dir / "metadata.jsonl"

if not (chunks.exists() and chunks.stat().st_size > 0):
    print("FAIL: no chunks produced", file=sys.stderr)
    raise SystemExit(1)

# Comprueba que no se hayan cortado oraciones: cada chunk debe acabar en
# puntuación final (., ?, !) o ser la última oración del bloque.
with chunks.open(encoding="utf-8") as f:
    bad = []
    for line in f:
        obj = json.loads(line)
        text = obj.get("texto", "")
        if not text:
            bad.append((obj.get("chunk_id"), "empty"))
            continue
        if text[-1] not in ".?!":
            # allow very short fragments
            if len(text.split()) > 3:
                bad.append((obj.get("chunk_id"), text[-20:]))

if bad:
    print("FAIL: some chunks end mid-sentence:", bad, file=sys.stderr)
    raise SystemExit(1)

if not (meta.exists() and meta.stat().st_size > 0):
    print("FAIL: metadata.jsonl missing", file=sys.stderr)
    raise SystemExit(1)

print("OK: chunks written ->", chunks)
print("OK: metadata written ->", meta)
raise SystemExit(0)
