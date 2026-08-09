"""Detección de formato real por magic bytes.

Nunca confiar en la extensión: dos `.pdf` del corpus son en realidad HTML (descargas
fallidas donde el servidor devolvió una página de error). `pdfinfo` emite
`May not be a PDF file`; sin este filtro el pipeline intentaría extraerlos y produciría
basura o un fallo confuso.
"""

from __future__ import annotations

_SIGNATURES: tuple[tuple[bytes, str], ...] = (
    (b"%PDF", "pdf"),
    (b"\x89PNG\r\n\x1a\n", "png"),
    (b"\xff\xd8\xff", "jpeg"),
    (b"GIF87a", "gif"),
    (b"GIF89a", "gif"),
    (b"PK\x03\x04", "zip"),  # xlsx/docx
    (b"\x1f\x8b", "gzip"),
)

_HTML_MARKERS = (b"<!doctype", b"<html", b"<?xml", b"<head", b"<body")

# Extensión declarada → formato que debería tener
_EXPECTED_BY_EXT = {
    ".pdf": "pdf",
    ".json": "json",
    ".csv": "csv",
    ".tsv": "csv",
    ".xlsx": "zip",
    ".txt": "text",
    ".jpg": "jpeg",
    ".jpeg": "jpeg",
    ".png": "png",
    ".avif": "avif",
    ".pbf": "pbf",
}


def detect_format(magic: bytes, extension: str) -> str:
    """Devuelve el formato real deducido de los primeros bytes."""
    for sig, fmt in _SIGNATURES:
        if magic.startswith(sig):
            if fmt == "zip" and extension == ".xlsx":
                return "xlsx"
            return fmt

    head = magic[:16].lstrip().lower()
    if any(head.startswith(m) for m in _HTML_MARKERS):
        return "html"

    # AVIF/HEIF: caja ftyp en el offset 4.
    if len(magic) >= 12 and magic[4:8] == b"ftyp":
        return "avif"

    # Mapbox Vector Tile v2: protobuf CRUDO, sin gzip. Empieza por el field-tag 0x1a
    # (layer, wire type 2). Si empezara por 1f 8b sería gzip — no es el caso.
    if extension == ".pbf" and magic[:1] == b"\x1a":
        return "pbf"

    if extension in (".json", ".csv", ".tsv", ".txt"):
        # Formatos de texto: no tienen magic. Se confía en la extensión, y el parser
        # correspondiente valida (json.loads / csv.reader) — ahí sí falla ruidosamente.
        return _EXPECTED_BY_EXT[extension]

    return "unknown"


def is_mismatch(detected: str, extension: str) -> bool:
    expected = _EXPECTED_BY_EXT.get(extension)
    if expected is None or detected == "unknown":
        return False
    if extension == ".xlsx":
        return detected not in ("xlsx", "zip")
    return detected != expected
