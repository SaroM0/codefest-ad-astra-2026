"""Parser PBF (Mapbox Vector Tile). Implementado y DESHABILITADO por defecto.

73 teselas, 11.906 features. Son protobuf **CRUDO, sin comprimir** (empiezan por `0x1a`,
no por `1f 8b`): `gzip.decompress()` falla. Se pasan directo a `mapbox_vector_tile.decode`.

Está deshabilitado porque el CSV de Amazon Underworld ya contiene todos los atributos;
los PBF sólo aportan la geometría. Procesarlos ahora duplicaría información sin mejorar
el retrieval textual. Se deja implementado para que activarlo sea un flag, no un proyecto.
"""

from __future__ import annotations

from pathlib import Path

from .base import BlockBuilder, ParseResult


class PBFParser:
    enabled = False

    def parse(self, path: Path, doc_id: str, pipeline_version: str) -> ParseResult:
        result = ParseResult()
        if not self.enabled:
            result.metadata = {"schema": "vector_tile", "processed": False}
            result.warnings.append(
                "pbf_disabled__attributes_already_in_amazon_underworld_csv"
            )
            return result

        import mapbox_vector_tile

        builder = BlockBuilder(doc_id, pipeline_version)
        # SIN gzip.decompress(): son protobuf crudo.
        tile = mapbox_vector_tile.decode(path.read_bytes())

        features = 0
        for layer_name, layer in tile.items():
            for i, feature in enumerate(layer.get("features", []), start=1):
                props = feature.get("properties") or {}
                if not props:
                    continue
                features += 1
                text = "; ".join(f"{k}: {v}" for k, v in props.items() if v not in (None, ""))
                if block := builder.add(
                    text,
                    "table_row",
                    "structured",
                    row=i,
                    structured_data={"layer": layer_name, **props},
                ):
                    result.blocks.append(block)

        result.metadata = {
            "schema": "vector_tile",
            "processed": True,
            "layers": list(tile.keys()),
            "features": features,
        }
        return result
