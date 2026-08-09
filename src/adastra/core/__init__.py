"""Contrato compartido por las cuatro etapas.

    models/      el modelo canónico (CanonicalDocument, ContentBlock, calidad)
    paths        dónde escribe y lee cada etapa dentro de artifacts/
    jsonl        lectura/escritura de JSONL (streaming, tolerante a pydantic)
    documents    cargar documentos ya ingeridos SIN caer en la trampa de blocks_ref

Regla de imports del repo: **relativo dentro de una etapa, absoluto entre etapas.**
Dentro de `ingestion/` se escribe `from ..models import X`; para cruzar la frontera
se escribe `from adastra.core.models import X`. Así se ve de un vistazo cuándo una
línea está atravesando un límite del diseño.
"""

from .paths import ArtifactPaths, StagePaths, DEFAULT_ARTIFACTS
from .jsonl import read_jsonl, load_jsonl, write_jsonl, dump_line

__all__ = [
    "ArtifactPaths",
    "StagePaths",
    "DEFAULT_ARTIFACTS",
    "read_jsonl",
    "load_jsonl",
    "write_jsonl",
    "dump_line",
]
