import pytest
from unittest.mock import patch
from adastra.chunking.processor import (
    _looks_like_abbreviation,
    _split_sentences,
    _split_unit,
    ChunkRecord,
    chunk_documents
)
from adastra.core.models import CanonicalDocument, ContentBlock
from adastra.core.models.document import SourceMetadata
from adastra.core.models.quality import DocumentQuality
from adastra.core.paths import ArtifactPaths

def test_looks_like_abbreviation():
    assert _looks_like_abbreviation("This is a dr.", 12) is True
    # 'es.' should not be an abbreviation
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

@patch("adastra.chunking.processor.iter_blocks")
def test_chunk_documents_headings_and_boilerplate(mock_iter_blocks):
    source = SourceMetadata(
        phenomenon="F1",
        observatory="OBS",
        observatory_code="O1",
        relative_path="file.pdf",
        original_format="PDF"
    )
    from unittest.mock import MagicMock
    quality = MagicMock()
    quality.overall_score = 0.9
    quality.basis = "intrinsic_only"
    
    doc = CanonicalDocument.model_construct(
        doc_id="DOC-123",
        pipeline_version="1.0",
        source=source,
        quality=quality,
    )
    
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
        )
    ]
    
    mock_iter_blocks.return_value = iter(blocks)
    paths = ArtifactPaths()
    
    chunks = list(chunk_documents(doc, paths=paths))
    
    assert len(chunks) == 1
    
    # Check heading is prepended
    assert "Chapter 1" in chunks[0].texto
    assert "First paragraph." in chunks[0].texto
    assert "heading" in chunks[0].block_types
    assert "paragraph" in chunks[0].block_types
    
    # Check boilerplate filtered (page_text removed, caption kept)
    assert "Figure 1" in chunks[0].texto
    assert "caption" in chunks[0].block_types
    
    # Check metadata
    assert chunks[0].quality_score == 0.9
    assert chunks[0].quality_basis == "intrinsic_only"
