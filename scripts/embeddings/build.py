"""CLI reproducible para construir embeddings e índice FAISS."""

from __future__ import annotations

import argparse
import json
from pathlib import Path

from adastra.embeddings.builder import (
    DEFAULT_BATCH_SIZE,
    DEFAULT_MAX_LENGTH,
    MODEL_NAME,
    build_vector_index,
)


def main() -> int:
    parser = argparse.ArgumentParser(description="Genera embeddings BGE-M3 e índice FAISS")
    parser.add_argument("--artifacts", type=Path, default=None, help="Raíz de artefactos")
    parser.add_argument("--model", default=MODEL_NAME, help="ID o snapshot local compatible con BGEM3FlagModel")
    parser.add_argument(
        "--model-reference",
        default=None,
        help="ID público del modelo si --model es una ruta local; se guarda en el manifiesto",
    )
    parser.add_argument("--batch-size", type=int, default=DEFAULT_BATCH_SIZE)
    parser.add_argument("--max-length", type=int, default=DEFAULT_MAX_LENGTH)
    parser.add_argument("--limit", type=int, default=None, help="Limita chunks; sólo para pruebas")
    parser.add_argument("--no-delivery-copy", action="store_true")
    args = parser.parse_args()

    manifest = build_vector_index(
        artifacts_root=args.artifacts,
        model_name=args.model,
        model_reference=args.model_reference,
        batch_size=args.batch_size,
        max_length=args.max_length,
        limit=args.limit,
        write_delivery_copy=not args.no_delivery_copy,
    )
    print(json.dumps(manifest, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())