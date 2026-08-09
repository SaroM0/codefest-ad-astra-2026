"""Modelo canónico: el contrato que viaja entre las cuatro etapas."""

from .corpus_entry import CorpusEntry, Role
from .block import ContentBlock, BlockType, ExtractionMethod
from .quality import (
    DocumentQuality,
    ExtractionConfidence,
    ConfidenceBasis,
    SignalValue,
    PageQuality,
    QualityVerdict,
)
from .document import CanonicalDocument, SourceMetadata, PageContent, ManifestEntry

__all__ = [
    "CorpusEntry",
    "Role",
    "ContentBlock",
    "BlockType",
    "ExtractionMethod",
    "DocumentQuality",
    "ExtractionConfidence",
    "ConfidenceBasis",
    "SignalValue",
    "PageQuality",
    "QualityVerdict",
    "CanonicalDocument",
    "SourceMetadata",
    "PageContent",
    "ManifestEntry",
]
