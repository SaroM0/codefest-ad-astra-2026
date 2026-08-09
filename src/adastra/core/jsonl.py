"""JSONL: el formato de intercambio entre etapas.

Se usa JSONL y no JSON para todo lo que crece con el corpus (manifest, registry,
bloques, chunks, resultados de retrieval) por una razón concreta: se puede escribir
incrementalmente y leer en streaming. `F1-AIINDEX-056` es un solo DOC_ID con 111.775
bloques; en JSON habría que cargar los 111.775 para mirar el primero.

`read_jsonl` es un generador **a propósito**. Si lo que necesitas es una lista, pide
`load_jsonl` explícitamente y asume el coste.
"""

from __future__ import annotations

import json
from collections.abc import Iterable, Iterator
from pathlib import Path
from typing import Any, TextIO


def dump_line(payload: Any) -> str:
    """Serializa a una línea JSONL. Acepta modelos pydantic y dicts indistintamente."""
    if hasattr(payload, "model_dump_json"):
        return payload.model_dump_json(exclude_none=True)
    return json.dumps(payload, ensure_ascii=False, default=str)


def read_jsonl(path: Path | str) -> Iterator[dict]:
    """Lee un JSONL en streaming. Un fichero ausente se lee como vacío.

    Ausente == vacío porque los artefactos opcionales (warnings, failures) sólo se
    crean cuando hay algo que reportar: obligar a cada consumidor a comprobar la
    existencia es la vía rápida a un `FileNotFoundError` en el peor momento.
    """
    path = Path(path)
    if not path.exists():
        return
    with path.open(encoding="utf-8") as handle:
        for line in handle:
            line = line.strip()
            if line:
                yield json.loads(line)


def load_jsonl(path: Path | str) -> list[dict]:
    """Igual que `read_jsonl`, materializado. Úsalo sólo si necesitas la lista."""
    return list(read_jsonl(path))


def write_jsonl(path: Path | str, rows: Iterable[Any]) -> int:
    """Escribe un JSONL completo, creando los directorios que falten. Devuelve filas."""
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    written = 0
    with path.open("w", encoding="utf-8") as handle:
        for row in rows:
            handle.write(dump_line(row) + "\n")
            written += 1
    return written


def write_line(handle: TextIO, payload: Any) -> None:
    """Añade una línea a un JSONL ya abierto."""
    handle.write(dump_line(payload) + "\n")
