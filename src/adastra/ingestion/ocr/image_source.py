"""De dónde sale la imagen que se OCRiza.

Preferencia: **extraer el JPEG ya embebido** antes que rasterizar la página.

Las 47 Alertas Tempranas son escaneos JPEG RGB de 2547×3510 px (300 dpi para A4).
`page.get_pixmap(dpi=300)` decodifica ese JPEG y lo vuelve a codificar: una generación de
pérdida gratuita, además de más lento. Sólo se rasteriza cuando la página no es una única
imagen a página completa (p.ej. escaneos fragmentados en tiles).
"""

from __future__ import annotations

from dataclasses import dataclass

from .. import config


@dataclass
class PageImage:
    data: bytes
    source: str  # "embedded" | "rendered"
    width: int
    height: int


def _full_page_image_xref(page, coverage_threshold: float = 0.85) -> int | None:
    """Devuelve el xref de la única imagen que cubre casi toda la página, si la hay."""
    try:
        infos = page.get_image_info(xrefs=True)
    except Exception:
        return None

    # Un escaneo fragmentado en miles de tiles (14.623 en un MAPP-OEA) no tiene una
    # imagen de página completa: hay que rasterizar.
    if not infos or len(infos) > 4:
        return None

    rect = page.rect
    page_area = float(rect.width * rect.height) or 1.0
    for info in infos:
        bbox = info.get("bbox")
        xref = info.get("xref")
        if not bbox or not xref:
            continue
        area = max(0.0, bbox[2] - bbox[0]) * max(0.0, bbox[3] - bbox[1])
        if area / page_area >= coverage_threshold:
            return int(xref)
    return None


def get_page_image(doc, page, dpi: int = config.OCR_RENDER_DPI) -> PageImage:
    """Imagen de la página lista para OCR, evitando el re-muestreo cuando se puede."""
    xref = _full_page_image_xref(page)
    if xref:
        try:
            extracted = doc.extract_image(xref)
            data = extracted.get("image")
            if data:
                return PageImage(
                    data=data,
                    source="embedded",
                    width=int(extracted.get("width") or 0),
                    height=int(extracted.get("height") or 0),
                )
        except Exception:
            pass  # cae a rasterizado

    pix = page.get_pixmap(dpi=dpi)
    return PageImage(
        data=pix.tobytes("png"), source="rendered", width=pix.width, height=pix.height
    )


def domain_vocabulary(alert_metadata: list[dict]) -> list[str]:
    """Vocabulario para `--user-words`: municipios, departamentos y códigos de alerta.

    289 municipios y 363 códigos conocidos de antemano son la mejora de precisión más
    barata disponible, y ningún motor genérico la explota por su cuenta.
    """
    words: set[str] = set()
    for meta in alert_metadata:
        if code := meta.get("alert_code"):
            words.add(str(code))
        for muni in meta.get("municipalities") or []:
            for key in ("municipality", "department"):
                value = (muni.get(key) or "").strip()
                # Se añaden también los componentes: Tesseract casa palabras, no frases.
                if value:
                    words.add(value)
                    words.update(p for p in value.split() if len(p) > 3)
    return sorted(words)
