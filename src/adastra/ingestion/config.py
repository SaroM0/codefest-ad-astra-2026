"""Configuración del pipeline de ingesta.

Todas las constantes de este módulo proceden de hechos **verificados** sobre el corpus y
documentados en docs/ARCHITECTURE_INGESTION.md §2. Cuando una constante es una expectativa
(p.ej. el número
de refs que debe resolver el catalog join), el pipeline la trata como test, no como estimación.
"""

from __future__ import annotations

import os
from pathlib import Path

# --------------------------------------------------------------------------------------
# Versiones por etapa (§14.3 del plan): la clave de cache se compone sólo de lo que
# afecta a esa etapa, para que tocar un umbral de calidad no invalide ~970 páginas de OCR.
# --------------------------------------------------------------------------------------
PIPELINE_VERSION = "v2"
EXTRACTOR_VERSION = "1.0.0"
OCR_VERSION = "1.0.0"
SEGMENTATION_VERSION = "1.0.0"
QUALITY_VERSION = "1.0.0"

# --------------------------------------------------------------------------------------
# Rutas
# --------------------------------------------------------------------------------------
DEFAULT_CORPUS = Path(
    os.environ.get("CODEFEST_CORPUS", "CORPUS CODEFEST AD ASTRA 2026")
).expanduser()

MASTER_INDEX = "Indice_Datos_Codefest.xlsx"
INVENTORY_SHEET = "Inventario de Archivos"
QUESTIONS_PDF = "Extracto_Preguntas_50_v2.pdf"
GOLD_SET_XLSX = "F3_Dinamicas_Territoriales/FASE ORDENADA CODEFEST.xlsx"

# --------------------------------------------------------------------------------------
# Reconciliación (§15.1). Invariante I2: 1826 + 13 + 9 = 1848.
# Los 13 extras se enumeran nominalmente: un extra no listado es un error, no una curiosidad.
# --------------------------------------------------------------------------------------
EXPECTED_INDEX_ENTRIES = 1826
EXPECTED_DISK_USEFUL = 1839
EXPECTED_DS_STORE = 9
EXPECTED_TOTAL_FILES = 1848

EXPECTED_EXTRAS: frozenset[str] = frozenset(
    {
        QUESTIONS_PDF,
        MASTER_INDEX,
        GOLD_SET_XLSX,
        "F3_Dinamicas_Territoriales/CEEEP/ceeep_catalogo.json",
        "F3_Dinamicas_Territoriales/CEEEP/ceeep_registro.json",
        "F3_Dinamicas_Territoriales/CEOBS/ceobs_full_catalogo.json",
        "F3_Dinamicas_Territoriales/CEOBS/ceobs_full_registro.json",
        "F3_Dinamicas_Territoriales/MAPP_OEA/mapp_catalogo.json",
        "F3_Dinamicas_Territoriales/MAPP_OEA/mapp_registro.json",
        "F3_Dinamicas_Territoriales/RESDAL/resdal_catalogo.json",
        "F3_Dinamicas_Territoriales/RESDAL/resdal_registro.json",
        "F3_Dinamicas_Territoriales/SIPRI/sipri_full_catalogo.json",
        "F3_Dinamicas_Territoriales/SIPRI/sipri_full_registro.json",
    }
)

# --------------------------------------------------------------------------------------
# Clasificación de roles (§5.2)
# --------------------------------------------------------------------------------------
NOISE_FILENAMES = frozenset({".DS_Store", "Thumbs.db"})

# Los 2 .pdf que en realidad son HTML: descargas fallidas (páginas de error del servidor),
# no documentos equivalentes. No se rescatan como contenido.
# La detección es por magic bytes; esta lista es la EXPECTATIVA contra la que se contrasta.
KNOWN_INVALID_SOURCES = frozenset(
    {
        "F3_Dinamicas_Territoriales/SIPRI/sipri_data/pdfs/SIPRI_22136.pdf",
        "F3_Dinamicas_Territoriales/SIPRI/sipri_data/pdfs/"
        "SIPRI_hsrc20lmip20report20320growth20employment20and20skills-1.pdf",
    }
)

# Skips deliberados (§5.3). Cada uno con motivo — I7: nada desaparece en silencio.
SKIP_EXTENSIONS: dict[str, str] = {
    ".pbf": "geometry_only__attributes_available_in_csv",
    ".avif": "profile_photo__no_informational_value",
}
SKIP_FILENAMES: dict[str, str] = {
    "AIINDEX_lit-covid-ai-covid-literature-csv.xlsx": (
        "exact_duplicate_of_csv__xlsx_corrupts_ids_to_scientific_notation"
    ),
}

