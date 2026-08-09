"""Leer lo que la ingesta dejó escrito. Es la puerta de entrada del chunking.

Hay una trampa concreta que este módulo existe para tapar. Un documento canónico
guarda sus bloques de dos formas distintas según el tamaño:

    blocks     = [...]                    inline, si son ≤ 1.000
    blocks_ref = "F1-AIINDEX-056.blocks.jsonl"   aparte, si son más

Quien lea `doc["blocks"]` directamente funcionará con el 99% del corpus y devolverá
`None` justo en los documentos grandes — que son precisamente los que más contenido
aportan. El fallo es silencioso: no lanza, simplemente pierde 111.775 bloques.

Por eso `iter_blocks()` es la única forma soportada de acceder a los bloques, y es
un **generador**: el caso grande no cabe cómodamente en memoria y no debería.
"""

from __future__ import annotations

import json
from collections.abc import Iterator
from pathlib import Path

from .jsonl import read_jsonl
from .models import CanonicalDocument, ContentBlock
from .paths import ArtifactPaths


def document_path(doc_id: str, paths: ArtifactPaths | None = None) -> Path:
    return (paths or ArtifactPaths()).documents / f"{doc_id}.json"


def load_document(doc_id: str, paths: ArtifactPaths | None = None) -> CanonicalDocument:
    """Carga un documento por DOC_ID. Los bloques se leen con `iter_blocks`."""
    path = document_path(doc_id, paths)
    if not path.exists():
        raise FileNotFoundError(f"No existe {path}. ¿Has ejecutado `make ingest`?")
    return CanonicalDocument.model_validate_json(path.read_text(encoding="utf-8"))


def iter_document_ids(paths: ArtifactPaths | None = None) -> Iterator[str]:
    """DOC_IDs presentes en disco, en orden estable.

    Filtra `.blocks.jsonl` con el sufijo completo, no con `"blocks" in name`: un
    DOC_ID puede contener cualquier cosa y el glob `*.json` no casa `.blocks.jsonl`,
    pero conviene no depender de esa sutileza.
    """
    documents = (paths or ArtifactPaths()).documents
    if not documents.is_dir():
        return
    for path in sorted(documents.glob("*.json")):
        if not path.name.endswith(".blocks.jsonl"):
            yield path.stem


def iter_documents(paths: ArtifactPaths | None = None) -> Iterator[CanonicalDocument]:
    """Recorre el corpus canónico completo, un documento cada vez."""
    for doc_id in iter_document_ids(paths):
        yield load_document(doc_id, paths)


def iter_blocks(
    doc: CanonicalDocument, paths: ArtifactPaths | None = None
) -> Iterator[ContentBlock]:
    """Los bloques de un documento, vengan inline o de su `.blocks.jsonl`.

    ÚSALO SIEMPRE en vez de `doc.blocks`. Ver la nota de cabecera del módulo.
    """
    if doc.blocks is not None:
        yield from doc.blocks
        return

    if doc.blocks_ref is None:
        return  # documento sin bloques: legítimo (p.ej. cuarentena parcial)

    external = (paths or ArtifactPaths()).documents / doc.blocks_ref
    if not external.exists():
        raise FileNotFoundError(
            f"{doc.doc_id} declara blocks_ref={doc.blocks_ref!r} pero {external} no "
            f"existe. Los artefactos están incompletos: re-ejecuta la ingesta."
        )
    for row in read_jsonl(external):
        yield ContentBlock.model_validate(row)


def load_summary(paths: ArtifactPaths | None = None) -> dict:
    """El resumen operativo de la última corrida de ingesta."""
    path = (paths or ArtifactPaths()).summary
    if not path.exists():
        raise FileNotFoundError(f"No existe {path}. ¿Has ejecutado `make ingest`?")
    return json.loads(path.read_text(encoding="utf-8"))
