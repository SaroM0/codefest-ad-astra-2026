"""Extracción nativa con poppler, DOBLE y por página.

Se ejecuta `pdftotext` dos veces por documento (modo por defecto y `-layout`) y se elige
por página. El coste es despreciable —segundos por documento sobre 760 PDFs— frente al
valor de no destruir el orden de lectura de ~150 documentos maquetados a dos columnas.

Nota sobre stderr: 125 PDFs emiten avisos de sintaxis (mayoría `Invalid Font Weight` en
AI Index). Son inocuos: `exit code 0` y texto correcto. Sólo los 2 HTML disfrazados
devuelven `exit code 1`. No confundir stderr con fallo.
"""

from __future__ import annotations

import subprocess
from pathlib import Path

_PAGE_BREAK = "\f"


def _run(args: list[str], timeout: int) -> tuple[str, str, int]:
    proc = subprocess.run(args, capture_output=True, timeout=timeout, check=False)
    return (
        proc.stdout.decode("utf-8", "replace"),
        proc.stderr.decode("utf-8", "replace"),
        proc.returncode,
    )


def extract_pages(
    path: Path,
    page_count: int,
    *,
    layout: bool,
    timeout: int = 900,
) -> list[str]:
    """Devuelve una lista de `page_count` cadenas, una por página.

    Se pide el documento completo de una vez y se parte por form feed **para separar la
    salida de pdftotext**, que sí emite un `\\f` fiable entre páginas. Eso NO contradice
    la invariante I5: el número de páginas viene del inspector, y aquí sólo se usa para
    alinear. Si el reparto no cuadra (los 6 ESA con form feeds espurios), se cae al modo
    página a página, que es exacto.
    """
    args = ["pdftotext"]
    if layout:
        args.append("-layout")
    args += ["-enc", "UTF-8", str(path), "-"]

    stdout, _, code = _run(args, timeout)
    if code != 0:
        raise RuntimeError(f"pdftotext_failed:exit_{code}")

    parts = stdout.split(_PAGE_BREAK)
    # pdftotext emite un \f final: sobra una parte vacía.
    if parts and not parts[-1].strip():
        parts = parts[:-1]

    if len(parts) == page_count:
        return parts

    # Desalineación: form feeds espurios dentro del contenido (los 6 informes ESA tienen
    # 343 \f para 144 páginas). Se extrae página a página, que es exacto aunque más lento.
    return _extract_page_by_page(path, page_count, layout=layout, timeout=timeout)


def _extract_page_by_page(
    path: Path,
    page_count: int,
    *,
    layout: bool,
    timeout: int,
) -> list[str]:
    pages: list[str] = []
    for n in range(1, page_count + 1):
        args = ["pdftotext"]
        if layout:
            args.append("-layout")
        args += ["-f", str(n), "-l", str(n), "-enc", "UTF-8", str(path), "-"]
        try:
            stdout, _, code = _run(args, timeout=120)
        except subprocess.TimeoutExpired:
            pages.append("")
            continue
        pages.append(stdout.replace(_PAGE_BREAK, "") if code == 0 else "")
    return pages


def extract_both(path: Path, page_count: int) -> tuple[list[str], list[str]]:
    """Las dos extracciones, alineadas a `page_count` páginas."""
    default = extract_pages(path, page_count, layout=False)
    layout = extract_pages(path, page_count, layout=True)

    # Normalización defensiva de longitud: el resto del pipeline asume 1:1 con las
    # páginas del inspector.
    def fit(pages: list[str]) -> list[str]:
        if len(pages) < page_count:
            return pages + [""] * (page_count - len(pages))
        return pages[:page_count]

    return fit(default), fit(layout)