# --------------------------------------------------------------------------------------
# PDF
# --------------------------------------------------------------------------------------
PDF_MAGIC = b"%PDF"

# MAPPOEA_2010-acompanando... tiene 14.623 imágenes en 5 páginas; los RESDAL atlas 800-1400.
# Enumerar sin límite cuelga el inspector. Para decidir "página-imagen" basta el área cubierta.
MAX_IMAGES_ENUMERATED_PER_PAGE = 200

# Una página se considera "cubierta por imagen" si el área de sus imágenes supera este ratio.
IMAGE_COVERAGE_THRESHOLD = 0.55

# Umbrales de página (§7.5). Multi-señal: nunca `chars/page < 50` como criterio único,
# porque aprobaría el CEOBS-Sudán (2.187 c/pág de basura).
PAGE_EMPTY_MAX_CHARS = 50
PAGE_LOW_TEXT_MAX_CHARS = 200

# Detección de página tabular en la salida -layout (§7.3).
COLUMN_GAP_MIN_SPACES = 8
COLUMN_GAP_MIN_LINE_LEN = 40
TABULAR_GAP_RATIO = 0.35   # ≥35% de líneas largas con hueco → tratar como tabla
COLUMNAR_GAP_RATIO = 0.08  # ≥8% → sospechar 2 columnas, dejar decidir al scorer

# --------------------------------------------------------------------------------------
# OCR (§7.6)
# --------------------------------------------------------------------------------------
OCR_LANG_BY_SCRIPT = {
    "latin": "spa+eng",
    "cyrillic": "rus",
    "arabic": "ara",
    "han": "chi_sim",
    "hangul": "kor",
    "kana": "jpn",
}
OCR_DEFAULT_LANG = "spa+eng"
OCR_PSM = "1"
OCR_RENDER_DPI = 300

# --------------------------------------------------------------------------------------
# Tabular (§9.1). Configuración determinista: nada de csv.Sniffer.
# --------------------------------------------------------------------------------------
CSV_SCHEMAS: dict[str, dict] = {
    # El único CSV del corpus delimitado por TAB, y el que tiene 8.188 saltos de línea
    # dentro de campos entrecomillados (8.866 filas lógicas vs 17.054 físicas).
    "lit-covid": {"delimiter": "\t", "expected_cols": 3},
    # pubmed-nlp tiene 11 columnas frente a las 12 de sus 4 hermanos (le falta la col. índice).
    "pubmed-nlp": {"delimiter": ",", "expected_cols": 11},
    "pubmed": {"delimiter": ",", "expected_cols": 12},
    "clinicaltrials": {"delimiter": ",", "expected_cols": 27},
    "amazonunderworld": {"delimiter": ",", "expected_cols": 32},
}
CSV_DEFAULT = {"delimiter": ",", "expected_cols": None}

# Separador interno de campos multivalor en los datasets de AI Index.
MULTIVALUE_SEPARATOR = "|"

# Documentos con más bloques que esto van a `.blocks.jsonl` en vez de inline (§9.3).
# F1-AIINDEX-056 es un solo DOC_ID con 111.775 filas.
INLINE_BLOCK_LIMIT = 1000

# Datasets bibliométricos: ninguna de las 50 preguntas se responde con una fila suelta.
# Su valor es filtrado/agregación estructurada, no embedding.
STRUCTURED_ONLY_PATTERNS = ("pubmed-", "clinicaltrials-", "lit-covid")

# --------------------------------------------------------------------------------------
# JSON (§8.1). Campos verificados como SIEMPRE vacíos: se omiten en vez de persistirse
# como null — el esquema no debe prometer lo que nunca existe.
# --------------------------------------------------------------------------------------
ALWAYS_EMPTY_FIELDS: dict[str, tuple[str, ...]] = {
    "ESA": ("tags",),
    "CEOBS": ("authors",),
    "SIPRI": ("images",),
    "ALERTAS": ("fields", "pdf_links", "doc_links"),
}

# 6 conjuntos de ~138 etiquetas para 186 documentos; uno solo cubre 159. Inservibles.
UNRELIABLE_FIELDS: dict[str, tuple[str, ...]] = {"ATLANTIC": ("tags",)}

# body_text es la concatenación de body_paragraphs — representaciones redundantes.
REDUNDANT_FIELDS = ("body_text",)

