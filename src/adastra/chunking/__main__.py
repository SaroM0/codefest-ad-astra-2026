"""CLI para el chunker mínimo."""
from __future__ import annotations

import argparse
from pathlib import Path

from .processor import write_chunks


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Chunking minimal")
    parser.add_argument("--artifacts", type=Path, default=None)
    parser.add_argument("--max-words", type=int, default=250)
    parser.add_argument("--overlap-words", type=int, default=50, help="overlap in words between consecutive chunks")
    parser.add_argument("--encoder", type=str, default="default", help="encoder name subfolder")
    args = parser.parse_args(argv)

    written = write_chunks(
        out_root=args.artifacts,
        max_words=args.max_words,
        overlap_words=args.overlap_words,
        encoder_name=args.encoder,
    )
    print(f"chunks written: {written}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
