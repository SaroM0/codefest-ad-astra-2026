import json

from unittest.mock import patch
from adastra.chunking.processor import (
    _looks_like_abbreviation,
    _split_sentences,
    _split_unit,
    _split_by_words,
    _token_count,
    build_chunks,
    chunk_documents,
    DEFAULT_MAX_WORDS,
)
from adastra.core.models import CanonicalDocument, ContentBlock
from adastra.core.models.document import SourceMetadata
from adastra.core.models.quality import DocumentQuality, ExtractionConfidence
from adastra.core.paths import ArtifactPaths


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _make_source(**kwargs):
    defaults = dict(
        phenomenon="F1",
        observatory="OBS",
        observatory_code="O1",
        relative_path="file.pdf",
        original_format="PDF",
    )
    defaults.update(kwargs)
    return SourceMetadata(**defaults)


def _make_doc(doc_id="DOC-001", quality=None, **kwargs):
    quality = quality or DocumentQuality(
        confidence=ExtractionConfidence(score=0.9, basis="intrinsic_only"),
        usable=True,
    )
    return CanonicalDocument.model_construct(
        doc_id=doc_id,
        pipeline_version="1.0",
        source=_make_source(),
        quality=quality,
        **kwargs,
    )


# ---------------------------------------------------------------------------
# Tests de funciones auxiliares
# ---------------------------------------------------------------------------

def test_looks_like_abbreviation():
    assert _looks_like_abbreviation("This is a dr.", 12) is True
    # 'es.' no debe ser abreviatura
    assert _looks_like_abbreviation("El fin es.", 9) is False
    assert _looks_like_abbreviation("What is it?", 5) is False
    assert _looks_like_abbreviation("Point 1.", 7) is True
    assert _looks_like_abbreviation("Section A.", 9) is True


def test_split_sentences():
    text = "This is a sentence. This is another sentence."
    sentences = _split_sentences(text)
    assert len(sentences) == 2
    assert sentences[0] == "This is a sentence."

    text2 = "El fin es. La siguiente oración debe iniciar aquí."
    sentences2 = _split_sentences(text2)
    assert len(sentences2) == 2
    assert sentences2[0] == "El fin es."


# ---------------------------------------------------------------------------
# Tests de _split_by_words — fallback duro
# ---------------------------------------------------------------------------

def test_split_by_words_respects_limit():
    """Todos los fragmentos deben tener <= max_words tokens."""
    long_text = " ".join(f"word{i}" for i in range(500))
    max_w = 50
    pieces = _split_by_words(long_text, max_w)
    assert pieces, "No debe devolver lista vacía"
    for piece in pieces:
        assert _token_count(piece) <= max_w, (
            f"Fragmento supera {max_w} tokens: {_token_count(piece)}"
        )


def test_split_by_words_empty():
    assert _split_by_words("", 50) == []
    assert _split_by_words("   ", 50) == []


def test_split_by_words_short_text_not_split():
    text = "Hola mundo"
    pieces = _split_by_words(text, 50)
    assert pieces == ["Hola mundo"]


# ---------------------------------------------------------------------------
# Tests de _split_unit — límite duro garantizado
# ---------------------------------------------------------------------------

def test_split_unit_no_sentence_boundary_hard_limit():
    """Bloque sin puntuación de miles de tokens → todos los trozos cumplen el límite."""
    # Simula texto tabular / lista sin puntos
    long_text = "token " * 1000  # 1000 tokens, sin puntuación
    pieces, oversize, strategy = _split_unit(long_text.strip(), DEFAULT_MAX_WORDS)
    assert pieces, "Debe producir al menos un fragmento"
    assert strategy == "hard_token_split"
    for piece in pieces:
        assert _token_count(piece) <= DEFAULT_MAX_WORDS, (
            f"Piece exceeds limit: {_token_count(piece)} tokens"
        )


def test_split_unit_short_text_unchanged():
    text = "A short text."
    pieces, oversize, strategy = _split_unit(text, DEFAULT_MAX_WORDS)
    assert pieces == ["A short text."]
    assert oversize == 0


