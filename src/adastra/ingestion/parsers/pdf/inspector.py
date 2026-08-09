"""Inspección estructural del PDF, antes de extraer una sola letra.

De aquí sale el número de páginas — que viene de PyMuPDF/pdfinfo y NUNCA de contar `\\f`
(invariante I5): 6 informes ESA tienen form feeds espurios y paginar por `\\f` infla el
recuento del corpus en +955 páginas.
"""

from __future__ import annotations

import subprocess
from dataclasses import dataclass, field
from pathlib import Path

from ... import config


@dataclass
class PageInfo:
    number: int
    width: float
    height: float
    image_coverage: float = 0.0
    image_count: int = 0
    images_truncated: bool = False


@dataclass
class PdfInfo:
    page_count: int
    pages: list[PageInfo] = field(default_factory=list)
    is_encrypted: bool = False
    is_tagged: bool = False
    pdf_version: str | None = None
    producer: str | None = None
    creator: str | None = None
    warnings: list[str] = field(default_factory=list)


def _page_image_coverage(page) -> tuple[float, int, bool]:
    """Área de la página cubierta por imágenes, y cuántas hay.

    Se limita la enumeración: `MAPPOEA_2010-acompanando-una-oportunidad-para-la-paz.pdf`
    tiene 14.623 imágenes en 5 páginas (escaneo fragmentado en miles de tiles) y los
    atlas de RESDAL entre 800 y 1.400. Sin tope, el inspector se cuelga — y para decidir
    "página-imagen" basta el área cubierta, no el conteo.
    """
    rect = page.rect
    page_area = float(rect.width * rect.height) or 1.0
    covered = 0.0
    count = 0
    truncated = False

    try:
        infos = page.get_image_info()
    except Exception:
        return 0.0, 0, False

    for info in infos:
        count += 1
        if count > config.MAX_IMAGES_ENUMERATED_PER_PAGE:
            truncated = True
            break
        bbox = info.get("bbox")
        if not bbox:
            continue
        w = max(0.0, bbox[2] - bbox[0])
        h = max(0.0, bbox[3] - bbox[1])
        covered += w * h

    return min(covered / page_area, 1.0), count, truncated


def inspect(path: Path) -> PdfInfo:
    import pymupdf

    warnings: list[str] = []
    doc = pymupdf.open(path)

    # 88 PDFs del corpus vienen cifrados (AES-256: 46, AES: 38, RC4: 4) y 71 declaran
    # `copy:no`. Verificado: los 88 se extraen sin problema — son permisos declarativos.
    # Se intenta autenticar con contraseña vacía en vez de asumir que funcionará.
    if doc.needs_pass:
        if not doc.authenticate(""):
            doc.close()
            raise RuntimeError("pdf_encrypted_with_user_password")
        warnings.append("encrypted_empty_password")

    is_encrypted = bool(doc.is_encrypted)
    meta = doc.metadata or {}

    pages: list[PageInfo] = []
    for i, page in enumerate(doc, start=1):
        coverage, count, truncated = _page_image_coverage(page)
        if truncated:
            warnings.append(f"image_enumeration_truncated:page_{i}")
        pages.append(
            PageInfo(
                number=i,
                width=float(page.rect.width),
                height=float(page.rect.height),
                image_coverage=coverage,
                image_count=count,
                images_truncated=truncated,
            )
        )

    info = PdfInfo(
        page_count=doc.page_count,  # I5: de la estructura del PDF, jamás de contar \f
        pages=pages,
        is_encrypted=is_encrypted,
        is_tagged=_is_tagged(doc),
        pdf_version=meta.get("format"),
        producer=(meta.get("producer") or "").strip() or None,
        creator=(meta.get("creator") or "").strip() or None,
        warnings=warnings,
    )
    doc.close()
    return info


def _is_tagged(doc) -> bool:
    """¿Tiene estructura de accesibilidad? 361 de 760 PDFs la tienen.

    Es señal estructural gratuita (encabezados, tablas, orden de lectura) y habilita la
    ruta de segmentación de mayor calidad.
    """
    try:
        catalog = doc.pdf_catalog()
        if catalog is None:
            return False
        marked = doc.xref_get_key(catalog, "MarkInfo/Marked")
        if marked and str(marked[1]).lower() == "true":
            return True
        struct = doc.xref_get_key(catalog, "StructTreeRoot")
        return bool(struct and struct[0] != "null")
    except Exception:
        return False


def pdfinfo_page_count(path: Path) -> int | None:
    """Segunda opinión vía poppler. Se usa para contrastar, no como fuente principal."""
    try:
        out = subprocess.run(
            ["pdfinfo", str(path)],
            capture_output=True,
            timeout=60,
            check=False,
        )
        for line in out.stdout.decode("utf-8", "replace").splitlines():
            if line.startswith("Pages:"):
                return int(line.split()[1])
    except (subprocess.SubprocessError, ValueError, IndexError):
        return None
    return None
