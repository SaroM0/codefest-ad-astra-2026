"""Chunking determinista para la etapa 2.

La ingesta ya resolvió el formato, el orden de lectura, la calidad y la procedencia.
Este módulo consume `CanonicalDocument` y produce fragmentos listos para embeddings,
sin volver a tocar OCR, parsing ni limpieza destructiva.
"""

from __future__ import annotations

import argparse
import json
import re
import sys
from collections.abc import Iterator
from dataclasses import dataclass, replace
from pathlib import Path

from pydantic import BaseModel, Field

from adastra.core.documents import iter_blocks, iter_documents
from adastra.core.jsonl import write_line
from adastra.core.models import CanonicalDocument, ContentBlock
from adastra.core.paths import ArtifactPaths

DEFAULT_MAX_WORDS = 220
DEFAULT_MIN_WORDS = 40

_WORD_RE = re.compile(r"\w+|[^\w\s]", re.UNICODE)
_SENTENCE_ENDINGS = ".!?。！？"
_QUOTE_CHARS = '"\'”’»)]}'
_ABBREVIATIONS = {
    "dr.",
    "mr.",
    "mrs.",
    "ms.",
    "sr.",
    "sra.",
    "prof.",
    "inc.",
    "ltd.",
    "etc.",
    "e.g.",
    "i.e.",
    "fig.",
    "al.",
    "no.",
    "art.",
    "vol.",
    "p.",
    "pp.",
}


class ChunkRecord(BaseModel):
    """Registro persistido por la etapa 2."""

    doc_id: str
    chunk_id: str
    fuente: str
    formato: str
    fenomeno: int
    posicion: int
    num_tokens: int
    texto: str

    block_ids: list[str] = Field(default_factory=list)
    block_types: list[str] = Field(default_factory=list)
    page_start: int | None = None
    page_end: int | None = None
    source_language: str | None = None
    source_script: str | None = None


@dataclass(frozen=True)
class ChunkStats:
    documents_seen: int = 0
    documents_chunked: int = 0
    documents_skipped_structured_only: int = 0
    documents_empty: int = 0
    chunks_written: int = 0
    oversize_units: int = 0


def _source_label(doc: CanonicalDocument) -> str:
    return doc.source.source_url or doc.source.original_filename or doc.source.relative_path


def _phenomenon_number(value: str) -> int:
    digits = "".join(ch for ch in str(value) if ch.isdigit())
    if digits in {"1", "2", "3"}:
        return int(digits)
    raise ValueError(f"Fenómeno inválido: {value!r}")


def _token_count(text: str) -> int:
    return sum(1 for piece in _WORD_RE.findall(text) if piece.strip())


def _split_paragraphs(text: str) -> list[str]:
    parts = [part.strip() for part in re.split(r"\n\s*\n+", text.strip())]
    return [part for part in parts if part]


def _looks_like_abbreviation(text: str, terminator_index: int) -> bool:
    window_start = max(0, terminator_index - 12)
    window = text[window_start : terminator_index + 1].lower().strip()
    if any(window.endswith(abbrev) for abbrev in _ABBREVIATIONS):
        return True
    if re.search(r"([A-Za-zÁÉÍÓÚÜÑáéíóúüñ]{1,3}\.)$", window):
        return True
    return False


def _split_sentences(text: str) -> list[str]:
    sentences: list[str] = []
    start = 0
    index = 0
    length = len(text)

    while index < length:
        char = text[index]
        if char in _SENTENCE_ENDINGS and not _looks_like_abbreviation(text, index):
            end = index + 1
            while end < length and text[end] in _QUOTE_CHARS:
                end += 1
            if end >= length or text[end].isspace():
                next_start = end
                while next_start < length and text[next_start].isspace():
                    next_start += 1
                sentence = text[start:next_start].strip()
                if sentence:
                    sentences.append(sentence)
                start = next_start
                index = next_start
                continue
        index += 1

    tail = text[start:].strip()
    if tail:
        sentences.append(tail)
    return sentences


