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

# REAL-06: Siglas compuestas con puntos intercalados (U.S., U.K., E.U., etc.)
_COMPOUND_ABBREV_RE = re.compile(
    r"\b[A-ZÁÉÍÓÚÜÑ](?:\.[A-ZÁÉÍÓÚÜÑ])+\.$",
    re.UNICODE,
)


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

    quality_score: float | None = None
    quality_basis: str | None = None
    extraction_method: str | None = None
    segmentation_confidence: float | None = None

    # Trazabilidad de la estrategia de fragmentación (solución propuesta §4)
    split_strategy: str = "sentence"  # sentence | paragraph | hard_token_split
    oversize_reason: str | None = None
    section_heading: str | None = None


@dataclass(frozen=True)
class ChunkStats:
    documents_seen: int = 0
    documents_chunked: int = 0
    documents_skipped_structured_only: int = 0
    documents_empty: int = 0
    chunks_written: int = 0
    oversize_units: int = 0
    # Conteo de chunks por estrategia de corte
    strategy_sentence: int = 0
    strategy_paragraph: int = 0
    strategy_hard_token_split: int = 0


def _source_label(doc: CanonicalDocument) -> str:
    return doc.source.source_url or doc.source.original_filename or doc.source.relative_path


def _phenomenon_number(value: str) -> int:
    digits = "".join(ch for ch in str(value) if ch.isdigit())
    if digits in {"1", "2", "3"}:
        return int(digits)
    raise ValueError(f"Fenómeno inválido: {value!r}")


def _token_count(text: str) -> int:
    return sum(1 for piece in _WORD_RE.findall(text) if piece.strip())


def _split_by_words(text: str, max_words: int) -> list[str]:
    """Fallback duro: parte el texto en fragmentos de ≤ max_words tokens.

    Garantiza el límite incluso cuando no hay puntuación, tabulaciones
    ni saltos de párrafo explotables (tablas, listas, URLs, PDFs mal segmentados).
    """
    if max_words < 1:
        raise ValueError("max_words debe ser mayor que cero")

    tokens = _WORD_RE.findall(text)
    if not tokens:
        return [text.strip()] if text.strip() else []

    # Reconstruir fragmentos respetando posiciones originales en el texto.
    # Iteramos sobre el texto original para no perder espacios internos.
    pieces: list[str] = []
    chunk_tokens: list[str] = []
    piece_start = 0

    for match in _WORD_RE.finditer(text):
        chunk_tokens.append(match.group())
        if len(chunk_tokens) >= max_words:
            pieces.append(text[piece_start:match.end()].strip())
            piece_start = match.end()
            chunk_tokens = []

    tail = text[piece_start:].strip()
    if tail:
        pieces.append(tail)

    return [p for p in pieces if p]


def _split_paragraphs(text: str) -> list[str]:
    parts = [part.strip() for part in re.split(r"\n\s*\n+", text.strip())]
    return [part for part in parts if part]


def _looks_like_abbreviation(text: str, terminator_index: int) -> bool:
    window_start = max(0, terminator_index - 20)
    window = text[window_start : terminator_index + 1].strip()
    window_lower = window.lower()

    # Diccionario de abreviaturas conocidas
    if any(window_lower.endswith(abbrev) for abbrev in _ABBREVIATIONS):
        return True

    # REAL-06: Siglas compuestas con puntos (U.S., U.K., E.U., EE.UU.)
    if _COMPOUND_ABBREV_RE.search(window):
        return True

    # SEG-02: Iniciales sueltas ("A.") y numeración de listas ("1.", "12.")
    # Se limita a un solo carácter o dígitos para no atrapar "es." / "is."
    if re.search(r"(^|\s)([A-ZÁÉÍÓÚÜÑa-záéíóúüñ]\.|[0-9]{1,3}\.)$", window):
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


def _split_unit(
    text: str, max_words: int
) -> tuple[list[str], int, str]:
    """Divide un bloque de texto en unidades de ≤ max_words tokens.

    Devuelve (piezas, contador_sobredimensionados, estrategia_usada).
    La estrategia es una de: 'paragraph', 'sentence', 'hard_token_split'.
    """
    paragraphs = _split_paragraphs(text)
    if len(paragraphs) > 1:
        pieces: list[str] = []
        oversize = 0
        for paragraph in paragraphs:
            sub_pieces, sub_oversize, _ = _split_unit(paragraph, max_words)
            pieces.extend(sub_pieces)
            oversize += sub_oversize
        return pieces, oversize, "paragraph"

    if _token_count(text) <= max_words:
        return [text.strip()], 0, "sentence"

    sentences = _split_sentences(text)
    if len(sentences) == 1:
        # CORRECCIÓN BUG-1: fallback duro por palabras cuando no hay límite de oración
        if _token_count(text) > max_words:
            return _split_by_words(text, max_words), 1, "hard_token_split"
        return [text.strip()], 0, "sentence"

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
            # CORRECCIÓN BUG-1: oración individual sobredimensionada → corte duro
            pieces.extend(_split_by_words(sentence, max_words))
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

    return [piece for piece in pieces if piece], oversize, "sentence"


