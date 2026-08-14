"""Etapa 3: chunks normalizados → embeddings BGE-M3 → índice FAISS.

El índice usa producto interno sobre vectores normalizados L2, equivalente a
similitud coseno. El orden de inserción en FAISS es exactamente el orden escrito
en ``metadata.jsonl``: ID FAISS ``i`` ↔ línea ``i`` de metadata.
"""

from __future__ import annotations

import importlib.metadata
import json
import shutil
import tempfile
from collections.abc import Iterable, Iterator
from pathlib import Path
from typing import Any

from adastra.core.jsonl import read_jsonl
from adastra.core.paths import ArtifactPaths

MODEL_NAME = "BAAI/bge-m3"
DEFAULT_BATCH_SIZE = 64
DEFAULT_MAX_LENGTH = 8192

REQUIRED_METADATA_FIELDS = {
    "doc_id", "chunk_id", "fuente", "formato", "fenomeno", "posicion", "num_tokens", "texto"
}


def _load_embedding_dependencies() -> tuple[Any, Any, Any]:
    """Carga opcionalmente las dependencias pesadas sólo al ejecutar embeddings."""
    try:
        import faiss  # type: ignore
        import numpy as np
        from FlagEmbedding import BGEM3FlagModel  # type: ignore
    except ImportError as exc:
        raise RuntimeError(
            "Faltan dependencias de embeddings. Instala el extra del proyecto con "
            "`pip install -e '.[embeddings]'` o instala FlagEmbedding y faiss-cpu."
        ) from exc
    return faiss, np, BGEM3FlagModel


def validate_chunk_metadata(chunks: Iterable[dict[str, Any]]) -> None:
    """Comprueba que todo chunk satisface el contrato requerido por el reto."""
    seen = False
    for line_number, chunk in enumerate(chunks, start=1):
        seen = True
        missing = REQUIRED_METADATA_FIELDS - set(chunk)
        if missing:
            raise KeyError(f"Chunk {line_number}: faltan campos obligatorios: {sorted(missing)}")
        if not isinstance(chunk["texto"], str) or not chunk["texto"].strip():
            raise ValueError(f"Chunk {line_number}: texto vacío o inválido")
    if not seen:
        raise ValueError("El archivo de chunks está vacío.")


def _batches(items: Iterable[dict[str, Any]], batch_size: int) -> Iterator[list[dict[str, Any]]]:
    batch: list[dict[str, Any]] = []
    for item in items:
        batch.append(item)
        if len(batch) == batch_size:
            yield batch
            batch = []
    if batch:
        yield batch


def _version(distribution: str) -> str | None:
    try:
        return importlib.metadata.version(distribution)
    except importlib.metadata.PackageNotFoundError:
        return None


def _model_device(model: Any) -> str:
    """Obtiene el dispositivo efectivo sin depender de detalles internos de FlagEmbedding."""
    for attribute in ("model", "encoder"):
        candidate = getattr(model, attribute, None)
        try:
            return str(next(candidate.parameters()).device)
        except (AttributeError, StopIteration):
            continue
    return "auto"


def load_encoder(model_name: str = MODEL_NAME) -> tuple[Any, Any, Any]:
    """Carga BGE-M3 para indexación o retrieval usando la misma configuración."""
    faiss, np, BGEM3FlagModel = _load_embedding_dependencies()
    try:
        import torch

        use_fp16 = bool(torch.cuda.is_available())
    except ImportError:
        use_fp16 = False
    return BGEM3FlagModel(model_name, use_fp16=use_fp16), faiss, np


def encode_dense_texts(
    model: Any,
    texts: list[str],
    *,
    batch_size: int = DEFAULT_BATCH_SIZE,
    max_length: int = DEFAULT_MAX_LENGTH,
) -> Any:
    """Codifica textos en el espacio BGE-M3 y devuelve vectores L2-normalizados.

    Retrieval debe llamar esta función para preguntas: asegura idéntico pooling
    (``dense_vecs``), longitud máxima y normalización que la indexación.
    """
    if not texts:
        raise ValueError("Se requiere al menos un texto para generar embeddings")
    faiss, np, _ = _load_embedding_dependencies()
    encoded = model.encode(
        texts,
        batch_size=batch_size,
        max_length=max_length,
        return_dense=True,
        return_sparse=False,
        return_colbert_vecs=False,
    )
    vectors = np.ascontiguousarray(encoded["dense_vecs"], dtype="float32")
    if vectors.ndim != 2 or vectors.shape[0] != len(texts):
        raise ValueError("El encoder devolvió una matriz de embeddings incompatible")
    if not np.isfinite(vectors).all():
        raise ValueError("El encoder devolvió embeddings no finitos")
    faiss.normalize_L2(vectors)
    return vectors


def _replace_directory(source: Path, target: Path) -> None:
    """Publica un directorio completo sólo cuando su construcción terminó bien."""
    if target.exists():
        shutil.rmtree(target)
    source.replace(target)