def _split_unit(text: str, max_words: int) -> tuple[list[str], int]:
    paragraphs = _split_paragraphs(text)
    if len(paragraphs) > 1:
        pieces: list[str] = []
        oversize = 0
        for paragraph in paragraphs:
            sub_pieces, sub_oversize = _split_unit(paragraph, max_words)
            pieces.extend(sub_pieces)
            oversize += sub_oversize
        return pieces, oversize

    if _token_count(text) <= max_words:
        return [text.strip()], 0

    sentences = _split_sentences(text)
    if len(sentences) == 1:
        return [text.strip()], 1

    pieces: list[str] = []
    current: list[str] = []
    current_words = 0
    oversize = 0

    for sentence in sentences:
        sentence_words = _token_count(sentence)
        if sentence_words > max_words:
            if current:
                pieces.append(" ".join(current).strip())
                current = []
                current_words = 0
            pieces.append(sentence.strip())
            oversize += 1
            continue

        if current and current_words + sentence_words > max_words:
            pieces.append(" ".join(current).strip())
            current = [sentence.strip()]
            current_words = sentence_words
            continue

        current.append(sentence.strip())
        current_words += sentence_words

    if current:
        pieces.append(" ".join(current).strip())

    return [piece for piece in pieces if piece], oversize


def _iter_blocks_for_chunking(
    doc: CanonicalDocument, paths: ArtifactPaths
) -> Iterator[ContentBlock]:
    for block in iter_blocks(doc, paths):
        if not block.text.strip():
            continue
        if block.is_boilerplate and block.type != "heading":
            continue
        yield block


def _flush_current(
    current_text: list[str],
    current_block_ids: list[str],
    current_block_types: list[str],
    current_pages: list[int],
    doc: CanonicalDocument,
    position: int,
) -> ChunkRecord | None:
    if not current_text:
        return None

    texto = "\n\n".join(part.strip() for part in current_text if part.strip()).strip()
    if not texto:
        return None

    page_start = min(current_pages) if current_pages else None
    page_end = max(current_pages) if current_pages else None
    return ChunkRecord(
        doc_id=doc.doc_id,
        chunk_id=f"{doc.doc_id}-chunk-{position:04d}",
        fuente=_source_label(doc),
        formato=doc.source.original_format.lower(),
        fenomeno=_phenomenon_number(doc.source.phenomenon),
        posicion=position,
        num_tokens=_token_count(texto),
        texto=texto,
        block_ids=list(current_block_ids),
        block_types=list(current_block_types),
        page_start=page_start,
        page_end=page_end,
        source_language=doc.source.language,
        source_script=doc.source.dominant_script,
    )


def chunk_documents(
    doc: CanonicalDocument,
    *,
    max_words: int = DEFAULT_MAX_WORDS,
    min_words: int = DEFAULT_MIN_WORDS,
    paths: ArtifactPaths | None = None,
) -> Iterator[ChunkRecord]:
    """Fragmenta un documento canónico en chunks estables y completos."""

    del min_words  # reserva explícita para refinamientos futuros

    root = paths or ArtifactPaths()
    current_text: list[str] = []
    current_block_ids: list[str] = []
    current_block_types: list[str] = []
    current_pages: list[int] = []
    current_words = 0
    position = 0

    for block in _iter_blocks_for_chunking(doc, root):
        if block.type in {"heading", "list_item", "table_row", "table_text", "caption"}:
            units = [block.text.strip()]
            oversize_units = 0
        else:
            units, oversize_units = _split_unit(block.text.strip(), max_words)

        if oversize_units:
            # Se conserva la unidad completa aunque exceda el presupuesto.
            # El reto prohíbe cortar oraciones; esta excepción queda reflejada en `num_tokens`.
            pass

        for unit in units:
            unit_words = _token_count(unit)
            if current_text and current_words + unit_words > max_words:
                chunk = _flush_current(
                    current_text,
                    current_block_ids,
                    current_block_types,
                    current_pages,
                    doc,
                    position,
                )
                if chunk is not None:
                    yield chunk
                    position += 1
                current_text = []
                current_block_ids = []
                current_block_types = []
                current_pages = []
                current_words = 0

            current_text.append(unit)
            current_block_ids.append(block.block_id)
            current_block_types.append(block.type)
            if block.page is not None:
                current_pages.append(block.page)
            current_words += unit_words

    chunk = _flush_current(
        current_text,
        current_block_ids,
        current_block_types,
        current_pages,
        doc,
        position,
    )
    if chunk is not None:
        yield chunk


