# Arquitectura de la ingesta

Etapa 1 del pipeline: **1.848 archivos en disco → 1.731 `CanonicalDocument` validados,
trazables y con una medida verificada de cuánto se puede confiar en cada extracción.**

Este documento describe lo que el código hace, verificado contra `src/adastra/ingestion/`
y contra los artefactos de la última corrida. Sustituye a los planes previos: donde el
plan y el código discrepan, manda el código, y la discrepancia queda anotada. La sección
[§11](#11-implementado-pero-inactivo) recoge lo que existe en el repositorio pero no está
conectado — leerla antes de dar por hecha una capacidad.

---

## Índice

1. [Frontera y objetivo](#1-frontera-y-objetivo)
2. [El corpus, en cifras verificadas](#2-el-corpus-en-cifras-verificadas)
3. [Flujo real](#3-flujo-real)
4. [Registry, clasificación y catalog join](#4-registry-clasificación-y-catalog-join)
5. [Extracción por formato](#5-extracción-por-formato)
6. [El camino del PDF](#6-el-camino-del-pdf)
7. [Normalización, escritura e idioma](#7-normalización-escritura-e-idioma)
8. [Cómo se mide la calidad](#8-cómo-se-mide-la-calidad)
9. [Modelo de datos y artefactos](#9-modelo-de-datos-y-artefactos)
10. [Invariantes](#10-invariantes)
11. [Implementado pero inactivo](#11-implementado-pero-inactivo)
12. [Resultado de la última corrida](#12-resultado-de-la-última-corrida)
13. [Operación](#13-operación)
14. [Frontera con chunking](#14-frontera-con-chunking)

---

## 1. Frontera y objetivo

El objetivo **no** es "sacar algún texto de cada archivo". Es:

> para cada DOC_ID oficial, obtener la mejor representación disponible del contenido
> original, preservando estructura y procedencia, y **detectar explícitamente cualquier
> caso donde no se pueda confiar en ella**.

Ese matiz gobierna todo el diseño. Una ingesta ingenua sobre este corpus parece exitosa y
simultáneamente pierde lo crítico: 47 alertas escaneadas sin texto nativo, un PDF que
devuelve 393.686 caracteres de basura, páginas a dos columnas intercaladas, CSV con saltos
de línea dentro de campos entrecomillados.

La ingesta **termina en `CanonicalDocument[]`**. No hace chunking, ni embeddings, ni
retrieval. El chunker no necesita saber nada de PDFs, OCR, JSON, CSV, escaneos ni
anomalías del corpus — esa separación es lo que permite iterar estrategias de chunking sin
volver a OCRizar nada.

---

## 2. El corpus, en cifras verificadas

Todas estas cifras están codificadas en [`config.py`](../src/adastra/ingestion/config.py)
como **expectativas-test**: si el corpus deja de cumplirlas, el pipeline lo reporta como
violación de invariante, no como curiosidad.

```
1.848 archivos en disco  =  1.826 del índice maestro
                          +    13 extras nominalmente enumerados
                          +     9 .DS_Store
```

Los 13 extras se enumeran uno a uno en `EXPECTED_EXTRAS` (el índice maestro, las 50
preguntas, el gold set y los 10 catálogos/registros del scraper). Un extra no listado es
un error, no una sorpresa.

| | |
|---|---|
| Fenómenos | F1 IA y capacidades estratégicas · F2 seguridad del entorno espacial · F3 dinámicas territoriales |
| Observatorios | 21, mapeados en `OBSERVATORY_CODES` |
| Formatos reales | 757 PDF · 945 JSON · 21 CSV · 4 XLSX · 8 JPEG · 1 TXT |
| Idiomas | en 1.003 · es 625 · pt 63 · zh 9 · ar 5 · ru 5 · ja 2 · ko 2 |
| Escrituras | latina 1.707 · han 9 · árabe 5 · cirílica 5 · kana 2 · hangul 2 |
| Páginas PDF | 36.822 |

Anomalías que dejaron de ser casos raros y son rutas explícitas del código:

| Anomalía | Dónde se trata |
|---|---|
| 2 `.pdf` que en realidad son HTML (descargas fallidas) | `classification/magic.py` → `invalid_source` |
| 47 Alertas escaneadas, sin texto nativo | `ocr/` + contraste C3 |
| CEOBS-Sudán: 393.686 caracteres de índices de glifo (fuente sin `ToUnicode`) | `quality/signals.py` → `char_distribution` |
| 6 informes ESA con `\f` espurios (+955 páginas fantasma) | `parsers/pdf/inspector.py`, invariante I5 |
| `lit-covid`: delimitador TAB y 8.188 saltos dentro de campos | `parsers/tabular/csv_parser.py` |
| U+2028/U+2029 en 4 CSV de PubMed | idem — `csv.reader` con `newline=""` |
| 4.561 NBSP en 13 archivos (columna `Age`) | `normalization/unicode_clean.py` |
| `mag-conferences-list.xlsx` declara 999 filas, tiene 28 | `parsers/tabular/xlsx_parser.py` |
| Un PDF con 14.623 imágenes en 5 páginas | `MAX_IMAGES_ENUMERATED_PER_PAGE = 200` |
| 20 PDFs en escrituras no latinas | `language/scripts.py`, antes que cualquier heurística léxica |

---

## 3. Flujo real

```
Indice_Datos_Codefest.xlsx ─┐
                            ├→ REGISTRY ──→ CLASSIFICATION ──→ CATALOG JOIN
filesystem scanner ─────────┘   I1 I2 I3      magic bytes        procedencia
                                              + roles (I10)           │
                                                                      ▼
                                                              FORMAT ROUTER
                                                                      │
        ┌──────────────┬───────────────┬──────────────┬───────────────┤
        ▼              ▼               ▼              ▼               ▼
      PDF            JSON          CSV/XLSX        IMAGE            TXT
        │         4 adapters      4 esquemas      OCR / manual        │
        │                                                             │
        └──────────────┴───────────────┴──────────────┴───────────────┘
                                       │
                                       ▼
                               ContentBlock[] tipados
                                       │
                     NORMALIZACIÓN → escritura → idioma
                                       │
                            ┌──────────┴──────────┐
                            ▼                     ▼
                   señales intrínsecas       CONTRASTES
                   (calibradas por          (el corpus valida
                    percentil de grupo)      al corpus)
                            └──────────┬──────────┘
                                       ▼
                            ExtractionConfidence
                                       │
                            ┌──────────┴──────────┐
                            ▼                     ▼
                       usable=True           CUARENTENA
                     documents/*.json      quarantine.jsonl
                            └──────────┬──────────┘
                                       ▼
                       manifest.jsonl + registry.jsonl + reports/
```

Orquestado por [`pipeline.py`](../src/adastra/ingestion/pipeline.py). El paralelismo es un
`ProcessPoolExecutor` sobre `_parse_one`, que devuelve dicts serializables porque cruza
frontera de proceso. La **agregación de calidad es secuencial y en dos pasadas**, y tiene
que serlo: la primera pasada recoge señales de todo el corpus para poder calibrar por
percentil en la segunda. Sin población previa no hay contra qué comparar, y cualquier
"calibración" sería una constante inventada.

---

## 4. Registry, clasificación y catalog join

### 4.1 El pipeline no empieza con `glob`

Empieza leyendo `Indice_Datos_Codefest.xlsx`, porque el `DOC_ID` (`F3-ALERTAS-001`) es el
único identificador estable del corpus y el que usa el reto. El XLSX se lee como ZIP de
XML (`index_loader.py`), no con openpyxl: una dependencia menos en la ruta crítica.

El escáner de filesystem (`scanner.py`) es **deliberadamente ciego al índice**. Sólo así la
reconciliación detecta discrepancias en ambas direcciones: archivos del índice que no están
en disco, y archivos en disco que el índice no declara.

### 4.2 Reconciliación

`reconciler.py` cierra la ecuación **sobre el disco**, no sobre el índice:

```
retrievable + metadata + evaluation + noise = 1848
```

Una reconciliación que cerrase en 1.826 dejaría 13 archivos sin invariante — y esos 13 son
precisamente los catálogos que aportan procedencia y el gold set.

### 4.3 Clasificación: rol y formato real

`magic.py` detecta el formato por **magic bytes, nunca por extensión**. Los 2 `.pdf` que son
HTML se marcan `invalid_source` y no se rescatan como contenido: son páginas de error del
servidor, no documentos equivalentes.

`roles.py` asigna cuatro roles. El que más importa es `evaluation`:

| Rol | Qué es | N |
|---|---|---|
| `retrievable` | contenido indexable | 1.812 |
| `metadata` | catálogos y registros del scraper | 25 |
| `evaluation` | **las 50 preguntas y el gold set** | 2 |
| `noise` | `.DS_Store` | 9 |

`evaluation` existe para la invariante I10: un pipeline que ingiera las preguntas como
documentos normales contamina la evaluación con las respuestas.

Los skips deliberados llevan motivo (I7 — nada desaparece en silencio):

```python
SKIP_EXTENSIONS = {".pbf": "geometry_only__attributes_available_in_csv",
                   ".avif": "profile_photo__no_informational_value"}
SKIP_FILENAMES  = {"AIINDEX_lit-covid-...xlsx":
                   "exact_duplicate_of_csv__xlsx_corrupts_ids_to_scientific_notation"}
```

### 4.4 Catalog join

El índice maestro da DOC_ID, fenómeno, observatorio y ruta — pero **no da URL de origen, ni
fecha de publicación, ni título original**. Esa información sólo existe en los catálogos
del scraper, y un reto que exige citar evidencia se queda sin referencia web sin esta etapa.

El problema: los catálogos citan nombres del servidor (`ATLAS-2024-ESP.pdf`) y el corpus fue
renombrado a `{CÓDIGO}_{slug}`. La búsqueda literal falla en el 100% de los casos.
`nombre_estandarizado()` reproduce la regla de renombrado y resuelve **219 de 220
referencias (99,5%)**.

Dos advertencias que el código encapsula y conviene no re-descubrir:

- Hay que usar el campo de **URL**, no el de ruta local. Con los campos de ruta local la
  tasa de acierto cae a 0% en CSIS y RutaN.
- Los catálogos declaran además **69 descargas fallidas**: huecos de cobertura del corpus
  que quedan registrados en `failed_downloads.jsonl` en vez de desaparecer.

> **Divergencia con el plan.** Los planes afirman que el catalog join da procedencia web a
> "los 760 PDFs". El resultado real es **174 documentos con procedencia** (`catalog_join.json
> → documents_with_provenance`), porque sólo 7 de los 21 observatorios dejaron catálogo. El
> 99,5% es la tasa de resolución de las referencias que existen, no la cobertura del corpus.

---

## 5. Extracción por formato

El router está en `pipeline._dispatch()`. Los parsers se importan de forma perezosa dentro
de cada rama para no cargar PyMuPDF en un proceso que sólo va a leer un JSON.

| Formato | Módulo | N | Notas |
|---|---|---|---|
| PDF | `parsers/pdf/` | 757 | §6 — el 97% del texto del corpus |
| JSON | `parsers/json/` | 945 | 0 errores de parseo, 100% UTF-8, 0 BOM: la ruta barata |
| CSV/TSV | `parsers/tabular/csv_parser.py` | 21 | esquemas deterministas, nunca `csv.Sniffer` |
| XLSX | `parsers/tabular/xlsx_parser.py` | 4 | nunca confiar en `max_row` |
| JPEG/PNG | `parsers/image.py` | 8 | OCR, o transcripción manual si es gráfico de datos |
| TXT | `parsers/text.py` | 1 | el único donde el boilerplate se **recorta**, no se marca |
| PBF | `parsers/pbf.py` | 73 | implementado y **desactivado** — ver §11 |

### 5.1 Los cuatro adapters de JSON

`json/parser.py` prueba los adapters en orden de especificidad, no por nombre de archivo.

| Adapter | Esquema | N | Por qué es propio |
|---|---|---|---|
| `alerts` | Alertas Tempranas | 363 | `alerta_meta` relleno al 100%: código oficial, tipo, **la única fecha ya en ISO del corpus**, municipios. Es el ground truth del contraste C3. |
| `articles` | artículo web (7 fuentes) | 485 | `body_text` es la concatenación de `body_paragraphs`: redundante, se conserva sólo la lista, ya segmentada |
| `journal` | revista CEEEP | 80 | no hay cuerpo: **el abstract ES el contenido**, y hay que declararlo o la capa de calidad lo lee como truncamiento |
| `cenia` | página institucional | 15 | la fuente declara su propia incompletitud (`contenido_limitado`); se propaga como warning |

Campos que el corpus tiene **siempre vacíos** se omiten en vez de persistirse como `null`
(`ALWAYS_EMPTY_FIELDS`): el esquema no debe prometer lo que nunca existe. Los `tags` de
Atlantic Council se descartan por inservibles — 6 conjuntos de ~138 etiquetas para 186
documentos, y uno solo cubre 159.

### 5.2 Tabulares

`csv.reader` con `newline=""`. Nunca `splitlines()`, nunca pandas como primer parser, nunca
`csv.Sniffer`. Los esquemas son explícitos en `CSV_SCHEMAS` (delimitador y número esperado
de columnas por familia) porque las cuatro trampas del §2 no se detectan por olfato.

`amazon_underworld.py` es un adapter propio para 4.369 filas × 32 columnas de las que
**sólo 999 tienen datos** (las demás son teselas de zoom bajo). Preserva dos matices
semánticos que un aplanamiento destruye: las columnas de grupo son cadenas `'SI'/'NO'` y no
booleanos, y `au_no_info = SI` significa *"sin información"*, no *"ningún grupo presente"*
— convertirlo a `grupos: []` sería inventar un dato para 324 municipios.

Los datasets bibliométricos (`pubmed-*`, `clinicaltrials-*`, `lit-covid`) reciben
`indexing_hint: "structured_only"`: ninguna de las 50 preguntas se responde recuperando una
fila suelta de PubMed. Su valor es filtrado y agregación.

### 5.3 Las tres figuras de SWF se transcriben a mano

[`data/manual_transcriptions.json`](../data/manual_transcriptions.json). El OCR de una
matriz semáforo devuelve etiquetas de fila y columna sin la relación que las une — el valor
de cada celda es una forma de color — y eso es peor que no hacer nada, porque *parece*
contenido. La transcripción de la tabla 5-1 se autovalida: las sumas de columna (6.904 y
2.773) coinciden con los totales impresos.

> `parsers/image.py` lee `data/manual_transcriptions.json` como **ruta relativa**: el
> pipeline debe ejecutarse desde la raíz del repositorio.

---

## 6. El camino del PDF

```
inspector → extracción dual → scorer de orden de lectura → limpieza
          → gate por página → OCR selectivo → segmentación → ContentBlock[]
```

### 6.1 Inspector

`pdfinfo`/PyMuPDF dan el número de páginas, si el PDF está etiquetado, si está cifrado y
qué área de cada página cubren las imágenes. El recuento de páginas viene **siempre** de
ahí y **nunca** de contar `\f` (I5).

La enumeración de imágenes se corta en `MAX_IMAGES_ENUMERATED_PER_PAGE = 200`: hay un PDF
de MAPP-OEA con 14.623 imágenes en 5 páginas y atlas de RESDAL con 800–1.400. Enumerar sin
límite cuelga el inspector, y para decidir "página-imagen" basta con el área cubierta
(`IMAGE_COVERAGE_THRESHOLD = 0.55`). El corte se registra: 254 avisos
`image_enumeration_truncated`.

### 6.2 Extracción dual y elección por página

**`pdftotext -layout` no se usa como regla fija, y la creencia habitual está invertida.**
El modo por defecto de poppler *sí* hace análisis de layout y emite orden de lectura;
`-layout` preserva posiciones **físicas**, así que en una página a dos columnas las deja
lado a lado en la misma línea de salida y al leerla linealmente se intercalan.

Verificado en `CSET_center-for-security-and-emerging-technology-2.pdf` p.5:

```
DEFAULT : "As CSET enters its seventh year, I am struck by / how far we've come..."
-layout : "As CSET enters its seventh year, I am struck by    best and most uniquely
           hard-hitting defense AI"
```

Y el efecto depende de la **página**, no del documento: en SWF-2026 y AI-Index-2025 el 15%
de las líneas largas de la salida `-layout` presentan hueco columnar, y en otras páginas
del mismo PDF, 0%. Una regla global falla en ambas direcciones.

Por eso se extrae de las dos formas y se decide por página, detectando multicolumna por
sangría bimodal con alternancia y tablas por alineación consistente de huecos. La decisión
y ambos scores quedan en `reading_order_scores`. Resultado real: **28.349 páginas en modo
orden de lectura, 8.473 en modo layout, 3.197 detectadas como tabulares.**

> El coste de ejecutar `pdftotext` dos veces es de segundos por documento. 125 PDFs emiten
> avisos de sintaxis por stderr (mayoría `Invalid Font Weight` en AI Index) con `exit
> code 0` y texto correcto: **stderr no es fallo**.

### 6.3 Gate por página y OCR selectivo

La decisión nativo/OCR es **por página**, no por documento. Eso convierte los 11 PDFs
mixtos y los 6 falsos positivos del muestreo de primeras páginas en el caso general en vez
de en excepciones.

El gate (`quality/page_gate.py`) es multi-señal. Se rechaza explícitamente
`chars/page < 50` como criterio único: ese umbral aprobaría el CEOBS-Sudán (2.187 c/pág de
basura) y suspendería páginas legítimamente cortas.

Cuando toca OCR, `ocr/image_source.py` **extrae el JPEG ya embebido en vez de rasterizar**.
Las 47 Alertas son escaneos JPEG RGB de 2547×3510 px (300 dpi para A4);
`page.get_pixmap(dpi=300)` decodificaría ese JPEG para volver a codificarlo — una
generación de pérdida gratuita, y más lento. Sólo se rasteriza si la página no es una única
imagen a página completa.

Dos motores tras la misma interfaz, elegidos por disponibilidad:

- **RapidOCR** (PaddleOCR sobre ONNX Runtime) — por defecto. Sólo pip, sin `sudo`, CPU. Sin
  GPU, Paddle nativo no aporta nada.
- **Tesseract** — si está instalado y se prefiere.

**Sin ningún motor el pipeline no falla**: marca las páginas con
`ocr_needed_but_unavailable` y las contabiliza en `pages_flagged_for_ocr_not_applied`. La
carencia queda declarada, nunca escondida.

### 6.4 Segmentación

`pdftotext` no devuelve párrafos: devuelve líneas con saltos duros. Sin este paso cada
"párrafo" sería una línea suelta de ~70 caracteres y el chunker recibiría confeti.

Tres rutas, en orden de preferencia:

| Ruta | Cuándo | Qué aporta |
|---|---|---|
| **A** PDF etiquetado | 409 documentos | `get_text("dict")` da tamaños de fuente y bounding boxes → `heading` y `table_row` con fundamento |
| **B** texto plano | resto | reglas explícitas de unión de líneas y corte de párrafo |
| **C** fallback | no se puede tipar con confianza | un bloque `page_text` por página, `segmentation_confidence` baja |

La regla que gobierna las tres: **nunca etiquetar como `paragraph` algo que no se sabe que
lo sea.** Una mentira en el tipo se propaga a todas las capas siguientes.

**La ruta A se contrasta antes de aceptarse.** En algunos PDFs, PyMuPDF devuelve bastante
menos texto que poppler (`UNOOSA_st-space-61rev03a` perdía el 48%). Es una mejora de
*tipado*, no una fuente alternativa de texto: si una página etiquetada conserva menos del
95% de los caracteres que poppler ve, se descarta y se cae a la ruta B con el aviso
`tagged_route_dropped_text` — que se emitió 143 veces.

**El boilerplate se marca, no se borra.** En las 47 Alertas OCRizadas el encabezado
repetido contiene el código de alerta, que es el dato que hace posible el contraste C3. Se
emite `is_boilerplate: true` y decide el chunker.

---

## 7. Normalización, escritura e idioma

**Normalización mínima** (`unicode_clean.py`). Sólo se corrige lo inequívocamente corrupto
en transporte: NUL, controles, NBSP, separadores U+2028/U+2029. Nada de paráfrasis,
traducción, resumen, corrección gramatical ni reescritura con LLM — invariante I9. El reto
exige citar evidencia, y un texto reescrito ya no es evidencia.

**La escritura se detecta antes que el idioma** (`language/scripts.py` → `detector.py`).
Es el orden correcto y no el intuitivo: hay 20 PDFs predominantemente en árabe, ruso,
coreano, japonés y chino, y un detector léxico que busque `the`/`of`/`and` los marcaría
como corruptos. Un analizador de calidad que actuara sobre esa señal mandaría a cuarentena
documentos perfectamente extraídos.

Para las escrituras latinas basta distinguir es/en/pt por frecuencia de palabras
funcionales. **No se usa fastText**: el modelo pesa 126 MB, hay que descargarlo, y el
problema es de tres clases con vocabularios muy separados. Determinista y sin dependencias
gana.

**Metadatos** (`normalization/metadata.py`): el corpus tiene cinco formatos de fecha
incompatibles. Cada fecha normalizada lleva `date_confidence` (`exact` / `inferred` /
`ambiguous` / `absent`). La fecha propia del documento manda sobre la del catálogo — sin
esa promoción, `source.published_date` quedaría vacía en 363 alertas y ~500 artículos, y el
filtrado temporal sería inservible.

---

## 8. Cómo se mide la calidad

`quality_score: 0.94` no es accionable. Cada documento lleva un `ExtractionConfidence` con
procedencia:

```json
{
  "score": 0.87,
  "basis": "entity_crosscheck",
  "signals": {
    "known_word_ratio": {"value": 0.94, "pctile_in_source": 0.61, "flag": null}
  },
  "crosschecks": [
    {"type": "entity_crosscheck", "passed": true, "score": 0.92,
     "detail": {"alert_code": "001-17", "municipalities_found": "3/3"}}
  ],
  "flags": []
}
```

### 8.1 Señales intrínsecas

`quality/signals.py`: `printable_ratio`, `alphabetic_ratio`, `char_distribution`,
`known_word_ratio`, `average_word_length`, `single_char_token_ratio`, `repetition_ratio`.

Ninguna decisión se toma con una sola señal. La que resuelve el caso CEOBS-Sudán es
**`char_distribution`**, que detecta corrupción de forma **independiente del idioma**:
`known_word_ratio` sólo funciona en escrituras latinas, así que un CEOBS-Sudán en chino se
le escaparía.

`known_word_ratio` se interpreta por familia de escritura, no con un umbral global: en
latinas un 0,30 es excelente (las palabras funcionales son ~30% del texto); en CJK y árabe
mide proporción de caracteres en rango y lo esperable es ~0,95.

### 8.2 Calibración por percentil de grupo

Los umbrales se calibran **por percentil dentro de cada grupo (observatorio × escritura)**,
no con constantes. Un PDF de UNOOSA en árabe y una alerta OCRizada no comparten
distribución de `average_word_length`; lo que importa es si un documento es atípico
*respecto a sus pares*.

`SignalCalibrator` exige **≥8 documentos** en el grupo antes de calibrar: con menos, mejor
no calibrar que calibrar mal. La última corrida formó **32 grupos**.

### 8.3 Los contrastes: el corpus valida al corpus

Las señales dicen si un texto *parece* sano. Los contrastes dicen si *es* el texto
correcto. Los contrastes mandan sobre las señales.

| # | Contraste | Estado | Qué demuestra |
|---|---|---|---|
| C1 | OCR de control sobre páginas nativas sanas | **implementado, no conectado** | corrupción independiente del idioma |
| C2 | título del índice/catálogo ↔ documento | **activo** — 834 documentos | que el texto extraído es del documento correcto |
| C3 | `alerta_meta` ↔ texto del PDF escaneado | **activo** — 62 documentos | ground truth real sobre entidades |
| C4 | `lit-covid` CSV ↔ su XLSX gemelo | **implementado, no conectado** | el parser tabular contra sí mismo |
| C5 | 9 catálogos JSON ↔ sus CSV espejo | **implementado, no conectado** | el parser CSV en 9 esquemas reales |
| C6 | 15 pares del gold set | **activo** — 11 documentos | fidelidad extremo-a-extremo |

**C3 es el más fuerte y merece énfasis.** Los PDFs de Alertas se llaman
`ALERTAS_informesNNN.pdf` y los JSON `ALERTAS_{codigo}-{detail_id}.json`: **no hay pareo
por nombre**, y los PDFs no tienen texto nativo. El código sólo aparece dentro del escaneo
→ emparejar sólo es posible después del OCR → **el emparejamiento ES la métrica de calidad
del OCR**. El emparejador se autovalida exigiendo que además aparezca un municipio de la
alerta candidata: emitir un `matched_alert_code` incorrecto sería peor que no emitir
ninguno.

Tres reglas de exclusión que evitan contrastes que no pueden pasar — *un contraste que
siempre falla no es un contraste, es ruido*:

- **C2 no se aplica a tabulares.** Un dataset no lleva su título dentro del contenido;
  contrastarlo es un error de categoría que castigaría a CSV y XLSX bien parseados.
- **C2 no usa el nombre de archivo si no parece un título.** En las Alertas es un código
  (`ALERTAS_001-17-91689`) y en otras fuentes un hash. Contrastarlo hundía la confianza de
  363 documentos perfectamente extraídos.
- **C2 descarta títulos genéricos**, detectados por la propiedad que los define: un título
  repetido en ≥3 documentos no identifica a ninguno. Así se neutraliza sin codificarlo el
  caso de los 47 archivos de CSET a los que el scraper puso el título de la página.
- **C3 no se aplica al JSON del que salen los metadatos.** Sería circular —los metadatos
  *son* la fuente— y además falla legítimamente, porque el código vive en `alerta_meta` y
  no en `body_paragraphs`. Aplicarlo mandaba a cuarentena 181 alertas correctas.

**C6 se usa sólo como assert**: no entra al corpus, no se indexa, no ajusta parámetros.

### 8.4 Agregación y gate

`build_confidence()` mezcla la puntuación intrínseca con la de los contrastes, dando más
peso a estos cuanto más fuertes son (`alpha = min(0.7, Σ pesos)`; pesos: entidad y gold
0,55 · espejo 0,50 · OCR 0,45 · título 0,30). El `basis` publicado es el contraste más
fuerte disponible, y cuando nada pudo comprobarse se declara **`unverified`** — no se
esconde.

El gate final (`_is_usable`) manda a cuarentena si el texto está vacío sin declararlo, si
`basis == "unverified"`, o si `score < 0.35`. **Cuarentena significa "no confío en esta
extracción", no exclusión permanente**: cada entrada lleva motivo y acción recomendada.

---

## 9. Modelo de datos y artefactos

El modelo vive en [`src/adastra/core/models/`](../src/adastra/core/models/), **fuera de
`ingestion/`**: es el contrato que la ingesta entrega a las otras tres etapas, no una
estructura interna suya.

```
CanonicalDocument
├── doc_id, pipeline_version
├── source: SourceMetadata      fenómeno · observatorio · ruta · formato
│                               url · fecha (+confianza) · título · catálogo   ← catalog join
│                               script{} · dominant_script · language (+conf)
├── blocks: ContentBlock[] | None        inline si ≤ 1.000
├── blocks_ref: str | None               "{DOC_ID}.blocks.jsonl" si son más
├── block_count
├── metadata{}, metadata_warnings[]
├── quality: DocumentQuality
│   ├── confidence: ExtractionConfidence   score · basis · signals · crosschecks · flags
│   ├── usable: bool
│   └── pages_total/native/ocr/quarantined · characters · warnings
├── indexing_hint: "full" | "structured_only"
└── related_doc_ids[], potential_overlap_group

ContentBlock
├── block_id, type, text, order
├── page, row, bbox
├── structured_data{}            preserva tipos y nombres de campo originales
├── extraction_method            native_reading_order | native_layout | native_tagged
│                                | ocr | structured | manual
├── is_boilerplate               marcado, nunca borrado
└── segmentation_confidence      fiabilidad del TIPO, no del texto
```

`structured_data` y `text` no son alternativas: son complementarios. El primero preserva la
semántica original, el segundo queda disponible para embedding.

### Salida

```
artifacts/
├── ingestion/
│   ├── registry.jsonl                 1.848 entradas, una por archivo del disco
│   ├── manifest.jsonl                 1.848 líneas — traza por archivo (I7)
│   ├── documents/
│   │   ├── {DOC_ID}.json              documento canónico
│   │   └── {DOC_ID}.blocks.jsonl      bloques, si son >1.000  (141 documentos)
│   ├── quarantine/quarantine.jsonl    "no confío en esto" + motivo + acción
│   └── reports/
│       ├── summary.json               resumen operativo completo
│       ├── quality_coverage.json      matriz de cobertura de verificación
│       ├── reconciliation.json        invariante I2
│       ├── catalog_join.json          220 refs / 219 resueltas / 174 con procedencia
│       ├── unresolved_catalog_refs.jsonl
│       ├── failed_downloads.jsonl     huecos declarados por los propios catálogos
│       ├── warnings.jsonl
│       └── failures.jsonl
└── evaluation/                        ← FUERA de ingestion/ (I10)
    ├── gold_set.json
    └── gold_resolution.json
```

**Regla de tamaño.** Los bloques van inline salvo que superen `INLINE_BLOCK_LIMIT = 1000`.
`F1-AIINDEX-056` es un solo DOC_ID con **111.775 bloques**: inline serían ~200 MB de JSON
que habría que cargar entero para leer un bloque, invirtiendo la ventaja que justifica un
archivo por documento. Consecuencia para quien consuma esto: ver [§14](#14-frontera-con-chunking).

---

## 10. Invariantes

Todas se comprueban automáticamente (`quality/validators.py`) y se reportan en
`summary.json → invariant_problems`. Con `--strict` lanzan excepción en vez de avisar.
El código de salida del pipeline es `1` si alguna falla.

| # | Invariante |
|---|---|
| I1 | todo archivo del disco tiene rol y aparece en el reporte |
| I2 | `retrievable + metadata + evaluation + noise = 1848` |
| I3 | ningún `DOC_ID` del índice queda sin estado terminal |
| I4 | ningún texto persistido contiene `\x00` |
| I5 | `page_count` viene de PyMuPDF/pdfinfo, **jamás** de contar `\f` |
| I6 | todo documento recuperable lleva confianza **con procedencia** |
| I7 | ningún archivo se descarta en silencio |
| I8 | `block_id` único y orden monótono |
| I9 | ningún texto ha sido reescrito por un LLM |
| I10 | preguntas y gold set nunca entran al corpus recuperable |
| I11 | toda decisión automática cara queda registrada con su motivo |

---

## 11. Implementado pero inactivo

Tres capacidades existen en el repositorio y **no están conectadas**. No son bugs: son
decisiones o trabajo pendiente. Se listan aquí para que nadie las dé por hechas.

| Qué | Dónde | Estado y consecuencia |
|---|---|---|
| **Contrastes C1, C4 y C5** | `quality/crosschecks.py` → `check_ocr_agreement()`, `check_mirror()` | Las funciones están escritas y tienen peso asignado en `_CROSSCHECK_WEIGHT`, pero `pipeline._build_document()` **nunca las llama**. `by_basis` de la última corrida no contiene `ocr_agreement` ni `mirror_match`: los 834 "contrastes débiles" son **todos** C2/título. La etiqueta de `report.py coverage` («C1 OCR / C2 título / C4-C5 espejo») induce a error. |
| **Cache incremental** | `persistence/cache.py` | Instanciado con `enabled=False` en `pipeline.py:157` y nunca consultado en el bucle. La clave por etapa está diseñada para que un cambio de umbral re-evalúe en vez de re-OCRizar; hoy `--rescore` cubre ese caso releyendo los documentos de disco. Cada corrida completa vuelve a OCRizar. |
| **Parser PBF** | `parsers/pbf.py` (`enabled = False`) | Desactivado a propósito: el CSV de Amazon Underworld ya contiene todos los atributos y los PBF sólo aportan geometría. Se deja implementado para que activarlo sea un flag y no un proyecto. Las 73 teselas se registran como `intentional_skip` con motivo. |

Además, **1.751 páginas quedaron marcadas `ocr_needed_but_unavailable`** frente a 1.134 con
OCR aplicado. Es la mayor brecha de cobertura abierta de la etapa.

---

## 12. Resultado de la última corrida

```
1.848 archivos  =  1.826 índice + 13 extras + 9 ruido           ✓ I2
1.826 del índice → 1.731 success · 88 intentional_skip
                   ·  5 quarantined ·  2 invalid_source          ✓ I3
invariantes                                            11 / 11   ✓
gold set C6                          15 / 15 fragmentos hallados ✓
fidelidad de extracción vs poppler                      102,48%
```

**Confianza** (n = 1.736): mín 0,0 · p25 0,922 · mediana 0,968 · p75 0,990 · media 0,940.

**Cobertura de verificación** — la cifra más honesta del pipeline:

| | N | % |
|---|---|---|
| contraste fuerte (C3 entidades / C6 gold) | 73 | 4,2% |
| contraste débil (C2 título) | 834 | 48,0% |
| sólo señales intrínsecas | 823 | 47,4% |
| **sin verificar** | 6 | 0,3% |

**Warnings principales:** `image_enumeration_truncated` 254 · `tagged_route_dropped_text`
143 · `abstract_only__full_text_not_in_corpus` 80 · `short_document__summary_not_full_report`
17 · `nul_bytes_cleaned` 8 · `ocr_needed_but_unavailable` 5.

**Fidelidad por debajo del 95%** — 6 de 757 PDFs, cinco de ellos RTL/árabe:
`UNOOSA_st-space-088a` 90,2% · `UNOOSA_st-space-61rev03a` 91,2% ·
`SWF_2025-executive-summary-arabic` 93,0% · `SWF_gcsr-2026-execsum-ara` 93,0% ·
`SIPRI_21.11.2025-pb-arabic` 93,3% · `CENIA_balance-cenia-2023-firmado-1` 94,7%.

Reproducible con `make ingest && make check`.

---

## 13. Operación

```bash
make setup                     # venv 3.11 + dependencias (pyproject.toml)
make ocr                       # RapidOCR, sin sudo
make check-env                 # poppler, venv, corpus, motor OCR

make ingest                    # completa, con OCR      (~60-75 min)
make ingest-fast               # sin OCR                (~5 min)
make ingest-sample N=120       # muestra
make resume                    # en segundo plano, sobrevive al cierre de sesión
make retry                     # sólo los DOC_ID con contraste fallido
make rescore                   # recalcula CALIDAD sin re-extraer   (minutos)

make check                     # verify + gold + audit
```

Requisito de sistema: `sudo apt install poppler-utils`. El corpus se ubica en la raíz o se
apunta con `CODEFEST_CORPUS`.

**`rescore` frente a `retry`.** Cuando cambia la lógica de un contraste hay que usar
`rescore`, no `retry`: un contraste espurio que *pasaba* también aportó peso al score, así
que reprocesar sólo los fallidos deja al resto con una confianza calculada sobre evidencia
ya inválida. `rescore` relee los documentos persistidos, descarta los campos derivados por
la capa de calidad y recalcula — minutos en vez de una hora.

CLI directo: `python -m adastra.ingestion.pipeline --corpus … --output artifacts`, con
`--limit N`, `--no-ocr`, `--strict`, `--workers N`, `--rescore`, `--only ID,ID` (o
`--only @fichero`). Salida `0` si todas las invariantes se cumplen, `1` si alguna falla.

Utilidades de revisión en [`scripts/ingestion/`](../scripts/ingestion/): `report.py`
(summary/coverage/quarantine/warnings/doc/find), `check_gold.py` (C6),
`audit_extraction.py` (fidelidad vs poppler), `failed_docs.py` (entrada de `make retry`).

---

## 14. Frontera con chunking

La etapa siguiente entra por el lector compartido, **nunca leyendo los JSON a mano**:

```python
from adastra.core.documents import iter_documents, iter_blocks

for doc in iter_documents():
    if doc.indexing_hint == "structured_only":
        continue                          # bibliometría: se filtra y agrega, no se embebe
    for block in iter_blocks(doc):        # resuelve blocks_ref transparentemente
        ...
```

**Por qué importa.** `doc.blocks` es `None` en los 141 documentos con más de 1.000 bloques;
sus bloques viven en `{DOC_ID}.blocks.jsonl`. Quien lea `doc.blocks` directamente
funcionará con el 99% del corpus y perderá en silencio los 111.775 bloques de
`F1-AIINDEX-056` — sin excepción y sin aviso. `iter_blocks()` cubre ambos casos y es un
generador, porque el caso grande no debería caber en memoria.

Lo que la ingesta ya dejó resuelto y no hay que rehacer:

- `block.type` distingue heading / paragraph / list_item / table_row / table_text / caption,
  y `page_text` es el fallback honesto. Mirar `segmentation_confidence` antes de fiarse.
- `block.is_boilerplate` marca los encabezados repetidos; **descartarlos o no es decisión
  del chunker**, no de la ingesta.
- `doc.quality.confidence` trae score, base y señales: un documento en cuarentena o de
  confianza baja no debería pesar igual en el índice.
- `doc.source` trae idioma, escritura, URL, fecha y título original — los metadatos de cita
  que cada chunk debe arrastrar para que retrieval pueda citar.
- `doc.indexing_hint == "structured_only"` marca los datasets bibliométricos.

Y lo que **no** está resuelto y hereda quien siga: las 1.751 páginas sin OCR aplicar, el
47,4% del corpus verificado sólo con señales intrínsecas, y los tres contrastes del §11 sin
conectar.
