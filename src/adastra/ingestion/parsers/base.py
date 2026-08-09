"""Contrato común de los parsers y utilidades de construcción de bloques."""

from __future__ import annotations

from dataclasses import dataclass, field

from adastra.core.models import ContentBlock
from adastra.core.models.block import BlockType, ExtractionMethod


@dataclass
class ParseResult:
    """Salida de un parser antes de la capa de calidad."""

    blocks: list[ContentBlock] = field(default_factory=list)
    metadata: dict = field(default_factory=dict)
    metadata_warnings: list[str] = field(default_factory=list)
    warnings: list[str] = field(default_factory=list)

    pages_total: int | None = None
    pages_native: int = 0
    pages_ocr: int = 0
    pages_quarantined: int = 0

    # Sólo lo rellena la ruta PDF; la capa de calidad lo usa para los contrastes.
    page_texts: dict[int, str] = field(default_factory=dict)

    @property
    def text(self) -> str:
        return "\n\n".join(b.text for b in self.blocks if b.text)

    @property
    def characters(self) -> int:
        return sum(len(b.text) for b in self.blocks)


class BlockBuilder:
    """Genera bloques con IDs determinísticos y orden monótono.

    Los IDs incluyen la versión del pipeline: son posicionales, así que un cambio de
    segmentación los renumera. Sin la versión, las referencias guardadas por capas
    posteriores apuntarían en silencio a otro contenido — no fallaría, mentiría.
    """

    def __init__(self, doc_id: str, pipeline_version: str) -> None:
        self._doc_id = doc_id
        self._version = pipeline_version
        self._order = 0

    def add(
        self,
        text: str,
        block_type: BlockType,
        extraction_method: ExtractionMethod,
        *,
        page: int | None = None,
        row: int | None = None,
        bbox: tuple[float, float, float, float] | None = None,
        structured_data: dict | None = None,
        is_boilerplate: bool = False,
        segmentation_confidence: float = 1.0,
    ) -> ContentBlock | None:
        # Un bloque sin texto sólo es legítimo si transporta datos estructurados
        # (una fila de tabla con valores pero sin representación textual útil).
        if not text.strip() and structured_data is None:
            return None

        self._order += 1
        block = ContentBlock(
            block_id=f"{self._doc_id}:{self._version}:block:{self._order:06d}",
            type=block_type,
            text=text,
            order=self._order,
            page=page,
            row=row,
            bbox=bbox,
            structured_data=structured_data,
            extraction_method=extraction_method,
            is_boilerplate=is_boilerplate,
            segmentation_confidence=segmentation_confidence,
        )
        return block

    def rollback(self, blocks: list[ContentBlock]) -> None:
        """Devuelve el contador tras descartar bloques ya emitidos.

        Necesario cuando una ruta de segmentación se prueba y se rechaza: sin esto, los
        `order` quedarían con huecos y la invariante I8 (orden monótono sin saltos)
        dejaría de reflejar la posición real del bloque en el documento.
        """
        self._order -= len(blocks)
