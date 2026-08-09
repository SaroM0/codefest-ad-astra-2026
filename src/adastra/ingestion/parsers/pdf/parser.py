"""Pipeline PDF completo. El 97% del texto del corpus pasa por aquí.

    inspector → extracción dual → reading-order scorer → limpieza → gate por página
              → OCR selectivo → segmentación → bloques tipados
"""

from __future__ import annotations

from pathlib import Path

from adastra.core.models import PageContent

from ... import config
from ...language.detector import detect
from ...normalization.unicode_clean import clean_text
from ...ocr.engine import OCRUnavailable, TesseractOCR, lang_for
from ...ocr.rapid import best_available_engine
from ...ocr.image_source import get_page_image
from ...quality.page_gate import evaluate_page
from ..base import BlockBuilder, ParseResult
from .inspector import inspect
from .poppler import extract_both
from .reading_order import choose
from .segmentation import detect_boilerplate, segment_plain_text, segment_tagged_page

# La ruta etiquetada sólo se acepta si conserva al menos esta fracción del texto que
# poppler ve en la misma página. Es una mejora de TIPADO, nunca una fuente alternativa.
TAGGED_MIN_COVERAGE = 0.95


def parse_pdf(
    path: Path,
    doc_id: str,
    pipeline_version: str,
    *,
    ocr_engine: TesseractOCR | None = None,
    enable_ocr: bool = True,
) -> ParseResult:
    result = ParseResult()

    info = inspect(path)
    result.warnings.extend(info.warnings)
    result.pages_total = info.page_count

    if info.page_count < 1:
        result.warnings.append("no_pages")
        return result

    # --- 1. extracción dual -------------------------------------------------------
    default_pages, layout_pages = extract_both(path, info.page_count)

    # --- 2. idioma a nivel documento (para puntuar y para elegir modelo de OCR) ----
    sample = "\n".join(default_pages[:12])[:200_000]
    sample_clean, _ = clean_text(sample)
    language, lang_conf, script_dist, script = detect(sample_clean)

    # --- 3. boilerplate: se detecta para MARCAR, nunca para eliminar --------------
    boilerplate = detect_boilerplate(default_pages)

    # --- 4. por página: elegir modo, limpiar, evaluar -----------------------------
    pages: list[PageContent] = []
    nul_total = 0

    for i, page_info in enumerate(info.pages):
        n = page_info.number
        raw_default = default_pages[i] if i < len(default_pages) else ""
        raw_layout = layout_pages[i] if i < len(layout_pages) else ""

        chosen, method, scores, tabular = choose(
            raw_default, raw_layout, language, script
        )
        cleaned, stats = clean_text(chosen, collapse_spaces=False)
        nul_total += stats["nul"]

        quality = evaluate_page(
            n, cleaned, page_info.image_coverage, language, script
        )
        pages.append(
            PageContent(
                page_number=n,
                text=cleaned,
                extraction_method=method,  # type: ignore[arg-type]
                quality=quality,
                reading_order_scores=scores,
                is_tabular=tabular,
            )
        )

    if nul_total:
        # Los 6 informes ESA traen hasta 38.337 NUL por archivo. Tras quitarlos el texto
        # es correcto: no es mojibake y no requiere OCR.
        result.warnings.append(f"nul_bytes_cleaned:{nul_total}")

    # --- 5. OCR selectivo, sólo en las páginas que lo piden -----------------------
    ocr_pages = [p for p in pages if p.quality.verdict == "ocr"]
    if ocr_pages and enable_ocr:
        engine = ocr_engine or best_available_engine()
        if engine is None:
            result.warnings.append(
                f"ocr_needed_but_unavailable:{len(ocr_pages)}_pages"
            )
        else:
            _run_ocr(path, pages, ocr_pages, engine, language, script, result)
    elif ocr_pages:
        result.warnings.append(f"ocr_disabled:{len(ocr_pages)}_pages_skipped")

    # --- 6. segmentación ----------------------------------------------------------
    builder = BlockBuilder(doc_id, pipeline_version)
    use_tagged = info.is_tagged
    tagged_doc = None
    if use_tagged:
        try:
            import pymupdf

            tagged_doc = pymupdf.open(path)
            if tagged_doc.needs_pass:
                tagged_doc.authenticate("")
        except Exception:
            tagged_doc = None
            use_tagged = False

    try:
        for page in pages:
            idx = page.page_number - 1
            blocks: list = []

            # Ruta A: PDF etiquetado. PyMuPDF devuelve bloques en orden de lectura, así
            # que evita el problema del multicolumna por construcción.
            #
            # PERO la ruta etiquetada es una MEJORA de tipado, no una fuente alternativa
            # de texto: en algunos PDFs `get_text("dict")` devuelve bastante menos
            # contenido que poppler (UNOOSA_st-space-61rev03a perdía el 48%). Aceptarla
            # sin comparar convierte una mejora en una pérdida silenciosa. Por eso se
            # contrasta contra el texto de poppler y sólo se conserva si no pierde nada.
            if use_tagged and tagged_doc is not None and page.extraction_method != "ocr":
                try:
                    blocks = segment_tagged_page(
                        tagged_doc[idx], page.page_number, builder, boilerplate
                    )
                except Exception:
                    blocks = []

                if blocks:
                    tagged_chars = len(
                        "".join("".join(b.text for b in blocks).split())
                    )
                    native_chars = len("".join(page.text.split()))
                    if tagged_chars < native_chars * TAGGED_MIN_COVERAGE:
                        builder.rollback(blocks)
                        result.warnings.append(
                            f"tagged_route_dropped_text:page_{page.page_number}:"
                            f"{tagged_chars}_of_{native_chars}"
                        )
                        blocks = []

            # Ruta B: texto plano con reglas explícitas.
            if not blocks:
                blocks = segment_plain_text(
                    page.text,
                    page.page_number,
                    builder,
                    page.extraction_method,  # type: ignore[arg-type]
                    boilerplate,
                    tabular=page.is_tabular,
                )

            # Ruta C: fallback honesto. No se etiqueta como `paragraph` lo que no se
            # sabe que lo sea.
            if not blocks and page.text.strip():
                if block := builder.add(
                    page.text,
                    "page_text",
                    page.extraction_method,  # type: ignore[arg-type]
                    page=page.page_number,
                    segmentation_confidence=0.3,
                ):
                    blocks = [block]

            result.blocks.extend(blocks)
            result.page_texts[page.page_number] = page.text
    finally:
        if tagged_doc is not None:
            tagged_doc.close()

    # --- 7. contabilidad ----------------------------------------------------------
    result.pages_native = sum(1 for p in pages if p.extraction_method != "ocr")
    result.pages_ocr = sum(1 for p in pages if p.extraction_method == "ocr")
    result.pages_quarantined = sum(
        1 for p in pages if p.quality.verdict == "ocr" and p.extraction_method != "ocr"
    )

    layout_chosen = sum(1 for p in pages if p.extraction_method == "native_layout")
    result.metadata = {
        "schema": "pdf",
        "page_count": info.page_count,
        "is_tagged": info.is_tagged,
        "is_encrypted": info.is_encrypted,
        "pdf_version": info.pdf_version,
        "producer": info.producer,
        "creator": info.creator,
        "language": language,
        "language_confidence": lang_conf,
        "script": script,
        "script_distribution": {k: round(v, 4) for k, v in list(script_dist.items())[:5]},
        "pages_layout_mode": layout_chosen,
        "pages_reading_order_mode": info.page_count - layout_chosen,
        "pages_tabular": sum(1 for p in pages if p.is_tabular),
        "boilerplate_lines": len(boilerplate),
        "segmentation_route": "tagged" if use_tagged else "plain",
        "page_quality": [
            {
                "page": p.page_number,
                "verdict": p.quality.verdict,
                "method": p.extraction_method,
                "chars": p.quality.characters,
                "image_coverage": p.quality.image_coverage,
                "reasons": p.quality.reasons,
            }
            for p in pages
            if p.quality.verdict != "accept" or p.extraction_method == "ocr"
        ],
    }
    return result