def build_vector_index(
    *,
    artifacts_root: Path | str | None = None,
    model_name: str = MODEL_NAME,
    model_reference: str | None = None,
    batch_size: int = DEFAULT_BATCH_SIZE,
    max_length: int = DEFAULT_MAX_LENGTH,
    limit: int | None = None,
    write_delivery_copy: bool = True,
) -> dict[str, Any]:
    """Construye embeddings densos normalizados e índice FAISS reproducible.

    ``BGEM3FlagModel`` genera ``dense_vecs`` en el mismo espacio que debe usar el
    retrieval para codificar sus consultas. No se mezcla ningún encoder alternativo.
    """
    if batch_size < 1:
        raise ValueError("batch_size debe ser mayor que cero")
    if max_length < 1:
        raise ValueError("max_length debe ser mayor que cero")
    if limit is not None and limit < 1:
        raise ValueError("limit debe ser mayor que cero cuando se especifica")

    root = Path(artifacts_root) if artifacts_root is not None else ArtifactPaths().root
    paths = ArtifactPaths(root)
    chunks_file = paths.chunks
    if not chunks_file.is_file():
        raise FileNotFoundError(f"No existe {chunks_file}. Ejecuta chunking antes de embeddings.")

    print(f"Cargando encoder multilingüe {model_name}...")
    model, faiss, np = load_encoder(model_name)
    try:
        import torch

        use_fp16 = bool(torch.cuda.is_available())
    except ImportError:
        use_fp16 = False

    output_parent = paths.embeddings.root.parent
    output_parent.mkdir(parents=True, exist_ok=True)
    temporary_root = Path(tempfile.mkdtemp(prefix="embeddings-build-", dir=output_parent))
    metadata_file = temporary_root / "metadata.jsonl"
    index: Any | None = None
    count = 0
    max_chunk_tokens = 0
    max_chunk_characters = 0

    try:
        source: Iterable[dict[str, Any]] = read_jsonl(chunks_file)
        if limit is not None:
            from itertools import islice

            source = islice(source, limit)

        with metadata_file.open("w", encoding="utf-8") as metadata_handle:
            for batch in _batches(source, batch_size):
                validate_chunk_metadata(batch)
                texts = [chunk["texto"] for chunk in batch]
                vectors = encode_dense_texts(
                    model, texts, batch_size=batch_size, max_length=max_length
                )
                if index is None:
                    index = faiss.IndexFlatIP(int(vectors.shape[1]))
                elif index.d != vectors.shape[1]:
                    raise ValueError("El encoder devolvió una dimensión diferente entre batches")
                index.add(vectors)

                for chunk in batch:
                    metadata_handle.write(json.dumps(chunk, ensure_ascii=False) + "\n")
                    count += 1
                    max_chunk_tokens = max(max_chunk_tokens, int(chunk["num_tokens"]))
                    max_chunk_characters = max(max_chunk_characters, len(chunk["texto"]))

        if index is None or count == 0:
            raise ValueError("No se generaron embeddings: no había chunks utilizables")

        faiss.write_index(index, str(temporary_root / "index.faiss"))
        manifest = {
            "model": model_reference or model_name,
            "model_load_path": str(Path(model_name).resolve()) if Path(model_name).exists() else None,
            "model_revision": Path(model_name).name if Path(model_name).is_dir() else None,
            "encoder_library": "FlagEmbedding.BGEM3FlagModel",
            "pooling": "dense_vecs nativo de BGE-M3",
            "normalization": "L2 antes de IndexFlatIP; producto interno equivale a coseno",
            "faiss_index": "IndexFlatIP",
            "dimension": int(index.d),
            "vectors": int(index.ntotal),
            "metadata_lines": count,
            "faiss_id_mapping": "FAISS ID i corresponde a la línea i (0-indexada) de metadata.jsonl",
            "batch_size": batch_size,
            "max_length": max_length,
            "max_chunk_num_tokens": max_chunk_tokens,
            "max_chunk_characters": max_chunk_characters,
            "device": _model_device(model),
            "use_fp16": use_fp16,
            "dependencies": {
                "FlagEmbedding": _version("FlagEmbedding"),
                "faiss-cpu": _version("faiss-cpu"),
                "numpy": _version("numpy"),
                "torch": _version("torch"),
            },
        }
        (temporary_root / "reports").mkdir()
        (temporary_root / "reports" / "manifest.json").write_text(
            json.dumps(manifest, ensure_ascii=False, indent=2) + "\n", encoding="utf-8"
        )

        _replace_directory(temporary_root, paths.embeddings.root)
        if write_delivery_copy:
            paths.entrega_encoder_bge.parent.mkdir(parents=True, exist_ok=True)
            delivery_tmp = Path(tempfile.mkdtemp(prefix="embeddings-delivery-", dir=paths.entrega_encoder_bge.parent))
            shutil.copytree(paths.embeddings.root, delivery_tmp, dirs_exist_ok=True)
            _replace_directory(delivery_tmp, paths.entrega_encoder_bge)

        print(f"Embeddings terminados: {count} vectores de dimensión {index.d}.")
        return manifest
    except Exception:
        shutil.rmtree(temporary_root, ignore_errors=True)
        raise