import os
import json
from pathlib import Path

import faiss
import numpy as np
from sentence_transformers import SentenceTransformer

from adastra.core.jsonl import read_jsonl
from adastra.core.paths import ArtifactPaths

MODEL_NAME = "BAAI/bge-m3"

REQUIRED_METADATA_FIELDS = {
    "doc_id", "chunk_id", "fuente", "formato", 
    "fenomeno", "posicion", "num_tokens", "texto"
}

def validate_chunk_metadata(chunks: list[dict]) -> None:
    """Valida que los chunks contengan todos los campos obligatorios del reto."""
    if not chunks:
        raise ValueError("El archivo de chunks está vacío.")
    
    first_chunk = chunks[0]
    missing = REQUIRED_METADATA_FIELDS - set(first_chunk.keys())
    if missing:
        raise KeyError(
            f"Faltan campos obligatorios en la metadata de los chunks: {missing}. "
            f"Revisa el pipeline de Chunking (Etapa 2)."
        )

def build_vector_index() -> None:
    paths = ArtifactPaths()
    paths.embeddings.ensure("reports")
    
    chunks_file = paths.chunks
    
    print(f"Leyendo fragmentos desde {chunks_file}...")
    chunks = list(read_jsonl(chunks_file))
    
    validate_chunk_metadata(chunks)
    
    limit_env = os.environ.get("LIMIT_EMBEDDINGS")
    if limit_env:
        try:
            limit_val = int(limit_env)
            print(f"LIMIT_EMBEDDINGS detectado: limitando a los primeros {limit_val} chunks para pruebas.")
            chunks = chunks[:limit_val]
        except ValueError:
            print(f"Advertencia: LIMIT_EMBEDDINGS '{limit_env}' no es un entero válido.")
    
    texts = [c["texto"] for c in chunks]
    
    print(f"Cargando modelo de embeddings: {MODEL_NAME}...")
    model = SentenceTransformer(MODEL_NAME)
    
    print(f"Generando embeddings para {len(texts)} chunks...")
    embeddings = model.encode(
        texts, 
        batch_size=32, 
        show_progress_bar=True, 
        convert_to_numpy=True
    )
    
    faiss.normalize_L2(embeddings)
    
    d = embeddings.shape[1]
    index = faiss.IndexFlatIP(d)
    index.add(embeddings)
    
    def save_artifacts(target_dir: Path) -> None:
        target_dir.mkdir(parents=True, exist_ok=True)
        faiss.write_index(index, str(target_dir / "index.faiss"))
        
        with open(target_dir / "metadata.jsonl", "w", encoding="utf-8") as f:
            for chunk in chunks:
                f.write(json.dumps(chunk, ensure_ascii=False) + "\n")

    print("Guardando artefactos en artifacts/embeddings...")
    save_artifacts(paths.embeddings.root)
    
    entrega_dir = paths.entrega_encoder_bge
    print(f"Guardando copia estructurada para la entrega en {entrega_dir}...")
    save_artifacts(entrega_dir)
            
    print(f"Proceso finalizado con éxito.")

if __name__ == "__main__":
    build_vector_index()