def test_split_unit_sentence_split():
    """Texto con múltiples oraciones → se divide por oraciones."""
    text = " ".join(["Word."] * 100)  # 100 oraciones cortas
    pieces, oversize, strategy = _split_unit(text, 10)
    assert all(_token_count(p) <= 10 for p in pieces), "Algún fragmento supera el límite"


def test_split_unit_oversize_sentence_gets_hard_split():
    """Una oración larga dentro de un texto multi-oración debe cortarse por tokens."""
    short = "Short sentence."
    long_sentence = "word " * 300  # 300 tokens, sin punto final → una sola "oración" larga
    text = short + " " + long_sentence.strip() + ". " + short
    pieces, oversize, strategy = _split_unit(text.strip(), DEFAULT_MAX_WORDS)
    for piece in pieces:
        assert _token_count(piece) <= DEFAULT_MAX_WORDS, (
            f"Piece exceeds limit: {_token_count(piece)}"
        )


# ---------------------------------------------------------------------------
# Tests de chunk_documents
# ---------------------------------------------------------------------------

@patch("adastra.chunking.processor.iter_blocks")
def test_chunk_documents_headings_and_boilerplate(mock_iter_blocks):
    """Verifica que heading se incorpora, page_text boilerplate se filtra y caption se conserva."""
    doc = _make_doc(doc_id="DOC-123")

    blocks = [
        ContentBlock(
            block_id="b1", type="heading", text="Chapter 1", order=1, extraction_method="ocr"
        ),
        ContentBlock(
            block_id="b2", type="paragraph", text="First paragraph.", order=2, extraction_method="ocr"
        ),
        ContentBlock(
            block_id="b3", type="page_text", text="Page 1", order=3, extraction_method="ocr", is_boilerplate=True
        ),
        ContentBlock(
            block_id="b4", type="caption", text="Figure 1", order=4, extraction_method="ocr", is_boilerplate=True
        ),
    ]

    mock_iter_blocks.return_value = iter(blocks)
    paths = ArtifactPaths()

    chunks = list(chunk_documents(doc, paths=paths))

    assert len(chunks) == 1
    assert "Chapter 1" in chunks[0].texto
    assert "First paragraph." in chunks[0].texto
    assert "heading" in chunks[0].block_types
    assert "paragraph" in chunks[0].block_types

    # page_text boilerplate eliminado, caption conservado
    assert "Figure 1" in chunks[0].texto
    assert "caption" in chunks[0].block_types

    # Trazabilidad
    assert chunks[0].section_heading == "Chapter 1"


@patch("adastra.chunking.processor.iter_blocks")
def test_chunk_documents_heading_budget_does_not_exceed_limit(mock_iter_blocks):
    """CORRECCIÓN BUG-2: heading + contenido no debe superar max_words."""
    max_w = 20
    # heading de 10 tokens
    heading_text = " ".join(f"H{i}" for i in range(10))
    # contenido de 15 tokens (heading 10 + content 15 = 25 > 20, debe hacer flush antes)
    content_text = " ".join(f"W{i}" for i in range(15))

    blocks = [
        ContentBlock(
            block_id="h1", type="heading", text=heading_text, order=1, extraction_method="native_reading_order"
        ),
        ContentBlock(
            block_id="p1", type="paragraph", text=content_text, order=2, extraction_method="native_reading_order"
        ),
    ]
    mock_iter_blocks.return_value = iter(blocks)
    doc = _make_doc()
    chunks = list(chunk_documents(doc, max_words=max_w, paths=ArtifactPaths()))
    for chunk in chunks:
        assert chunk.num_tokens <= max_w, (
            f"Chunk {chunk.chunk_id} supera el límite: {chunk.num_tokens} tokens"
        )