# CSIS: body_text va de 60 a 297.739 caracteres; los de ~60 son placeholders sin contenido.
PLACEHOLDER_MAX_CHARS = 120

# --------------------------------------------------------------------------------------
# Catalog join (§6). La tabla esperada es un TEST: cualquier desviación es un bug.
# --------------------------------------------------------------------------------------
# Advertencia 1: usar el campo de URL, no el de ruta local. Con los campos de ruta local
# la tasa de acierto cae a 0% en CSIS y RutaN.
CATALOG_URL_FIELDS = ("url_pdf", "pdf_url", "url", "enlace", "link", "href")
CATALOG_PATH_FIELDS = ("dest", "path", "filename", "archivo", "ruta")
CATALOG_TITLE_FIELDS = ("titulo", "title", "nombre", "name")
CATALOG_DATE_FIELDS = ("fecha", "date", "published", "scraped_at", "año", "anio", "year")

EXPECTED_CATALOG_RESOLUTION = {
    "RESDAL_catalog-2.json": {"refs": 95, "resolved": 95},
    "resdal_catalogo.json": {"refs": 46, "resolved": 45},
    "DAIO_catalog-2.json": {"refs": 33, "resolved": 33},
    "mapp_catalogo.json": {"refs": 31, "resolved": 31},
    "MAPPOEA_mapp-catalog.json": {"refs": 10, "resolved": 10},
    "CSIS_catalog-2.json": {"refs": 3, "resolved": 3},
    "RUTAN_catalog-2.json": {"refs": 2, "resolved": 2},
}
EXPECTED_CATALOG_TOTAL_REFS = 220
EXPECTED_CATALOG_RESOLVED = 219  # 99,5%

# --------------------------------------------------------------------------------------
# Calidad (§12)
# --------------------------------------------------------------------------------------
# Calibración por percentiles del propio corpus, por observatorio y escritura.
# Nada de constantes globales: un PDF de UNOOSA en árabe y una alerta OCRizada no
# comparten distribución de average_word_length.
QUALITY_OUTLIER_PERCENTILE = 0.05

# Umbrales absolutos de seguridad (sólo para casos patológicos inequívocos).
# Calibrados midiendo el corpus: tras la limpieza de control chars, las páginas sanas dan
# printable_ratio = 1,000 (CSET 1,000 · AI Index p05 1,000). Un 0,95 es ya anómalo.
MIN_KNOWN_WORD_RATIO_LATIN = 0.25
MIN_PRINTABLE_RATIO = 0.95
MIN_CHAR_DISTRIBUTION_SCORE = 0.35

# Muestreo para el contraste C1 (OCR de control sobre páginas nativas sanas).
C1_SAMPLE_PAGES = 300
C1_AGREEMENT_SUSPICIOUS = 0.45

# --------------------------------------------------------------------------------------
# Paralelismo (§18). Son 3 GB: el problema es de calidad, no de escala.
# --------------------------------------------------------------------------------------
DEFAULT_WORKERS = max(1, min(12, (os.cpu_count() or 4) - 2))

# --------------------------------------------------------------------------------------
# Códigos de observatorio → nombre de carpeta (para el catalog join)
# --------------------------------------------------------------------------------------
OBSERVATORY_CODES = {
    "AIINDEX": "AI_Index_Stanford",
    "ALERTAS": "Alertas_Tempranas",
    "AMAZONUW": "Amazon_Underworld",
    "ATLANTIC": "Atlantic_Council",
    "CEEEP": "CEEEP",
    "CENIA": "CENIA",
    "CEOBS": "CEOBS",
    "CSET": "CSET_Georgetown",
    "CSIS": "CSIS_Aerospace",
    "DAIO": "DAIO",
    "DEFENSA21": "Defensa21_LatAm",
    "ESA": "ESA_Space_Debris",
    "ILIA": "ILIA_Latam",
    "INPE": "INPE",
    "MAPPOEA": "MAPP_OEA",
    "RESDAL": "RESDAL",
    "RUTAN": "RutaN_GEIAL",
    "SIPRI": "SIPRI",
    "SWF": "SWF_Counterspace",
    "UNOOSA": "UNOOSA",
    "WILSON": "Wilson_Center",
}

# Fuentes verificadas como vacías o sin contenido: se registran con la causa, para poder
# distinguir "no se intentó" de "se intentó y falló".
EMPTY_SOURCES = {
    "Wilson_Center": "directory_empty__collection_never_produced_output",
    "Defensa21_LatAm": "all_5_rss_feeds_returned_status_error_with_0_entries",
}
