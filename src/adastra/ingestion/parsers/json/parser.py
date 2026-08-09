"""Router de esquemas JSON.

964 archivos, 0 errores de parseo, 100% UTF-8, 0 BOM. Es la ruta barata del corpus.
El detector prueba los adapters en orden de especificidad: Alertas primero (tiene un campo
inconfundible), luego CENIA, luego artículo genérico.
"""

from __future__ import annotations

import json
from pathlib import Path

from ..base import BlockBuilder, ParseResult
from .adapters import AlertasAdapter, ArticleAdapter, CENIAAdapter, JournalAdapter

# Orden importante: del esquema más específico al más genérico.
_ADAPTERS = (AlertasAdapter(), JournalAdapter(), CENIAAdapter(), ArticleAdapter())

# Claves que contienen texto recuperable en esquemas no catalogados.
_TEXT_KEYS = ("text", "content", "body", "descripcion", "description", "abstract",
              "paragraphs", "sections", "valor", "value")


def _collect_text(node: object, depth: int = 0, out: list[str] | None = None) -> list[str]:
    """Recorre un esquema desconocido recogiendo texto de las claves de contenido.

    Sólo desciende por claves que sabemos que transportan contenido: recoger TODA cadena
    del JSON metería URLs, IDs y timestamps en el texto recuperable.
    """
    if out is None:
        out = []
    if depth > 6:
        return out

    if isinstance(node, str):
        value = node.strip()
        if len(value) >= 40:  # descarta etiquetas, IDs y fragmentos sin valor semántico
            out.append(value)
    elif isinstance(node, list):
        for item in node:
            _collect_text(item, depth + 1, out)
    elif isinstance(node, dict):
        for key, value in node.items():
            if key.lower() in _TEXT_KEYS or isinstance(value, (dict, list)):
                _collect_text(value, depth + 1, out)
    return out


def detect_adapter(payload: dict):
    for adapter in _ADAPTERS:
        if adapter.matches(payload):
            return adapter
    return None


def parse_json(
    path: Path,
    doc_id: str,
    pipeline_version: str,
    observatory_code: str,
) -> ParseResult:
    raw = path.read_text(encoding="utf-8")
    payload = json.loads(raw)  # falla ruidosamente si no es JSON válido — es lo correcto

    builder = BlockBuilder(doc_id, pipeline_version)

    # Una lista vacía es un documento legítimo y vacío: DEFENSA21_articulos-2.json es
    # `[]` porque los 5 feeds RSS devolvieron error. No es un fallo del parser.
    if isinstance(payload, list):
        if not payload:
            result = ParseResult()
            result.warnings.append("empty_list__source_produced_no_documents")
            result.metadata = {"schema": "empty_list"}
            return result
        # Lista de artículos en un solo archivo: se concatenan como un documento.
        result = ParseResult()
        result.metadata = {"schema": "article_list", "items": len(payload)}
        adapter = ArticleAdapter()
        for item in payload:
            if not isinstance(item, dict):
                continue
            partial = adapter.parse(item, builder, observatory_code)
            result.blocks.extend(partial.blocks)
            result.metadata_warnings.extend(partial.metadata_warnings)
        return result

    if not isinstance(payload, dict):
        result = ParseResult()
        result.warnings.append(f"unexpected_json_root:{type(payload).__name__}")
        return result

    adapter = detect_adapter(payload)
    if adapter is None:
        # Esquema no reconocido: se emite el texto que haya, marcado como tal, en vez de
        # descartarlo en silencio.
        result = ParseResult()
        result.metadata = {"schema": "unrecognized", "keys": sorted(payload)[:20]}
        result.warnings.append("unrecognized_json_schema")
        for text in _collect_text(payload):
            # `page_text` con confianza baja: no sabemos si es un párrafo, así que no
            # lo etiquetamos como tal. Mejor un tipo honesto que uno inventado.
            if block := builder.add(
                text, "page_text", "structured", segmentation_confidence=0.3
            ):
                result.blocks.append(block)
        return result

    result = adapter.parse(payload, builder, observatory_code)
    result.metadata.setdefault("schema", adapter.name)
    return result
