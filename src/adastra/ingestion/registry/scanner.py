"""Escaneo del filesystem, independiente del índice.

Deliberadamente ciego al índice: sólo así la reconciliación puede detectar discrepancias
en ambas direcciones (archivos del índice que no están en disco, y archivos en disco que
el índice no declara).
"""

from __future__ import annotations

import hashlib
from dataclasses import dataclass
from pathlib import Path

_HASH_CHUNK = 1 << 20


@dataclass(frozen=True)
class ScannedFile:
    relative_path: str
    filename: str
    extension: str
    size_bytes: int
    sha256: str
    magic: bytes


def sha256_of(path: Path) -> str:
    h = hashlib.sha256()
    with path.open("rb") as f:
        while chunk := f.read(_HASH_CHUNK):
            h.update(chunk)
    return h.hexdigest()


def scan_corpus(root: Path) -> list[ScannedFile]:
    """Devuelve los 1.848 archivos del disco, con hash y magic bytes."""
    files: list[ScannedFile] = []
    for path in sorted(root.rglob("*")):
        if not path.is_file() or path.is_symlink():
            continue
        rel = path.relative_to(root).as_posix()
        try:
            with path.open("rb") as f:
                magic = f.read(16)
            files.append(
                ScannedFile(
                    relative_path=rel,
                    filename=path.name,
                    extension=path.suffix.lower(),
                    size_bytes=path.stat().st_size,
                    sha256=sha256_of(path),
                    magic=magic,
                )
            )
        except OSError as exc:  # I7: nada desaparece en silencio, ni un error de E/S
            raise RuntimeError(f"No se pudo leer {rel}: {exc}") from exc
    return files