def build_chunks(
    *,
    artifacts_root: Path | str | None = None,
    max_words: int = DEFAULT_MAX_WORDS,
    limit: int | None = None,
) -> ChunkStats:
    """Lee la ingesta y escribe los artefactos de chunking en streaming."""

    paths = ArtifactPaths(Path(artifacts_root) if artifacts_root is not None else ArtifactPaths().root)
    paths.chunking.ensure("reports")

    if not paths.documents.is_dir():
        raise FileNotFoundError(
            f"No existe {paths.documents}. Ejecuta primero la ingesta completa."
        )

    stats = ChunkStats()
    chunks_path = paths.chunking.root / "chunks.jsonl"
    metadata_path = paths.chunking.root / "metadata.jsonl"

    with chunks_path.open("w", encoding="utf-8") as chunks_handle, metadata_path.open(
        "w", encoding="utf-8"
    ) as metadata_handle:
        for index, doc in enumerate(iter_documents(paths)):
            if limit is not None and index >= limit:
                break

            stats = replace(stats, documents_seen=stats.documents_seen + 1)
            if doc.indexing_hint == "structured_only":
                stats = replace(
                    stats,
                    documents_skipped_structured_only=stats.documents_skipped_structured_only + 1,
                )
                continue

            produced = 0
            oversize_units = 0
            for chunk in chunk_documents(doc, max_words=max_words, paths=paths):
                oversize_units += int(chunk.num_tokens > max_words)
                write_line(chunks_handle, chunk)
                write_line(metadata_handle, chunk)
                produced += 1
                stats = replace(stats, chunks_written=stats.chunks_written + 1)

            if produced:
                stats = replace(stats, documents_chunked=stats.documents_chunked + 1)
                stats = replace(stats, oversize_units=stats.oversize_units + oversize_units)
            else:
                stats = replace(stats, documents_empty=stats.documents_empty + 1)

    summary = {
        "artifacts_root": str(paths.root),
        "documents_seen": stats.documents_seen,
        "documents_chunked": stats.documents_chunked,
        "documents_skipped_structured_only": stats.documents_skipped_structured_only,
        "documents_empty": stats.documents_empty,
        "chunks_written": stats.chunks_written,
        "oversize_units": stats.oversize_units,
        "max_words": max_words,
    }
    (paths.chunking.reports / "summary.json").write_text(
        json.dumps(summary, ensure_ascii=False, indent=2), encoding="utf-8"
    )
    return stats


def write_chunks(
    *,
    artifacts_root: Path | str | None = None,
    max_words: int = DEFAULT_MAX_WORDS,
    limit: int | None = None,
) -> ChunkStats:
    """Alias práctico para la API pública de la etapa."""

    return build_chunks(artifacts_root=artifacts_root, max_words=max_words, limit=limit)


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Chunking CORPUS CODEFEST AD ASTRA 2026")
    parser.add_argument("--artifacts", type=Path, default=ArtifactPaths().root)
    parser.add_argument("--max-words", type=int, default=DEFAULT_MAX_WORDS)
    parser.add_argument("--limit", type=int, default=None)
    parser.add_argument("--strict", action="store_true")
    args = parser.parse_args(argv)

    try:
        stats = write_chunks(
            artifacts_root=args.artifacts,
            max_words=args.max_words,
            limit=args.limit,
        )
    except Exception as exc:  # pragma: no cover - CLI error path
        print(str(exc), file=sys.stderr)
        return 2

    print(
        json.dumps(
            {
                "documents_seen": stats.documents_seen,
                "documents_chunked": stats.documents_chunked,
                "documents_skipped_structured_only": stats.documents_skipped_structured_only,
                "documents_empty": stats.documents_empty,
                "chunks_written": stats.chunks_written,
                "oversize_units": stats.oversize_units,
            },
            ensure_ascii=False,
            indent=2,
        )
    )

    if args.strict and stats.chunks_written == 0:
        return 1
    return 0
