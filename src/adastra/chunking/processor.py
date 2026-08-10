"""Procesador de chunking mínimo.

Convierte `CanonicalDocument` → chunks (JSONL) bajo `artifacts/chunking/`.
"""
from __future__ import annotations

from dataclasses import asdict, dataclass
from pathlib import Path
from typing import Iterator

from adastra.core.jsonl import write_jsonl
from adastra.core.documents import iter_documents, iter_blocks
from adastra.core.paths import ArtifactPaths


@dataclass
class Chunk:
    doc_id: str
    chunk_id: str
    fuente: str
    formato: str
    fenomeno: int
    posicion: int
    num_tokens: int
    texto: str
    language: str
    published_date: str
    original_title: str


def _count_tokens(text: str) -> int:
    return len(text.split())


def _trim_words(text: str, max_words: int) -> str:
    words = text.split()
    if len(words) <= max_words:
        return text
    return " ".join(words[:max_words])


def _split_sentences(text: str) -> list[str]:
    """Rudimentario: divide por puntos, signos de interrogación/exclamación
    seguidos de espacio y mayúscula o fin de texto. Suficiente para evitar cortes
    de oraciones en corpus hispano/inglés en este contexto.
    """
    import re

    pattern = re.compile(r"(?<=[\.\?!])\s+(?=[A-ZÀ-ÖØ-Ý])")
    parts = [p.strip() for p in pattern.split(text) if p.strip()]
    return parts


def iter_chunks(
    paths: ArtifactPaths | None = None, max_words: int = 250, overlap_words: int = 50
) -> Iterator[Chunk]:
    paths = paths or ArtifactPaths()
    for doc in iter_documents(paths):
        # extraer campos desde la metadata de la fuente
        lang = doc.source.language
        pub_date = doc.source.published_date
        orig_title = doc.source.original_title
        if not (lang and pub_date and orig_title):
            raise ValueError(
                f"Documento {doc.doc_id} carece de campos obligatorios: language/published_date/original_title"
            )
        pos = 0
        fuente = doc.source.relative_path or ""
        formato = doc.source.original_format or ""
        try:
            fenomeno = int(doc.source.phenomenon) if doc.source.phenomenon else 0
        except Exception:
            fenomeno = 0
        for block in iter_blocks(doc, paths):
            if not (block.text and block.text.strip()):
                continue
            # No cortar oraciones por la mitad
            sentences = _split_sentences(block.text.strip())
            sent_words_list = [_count_tokens(s) for s in sentences]

            if overlap_words >= max_words:
                overlap_words = max(0, max_words - 1)

            start_idx = 0
            n = len(sentences)
            prefix = [0]
            for w in sent_words_list:
                prefix.append(prefix[-1] + w)

            while start_idx < n:

                end_idx = start_idx
                while end_idx < n and (prefix[end_idx + 1] - prefix[start_idx]) <= max_words:
                    end_idx += 1

                if end_idx == start_idx:
                    s = sentences[start_idx]
                    s = _trim_words(s, max_words)
                    texto = s
                else:
                    texto = " ".join(sentences[start_idx:end_idx])

                num_tokens = _count_tokens(texto)
                chunk = Chunk(
                    doc_id=doc.doc_id,
                    chunk_id=f"{doc.doc_id}-chunk-{pos:04d}",
                    fuente=fuente,
                    formato=formato,
                    fenomeno=fenomeno,
                    posicion=pos,
                    num_tokens=num_tokens,
                    texto=texto,
                    language=lang,
                    published_date=pub_date,
                    original_title=orig_title,
                )
                yield chunk
                pos += 1

                if end_idx == n:
                    break
                target = prefix[start_idx] + max_words - overlap_words
                next_idx = start_idx + 1
                while next_idx < n and prefix[next_idx] < target:
                    next_idx += 1
                if next_idx <= start_idx:
                    next_idx = start_idx + 1
                start_idx = next_idx


def write_chunks(
    out_root: Path | None = None,
    max_words: int = 250,
    encoder_name: str = "default",
    overlap_words: int = 50,
) -> int:
    """Escribe `chunks.jsonl` y `metadata.jsonl` bajo `out_root/encoder_<name>/`.

    El formato de `metadata.jsonl` sigue la Tabla 1 del concurso.
    """
    paths = ArtifactPaths()
    if out_root:
        base = Path(out_root) / "chunking"
    else:
        base = paths.chunking.root
    encoder_dir = base / f"encoder_{encoder_name}"
    encoder_dir.mkdir(parents=True, exist_ok=True)
    out_path = encoder_dir / "chunks.jsonl"
    meta_path = encoder_dir / "metadata.jsonl"

    chunks_iter = list(iter_chunks(paths, max_words=max_words, overlap_words=overlap_words))
    written = write_jsonl(out_path, (asdict(c) for c in chunks_iter))
    write_jsonl(meta_path, (asdict(c) for c in chunks_iter))
    # simple report
    report = {"chunks_written": written}
    (encoder_dir / "reports").mkdir(exist_ok=True)
    (encoder_dir / "reports" / "summary.json").write_text(str(report), encoding="utf-8")
    return written


__all__ = ["Chunk", "iter_chunks", "write_chunks"]