@patch("adastra.chunking.processor.iter_blocks")
def test_chunk_documents_no_oversize_invariant(mock_iter_blocks):
    """Invariante principal: ningún chunk final supera max_words."""
    max_w = DEFAULT_MAX_WORDS
    # Mezcla de bloques cortos y uno muy largo sin puntuación
    long_block = "word " * 1000
    blocks = [
        ContentBlock(
            block_id="b1", type="paragraph", text="Short intro sentence.", order=1, extraction_method="native_reading_order"
        ),
        ContentBlock(
            block_id="b2", type="paragraph", text=long_block.strip(), order=2, extraction_method="native_reading_order"
        ),
        ContentBlock(
            block_id="b3", type="paragraph", text="Closing sentence.", order=3, extraction_method="native_reading_order"
        ),
    ]
    mock_iter_blocks.return_value = iter(blocks)
    doc = _make_doc()
    chunks = list(chunk_documents(doc, max_words=max_w, paths=ArtifactPaths()))
    assert chunks, "Debe producir chunks"
    oversize = [c for c in chunks if c.num_tokens > max_w]
    assert oversize == [], (
        f"{len(oversize)} chunks superan el límite: "
        + str([(c.chunk_id, c.num_tokens) for c in oversize])
    )


@patch("adastra.chunking.processor.iter_blocks")
def test_chunk_documents_split_strategy_hard_token_recorded(mock_iter_blocks):
    """Cuando se usa el fallback duro, split_strategy debe ser 'hard_token_split'."""
    long_block = "word " * 500  # sin puntuación
    blocks = [
        ContentBlock(
            block_id="b1", type="paragraph", text=long_block.strip(), order=1, extraction_method="native_reading_order"
        ),
    ]
    mock_iter_blocks.return_value = iter(blocks)
    doc = _make_doc()
    chunks = list(chunk_documents(doc, max_words=DEFAULT_MAX_WORDS, paths=ArtifactPaths()))
    assert any(c.split_strategy == "hard_token_split" for c in chunks), (
        "Ningún chunk registró estrategia hard_token_split"
    )


@patch("adastra.chunking.processor.iter_blocks")
def test_chunk_documents_structured_only_excluded(mock_iter_blocks):
    """structured_only se excluye en build_chunks; chunk_documents vacío sin bloques."""
    mock_iter_blocks.return_value = iter([])
    doc = _make_doc()
    chunks = list(chunk_documents(doc, paths=ArtifactPaths()))
    assert chunks == []


def test_build_chunks_reads_blocks_ref_and_skips_structured_only(tmp_path):
    """Integración: el lector resuelve blocks_ref y build_chunks excluye structured_only."""
    documents_dir = tmp_path / "ingestion" / "documents"
    documents_dir.mkdir(parents=True)

    external_block = ContentBlock(
        block_id="DOC-EXTERNAL:block:1",
        type="paragraph",
        text="Contenido almacenado fuera del documento canónico.",
        order=1,
        extraction_method="manual",
    )
    external_doc = _make_doc(
        doc_id="DOC-EXTERNAL",
        blocks=None,
        blocks_ref="DOC-EXTERNAL.blocks.jsonl",
        block_count=1,
    )
    (documents_dir / "DOC-EXTERNAL.json").write_text(
        external_doc.model_dump_json(), encoding="utf-8"
    )
    (documents_dir / "DOC-EXTERNAL.blocks.jsonl").write_text(
        json.dumps(external_block.model_dump()) + "\n", encoding="utf-8"
    )

    structured_doc = _make_doc(
        doc_id="DOC-STRUCTURED",
        blocks=[ContentBlock(
            block_id="DOC-STRUCTURED:block:1",
            type="table_row",
            text="Esta fila no debe indexarse.",
            order=1,
            extraction_method="structured",
        )],
        block_count=1,
        indexing_hint="structured_only",
    )
    (documents_dir / "DOC-STRUCTURED.json").write_text(
        structured_doc.model_dump_json(), encoding="utf-8"
    )

    stats = build_chunks(artifacts_root=tmp_path)
    rows = [
        json.loads(line)
        for line in (tmp_path / "chunking" / "chunks.jsonl").read_text(encoding="utf-8").splitlines()
    ]

    assert stats.documents_seen == 2
    assert stats.documents_skipped_structured_only == 1
    assert stats.chunks_written == 1
    assert [row["doc_id"] for row in rows] == ["DOC-EXTERNAL"]