def _run_ocr(
    path: Path,
    pages: list[PageContent],
    ocr_pages: list[PageContent],
    engine,
    language: str | None,
    script: str | None,
    result: ParseResult,
) -> None:
    import pymupdf

    lang = lang_for(script, language) if isinstance(engine, TesseractOCR) else (language or "es")

    doc = pymupdf.open(path)
    if doc.needs_pass:
        doc.authenticate("")

    try:
        by_number = {p.page_number: p for p in pages}
        for target in ocr_pages:
            try:
                page = doc[target.page_number - 1]
                image = get_page_image(doc, page)
                ocr = engine.extract(image.data, lang=lang)
            except OCRUnavailable:
                result.warnings.append("ocr_unavailable")
                return
            except Exception as exc:
                result.warnings.append(
                    f"ocr_failed:page_{target.page_number}:{type(exc).__name__}"
                )
                continue

            text, _ = clean_text(ocr.text, collapse_spaces=False)
            quality = evaluate_page(
                target.page_number,
                text,
                target.quality.image_coverage,
                language,
                script,
            )

            # Sólo se sustituye si el OCR mejora. Un OCR peor que el texto nativo se
            # descarta y la página queda en cuarentena, registrada.
            native_chars = target.quality.characters
            if len(text.strip()) > max(native_chars, config.PAGE_EMPTY_MAX_CHARS):
                page_content = by_number[target.page_number]
                page_content.text = text
                page_content.extraction_method = "ocr"
                page_content.quality = quality
                page_content.quality.verdict = (
                    "accept" if quality.verdict != "ocr" else "review"
                )
                page_content.warnings.append(f"ocr_image_source:{image.source}")
            else:
                target.warnings.append("ocr_did_not_improve")
    finally:
        doc.close()