def _iter_blocks_for_chunking(
    doc: CanonicalDocument, paths: ArtifactPaths
) -> Iterator[ContentBlock]:
    for block in iter_blocks(doc, paths):
        if not block.text.strip():
            continue
        # SEG-03: No descartar todo boilerplate. Sólo page_text
        if block.is_boilerplate and block.type == "page_text":
            continue
        yield block


def _flush_current(
    current_text: list[str],
    current_block_ids: list[str],
    current_block_types: list[str],
    current_pages: list[int],
    current_methods: list[str],
    current_confidences: list[float],
    doc: CanonicalDocument,
    position: int,
    *,
    split_strategy: str = "sentence",
    section_heading: str | None = None,
    oversize_reason: str | None = None,
) -> ChunkRecord | None:
    if not current_text:
        return None

    texto = "\n\n".join(part.strip() for part in current_text if part.strip()).strip()
    if not texto:
        return None

    page_start = min(current_pages) if current_pages else None
    page_end = max(current_pages) if current_pages else None

    extraction = current_methods[0] if current_methods else None
    confidence = sum(current_confidences) / len(current_confidences) if current_confidences else None

    # REAL-01: leer calidad del contrato real de DocumentQuality
    q_score = None
    q_basis = None
    if hasattr(doc, "quality") and doc.quality is not None:
        try:
            q_score = doc.quality.confidence.score
            q_basis = doc.quality.confidence.basis
        except AttributeError:
            pass

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
        quality_score=q_score,
        quality_basis=q_basis,
        extraction_method=extraction,
        segmentation_confidence=confidence,
        split_strategy=split_strategy,
        section_heading=section_heading,
        oversize_reason=oversize_reason,
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
    if max_words < 1:
        raise ValueError("max_words debe ser mayor que cero")

    root = paths or ArtifactPaths()
    current_text: list[str] = []
    current_block_ids: list[str] = []
    current_block_types: list[str] = []
    current_pages: list[int] = []
    current_methods: list[str] = []
    current_confidences: list[float] = []
    current_words = 0
    position = 0
    current_strategy = "sentence"

    # REAL-05: heading_text/heading_words se resetean tras ser incorporados al primer chunk
    pending_heading: ContentBlock | None = None
    pending_heading_words: int = 0
    # Texto del heading de sección activo (para section_heading en ChunkRecord)
    active_section_heading: str | None = None

    for block in _iter_blocks_for_chunking(doc, root):
        if block.type == "heading":
            # Flush del chunk anterior antes de iniciar nueva sección
            if current_text:
                chunk = _flush_current(
                    current_text, current_block_ids, current_block_types,
                    current_pages, current_methods, current_confidences,
                    doc, position,
                    split_strategy=current_strategy,
                    section_heading=active_section_heading,
                )
                if chunk is not None:
                    yield chunk
                    position += 1
                current_text.clear()
                current_block_ids.clear()
                current_block_types.clear()
                current_pages.clear()
                current_methods.clear()
                current_confidences.clear()
                current_words = 0
                current_strategy = "sentence"

            pending_heading = block
            pending_heading_words = _token_count(block.text.strip())
            active_section_heading = block.text.strip()
            continue

        # SEG-01: dividir todos los tipos de bloque por límite de oración
        units, _oversize_count, unit_strategy = _split_unit(block.text.strip(), max_words)

        # Un heading pendiente también consume presupuesto. Si cabe por sí solo, se
        # parte la primera unidad de contenido para que el primer chunk de sección
        # nunca exceda el límite. Las unidades posteriores se procesan normalmente.
        if pending_heading and pending_heading_words < max_words and units:
            available_for_first_unit = max_words - pending_heading_words
            first_unit_words = _token_count(units[0])
            if first_unit_words > available_for_first_unit:
                units = _split_by_words(units[0], available_for_first_unit) + units[1:]
                unit_strategy = "hard_token_split"

        for unit in units:
            unit_words = _token_count(unit)

            # REAL-03 / CORRECCIÓN BUG-2: calcular presupuesto incluyendo heading pendiente
            # para la decisión de flush ANTES de incorporar el heading.
            heading_budget = pending_heading_words if pending_heading else 0

            # Flush si el chunk actual ya no cabe, contabilizando el heading pendiente
            if current_text and current_words + heading_budget + unit_words > max_words:
                chunk = _flush_current(
                    current_text, current_block_ids, current_block_types,
                    current_pages, current_methods, current_confidences,
                    doc, position,
                    split_strategy=current_strategy,
                    section_heading=active_section_heading,
                )
                if chunk is not None:
                    yield chunk
                    position += 1
                current_text.clear()
                current_block_ids.clear()
                current_block_types.clear()
                current_pages.clear()
                current_methods.clear()
                current_confidences.clear()
                current_words = 0
                current_strategy = "sentence"

            # Un heading excepcionalmente largo se emite dividido antes del contenido.
            # Esto preserva el límite duro sin descartar evidencia estructural.
            if not current_text and pending_heading and pending_heading_words >= max_words:
                for heading_piece in _split_by_words(pending_heading.text.strip(), max_words):
                    heading_chunk = _flush_current(
                        [heading_piece],
                        [pending_heading.block_id],
                        [pending_heading.type],
                        [pending_heading.page] if pending_heading.page is not None else [],
                        [pending_heading.extraction_method],
                        [pending_heading.segmentation_confidence],
                        doc,
                        position,
                        split_strategy="hard_token_split",
                        section_heading=pending_heading.text.strip(),
                    )
                    if heading_chunk is not None:
                        yield heading_chunk
                        position += 1
                pending_heading = None
                pending_heading_words = 0

            if unit_strategy == "hard_token_split":
                current_strategy = "hard_token_split"
            elif unit_strategy == "paragraph" and current_strategy == "sentence":
                current_strategy = "paragraph"

            # REAL-05: incorporar heading SOLO al primer chunk de la sección y resetearlo
            if not current_text and pending_heading:
                current_text.append(pending_heading.text.strip())
                current_block_ids.append(pending_heading.block_id)
                current_block_types.append(pending_heading.type)
                if pending_heading.page is not None:
                    current_pages.append(pending_heading.page)
                current_methods.append(pending_heading.extraction_method)
                current_confidences.append(pending_heading.segmentation_confidence)
                current_words += pending_heading_words
                # REAL-05: limpiar heading pendiente para que no se repita
                pending_heading = None
                pending_heading_words = 0

            current_text.append(unit)
            current_block_ids.append(block.block_id)
            current_block_types.append(block.type)
            if block.page is not None:
                current_pages.append(block.page)
            current_methods.append(block.extraction_method)
            current_confidences.append(block.segmentation_confidence)
            current_words += unit_words

    # REAL-04: emitir heading terminal si el documento termina en un heading
    if pending_heading and not current_text:
        current_text.append(pending_heading.text.strip())
        current_block_ids.append(pending_heading.block_id)
        current_block_types.append(pending_heading.type)
        if pending_heading.page is not None:
            current_pages.append(pending_heading.page)
        current_methods.append(pending_heading.extraction_method)
        current_confidences.append(pending_heading.segmentation_confidence)
        current_words += pending_heading_words

    chunk = _flush_current(
        current_text, current_block_ids, current_block_types,
        current_pages, current_methods, current_confidences,
        doc, position,
        split_strategy=current_strategy,
        section_heading=active_section_heading,
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

    # Escribir a archivos temporales y renombrar al final
    chunks_tmp = chunks_path.with_suffix(".tmp")
    metadata_tmp = metadata_path.with_suffix(".tmp")

    with chunks_tmp.open("w", encoding="utf-8") as chunks_handle, metadata_tmp.open(
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
            strategy_sentence = 0
            strategy_paragraph = 0
            strategy_hard = 0
            for chunk in chunk_documents(doc, max_words=max_words, paths=paths):
                oversize_units += int(chunk.num_tokens > max_words)
                write_line(chunks_handle, chunk)
                write_line(metadata_handle, chunk)
                produced += 1
                stats = replace(stats, chunks_written=stats.chunks_written + 1)
                if chunk.split_strategy == "hard_token_split":
                    strategy_hard += 1
                elif chunk.split_strategy == "paragraph":
                    strategy_paragraph += 1
                else:
                    strategy_sentence += 1

            if produced:
                stats = replace(stats, documents_chunked=stats.documents_chunked + 1)
                stats = replace(stats, oversize_units=stats.oversize_units + oversize_units)
                stats = replace(
                    stats,
                    strategy_sentence=stats.strategy_sentence + strategy_sentence,
                    strategy_paragraph=stats.strategy_paragraph + strategy_paragraph,
                    strategy_hard_token_split=stats.strategy_hard_token_split + strategy_hard,
                )
            else:
                stats = replace(stats, documents_empty=stats.documents_empty + 1)

    chunks_tmp.replace(chunks_path)
    metadata_tmp.replace(metadata_path)

    summary = {
        "artifacts_root": str(paths.root),
        "documents_seen": stats.documents_seen,
        "documents_chunked": stats.documents_chunked,
        "documents_skipped_structured_only": stats.documents_skipped_structured_only,
        "documents_empty": stats.documents_empty,
        "chunks_written": stats.chunks_written,
        "oversize_units": stats.oversize_units,
        "max_words": max_words,
        "strategy_counts": {
            "sentence": stats.strategy_sentence,
            "paragraph": stats.strategy_paragraph,
            "hard_token_split": stats.strategy_hard_token_split,
        },
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
