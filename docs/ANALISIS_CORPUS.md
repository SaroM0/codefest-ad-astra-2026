# Análisis del CORPUS CODEFEST AD ASTRA 2026

> **Destinatario:** ingeniería de datos, para construir el pipeline de extracción.
> **Método:** inspección exhaustiva de los 1.848 archivos. Se extrajo el texto **completo** de los
> 760 PDFs página por página (37.780 saltos de página procesados), se parsearon los 964 JSON, se
> validaron los 26 CSV con parser real, se decodificaron los 73 vector tiles a nivel de protobuf y
> se verificaron los _magic bytes_ de todos los archivos.
> **Ninguna cifra de este documento es una estimación.** Los comandos de verificación están en el
> apéndice.

---

## 1. Resumen ejecutivo

Repositorio documental para un reto de RAG / question-answering: 50 preguntas en español sobre
defensa, seguridad espacial y dinámicas territoriales, a responder citando evidencia de ~1.800
documentos de 20 observatorios internacionales.

| Métrica                                  | Valor verificado                                                        |
| ---------------------------------------- | ----------------------------------------------------------------------- |
| Tamaño total                             | 3,0 GB                                                                  |
| Archivos en disco                        | **1.848** (1.839 útiles + 9 `.DS_Store`)                                |
| Enlaces simbólicos / archivos de 0 bytes | **0 / 0**                                                               |
| PDFs                                     | **760** (758 PDF reales + **2 HTML disfrazados**)                       |
| Páginas PDF                              | **36.825** (según `pdfinfo`, autoritativo)                              |
| JSON                                     | 964 · CSV 26 · XLSX 6 · PBF 73 · JPG 8 · AVIF 1 · TXT 1                 |
| **Texto extraíble total**                | **≈141,4 M caracteres** (137,0 M de PDF + 4,4 M de JSON) ≈ 35 M tokens  |
| Idiomas                                  | **8**: español, inglés, portugués, chino, árabe, ruso, coreano, japonés |

### Extraibilidad real de los PDFs — la cifra que importa

Medido extrayendo el documento **entero**, no una muestra:

| Categoría                                                   | N       | %          |
| ----------------------------------------------------------- | ------- | ---------- |
| **Texto limpio directo** (≥400 c/pág, <10 % páginas-imagen) | **693** | 91,2 %     |
| Mixto: texto correcto + páginas-imagen intercaladas (>10 %) | 11      | 1,4 %      |
| Baja densidad (50–400 c/pág): diapositivas, tablas          | 3       | 0,4 %      |
| **Subtotal extraíble sin OCR**                              | **707** | **93,0 %** |
| **Requiere OCR** (0 texto o <50 c/pág)                      | **51**  | 6,7 %      |
| No son PDF (HTML con extensión `.pdf`)                      | 2       | 0,3 %      |

### Los 7 hallazgos que condicionan el pipeline

1. **51 PDFs requieren OCR** — 47 de ellos son Alertas Tempranas (escaneos JPEG 300 dpi,
   2547×3510 px). Es la fuente más ligada a las preguntas sobre Colombia (q033–q050).
2. **`CEOBS_minamata-convention-initial-assessment-for-sudan.pdf` produce 393.686 caracteres de
   basura.** 176 de sus 180 páginas devuelven índices de glifo en vez de Unicode (fuente sin tabla
   `ToUnicode`). Un pipeline ingenuo indexará ese ruido como si fuera texto válido.
3. **Los 6 informes ESA Space Environment vienen contaminados con bytes NUL** (hasta 38.337 por
   archivo) y con _form feeds_ espurios. El texto es correcto tras limpiarlos, pero contar páginas
   partiendo por `\f` da resultados inflados en +199 páginas.
4. **El corpus tiene 8 idiomas**, no 3. Hay documentos íntegros en árabe, ruso, coreano, japonés y
   chino (SWF, UNOOSA, SIPRI, CSIS, AI Index).
5. **Los `.pbf` son protobuf CRUDO, sin comprimir.** `gzip.decompress()` fallará; hay que pasarlos
   directo a `mapbox_vector_tile.decode()`.
6. **Los catálogos citan nombres de archivo que no existen en disco**: el corpus fue renombrado a
   una convención estándar. Hay una regla de normalización que resuelve el 99,5 % (§8).
7. **Los `tags` de Atlantic Council son inservibles**: 186 documentos comparten 6 conjuntos de
   ~138 etiquetas; uno solo cubre 159 de los 186.

### Los tres frentes

| Código | Fenómeno                       | Observatorios | Datos | PDFs | JSONs |
| ------ | ------------------------------ | ------------- | ----- | ---- | ----- |
| **F1** | IA y Capacidades Estratégicas  | 8             | 459   | 231  | 205   |
| **F2** | Seguridad del Entorno Espacial | 5             | 479   | 237  | 230   |
| **F3** | Dinámicas Territoriales        | 8             | 888   | 291  | 519   |

---

## 2. Integridad del corpus: qué se verificó y qué salió

Comprobaciones ejecutadas sobre el 100 % de los archivos, no sobre muestras:

| Verificación                                | Resultado                                          |
| ------------------------------------------- | -------------------------------------------------- |
| _Magic bytes_ vs extensión (1.839 archivos) | **2 desajustes** — ambos HTML con extensión `.pdf` |
| Parseo JSON (964 archivos)                  | **0 errores**, 0 con BOM, **100 % UTF-8 válido**   |
| URLs duplicadas entre documentos JSON       | **0**                                              |
| PDFs con MD5 idéntico                       | **0** en todo el corpus                            |
| Filas irregulares en CSV (parser real)      | **0** en los 26 archivos                           |
| Archivos de 0 bytes                         | **0**                                              |
| Enlaces simbólicos                          | **0**                                              |
| Vector tiles ilegibles                      | **0** de 73                                        |
| Índice maestro vs disco                     | **0 archivos faltantes**                           |

**Conclusión:** el corpus no tiene corrupción estructural. Los problemas son de _contenido_
(escaneos, codificación de fuentes, campos vacíos), no de integridad de archivos.

### Los 2 archivos que no son PDF

| Archivo                                                   | Tamaño   | Qué es realmente                                                                         |
| --------------------------------------------------------- | -------- | ---------------------------------------------------------------------------------------- |
| `SIPRI/sipri_data/pdfs/SIPRI_22136.pdf`                   | 23.067 B | HTML: página de la Fundación FES (_"Publikationen der Stiftung / Die Zukunft der NATO"_) |
| `SIPRI/sipri_data/pdfs/SIPRI_hsrc20lmip20report...-1.pdf` | 23.785 B | HTML: página Drupal con namespaces RDF                                                   |

Son descargas fallidas donde el servidor devolvió una página en vez del documento. `pdfinfo` emite
`May not be a PDF file` y `Illegal character <21> in hex string`. **Filtrar por magic bytes `%PDF`
antes de procesar.**

---

## 3. Archivos raíz: los artefactos del reto

Tres archivos fuera de la jerarquía de fenómenos. **No son corpus, son las reglas del juego.**

### 3.1 `Extracto_Preguntas_50_v2.pdf` (37 KB, 3 páginas, 7.226 caracteres)

Las 50 preguntas, `q001`–`q050`, en español, con capa de texto limpia. Reparto estricto y contiguo:

| Preguntas     | Fenómeno | Tema                                                                           |
| ------------- | -------- | ------------------------------------------------------------------------------ |
| `q001`–`q016` | F1       | IA militar, NBQR, drones, talento, semiconductores, DIH, ciberseguridad        |
| `q017`–`q032` | F2       | Derecho espacial, ASAT, guerra electrónica, spoofing, RPO, láseres             |
| `q033`–`q050` | F3       | Control territorial, GAO/GAOR/GDO, minería ilegal, narcotráfico, reclutamiento |

Varias preguntas de F3 nombran departamentos colombianos concretos (Chocó, Antioquia, Bolívar,
Norte de Santander, Arauca, Córdoba, Cauca).

### 3.2 `Indice_Datos_Codefest.xlsx` (156 KB) — índice maestro

| Hoja                     | Filas     | Contenido                                        |
| ------------------------ | --------- | ------------------------------------------------ |
| `Indice`                 | 23        | Matriz observatorio × tipo con conteos           |
| `Resumen por Fenomeno`   | 5         | Agregados F1/F2/F3                               |
| `Inventario de Archivos` | **1.827** | **Un registro por archivo — el activo más útil** |

Esquema del inventario: `Fenómeno | Observatorio | Código Observatorio | DOC_ID | Nombre estandarizado | Carpeta | Tipo`.

El **`DOC_ID`** (`F{n}-{CÓDIGO}-{NNN}`, p. ej. `F1-AIINDEX-001`, `F3-SIPRI-128`) es **el único
identificador estable del corpus**. Reconciliación verificada:

```
Índice: 1.826 registros    Disco: 1.839 archivos útiles    Faltantes: 0
Extra en disco (13): 10 JSON de catálogo/registro + 2 XLSX + 1 PDF de preguntas
```

Distribución del inventario por tipo: PDF 759, JSON 954, Otro 74, CSV 26, Imagen 8, Excel 4, Texto 1.

**Salvedad:** la columna `PBF (Mapas)` cuenta 74 = 73 `.pbf` + 1 `.avif`. En la hoja de inventario
ese tipo aparece correctamente como `Otro`; solo el encabezado de la matriz resumen induce a error.

### 3.3 `F3_Dinamicas_Territoriales/FASE ORDENADA CODEFEST.xlsx` (19 KB) — set de referencia parcial

Respuestas de referencia (_gold standard_) con estructura `PREGUNTA | FRAGMENTO | DOCUMENTO`.

| Hoja | Filas de datos | **Con fragmento no vacío** | Preguntas                                       | Fuentes citadas   |
| ---- | -------------- | -------------------------- | ----------------------------------------------- | ----------------- |
| `F1` | 5              | **5**                      | 3 (numeradas `2`, `3`, `4`)                     | DAIO, SIPRI, ILIA |
| `F3` | 20             | **10**                     | 6 (`q0047`–`q0052`, pero `q0051` sin fragmento) | MAPP-OEA          |

**Total real: 15 pares pregunta→fragmento utilizables, cubriendo 8 preguntas con evidencia.**
La hoja `F1` tiene además una columna A sin encabezado que contiene el número de pregunta; la hoja
`F3` la etiqueta como `# 1`. Las 10 filas restantes de `F3` están completamente vacías.

Tres inconsistencias a conocer antes de usarlo:

1. **Dos numeraciones incompatibles.** Hoja F1 usa enteros (`2`,`3`,`4`); hoja F3 usa `q0047`–`q0052`
   a cuatro dígitos. Ninguna coincide con `q001`–`q050`; `q0051` y `q0052` no existen en el set de 50.
   Proceden de un banco de preguntas mayor.
2. **Referencia por nombre original, no estandarizado.** Cita
   `daio_study2529_guarding_the_alliances_...pdf`; el corpus almacena
   `DAIO_study2529-guarding-the-alliances-...pdf`. Aplicar la regla de §8.
3. **Revela un chunking previo:** IDs `DOC-NNNN-chunk-NNNN` (p. ej. `DOC-0296-chunk-0052`).
   **Ese mapeo no está en el corpus.** La trazabilidad exacta con el _gold set_ no es reproducible;
   hay que emparejar por el texto del fragmento.

Verificado: **todas** las referencias del set resuelven a archivos reales tras normalizar nombres.

---

## 4. Anatomía estructural

### 4.1 Las cuatro plantillas

```
Observatorio/
├── articulos/ | noticias/ | paginas/ | alertas/     ← A. JSON de texto web (1 archivo = 1 doc)
│     └── {CÓDIGO}_{slug}.json
├── pdfs/ | pdfs_full/                               ← B. PDFs originales
│     └── {Categoría|Año}/{CÓDIGO}_{slug}.pdf
├── {fuente}_data/ | {fuente}_pdfs/                  ← C. Catálogo del scraper
│     ├── {CÓDIGO}_catalog-2.json                       (JSON y CSV con el MISMO contenido)
│     └── {CÓDIGO}_catalog-2.csv
└── {fuente}_catalogo.json + {fuente}_registro.json  ← D. Metadatos de pipeline (solo F3)
```

Convención de nombre: **`{CÓDIGO_OBSERVATORIO}_{slug-minúsculas-con-guiones}`**.

### 4.2 Cobertura real por observatorio

| Observatorio      | PDFs  | JSONs | ¿Catálogo propio?           |
| ----------------- | ----- | ----- | --------------------------- |
| CSET_Georgetown   | 127   | 0     | no                          |
| CSIS_Aerospace    | 110   | 103   | **sí**                      |
| RESDAL            | 105   | 3     | **sí**                      |
| SIPRI             | 74    | 55    | **sí**                      |
| SWF_Counterspace  | 68    | 56    | no                          |
| Alertas_Tempranas | 62    | 363   | no                          |
| AI_Index_Stanford | 44    | 0     | no                          |
| MAPP_OEA          | 33    | 3     | **sí**                      |
| DAIO              | 33    | 1     | **sí**                      |
| UNOOSA            | 31    | 0     | no                          |
| ESA_Space_Debris  | 24    | 16    | no                          |
| CEOBS             | 17    | 22    | **sí**                      |
| CENIA             | 12    | 15    | no                          |
| ILIA_Latam        | 10    | 0     | no                          |
| RutaN_GEIAL       | 5     | 1     | **sí**                      |
| INPE              | 4     | 55    | no                          |
| Atlantic_Council  | 0     | 186   | no                          |
| CEEEP             | 0     | 82    | **sí**                      |
| Amazon_Underworld | 0     | 1     | no                          |
| Defensa21_LatAm   | 0     | 2     | **sí** (documenta el fallo) |
| **Wilson_Center** | **0** | **0** | **—**                       |

**Solo 8 de 21 observatorios tienen catálogo propio.** Para los otros 13, el `Inventario de Archivos`
del índice maestro es la única referencia cruzada disponible.

### 4.3 ¿Hay fuentes realmente vacías? Sí, dos — pero de forma distinta

**`Wilson_Center`** — Directorio existente y **completamente vacío**: `find` devuelve 0 entradas.
El índice maestro lo declara con 0 en las 8 columnas de tipo. La recolección nunca produjo nada.

**`Defensa21_LatAm`** — Tiene 2 archivos JSON pero **cero documentos**:

- `DEFENSA21_articulos-2.json` → lista vacía `[]` (2 bytes)
- `DEFENSA21_catalog-2.json` → documenta la causa: **los 5 feeds RSS devolvieron
  `status: "error"`, `entries: 0`** (feeds _General_, _Publicaciones_, _Seguridad y Defensa_,
  _Ciberseguridad_, _Tecnología Militar_ de `defensa21latam.com`).

Este segundo caso es más útil que el primero: el catálogo **explica** el fallo, lo que permite
distinguir "no se intentó" de "se intentó y falló".

### 4.4 Los dos pipelines paralelos — y por qué no producen duplicados

Varias fuentes fueron recolectadas dos veces por procesos distintos. **Verificado por MD5: no hay
ni un solo par de archivos idénticos entre pipelines.**

| Fuente   | Pipeline 1                     | Pipeline 2                                | Duplicados MD5 |
| -------- | ------------------------------ | ----------------------------------------- | -------------- |
| CSIS     | `pdfs_full/` (110 PDFs)        | `csis_pdfs/` (**0 PDFs**, solo catálogo)  | 0              |
| MAPP-OEA | `pdfs/{2008..2026}/` (31 PDFs) | `oea/mapp_oea_informes/eng/` (2 PDFs)     | 0              |
| RESDAL   | `pdfs/` (46 PDFs)              | `resdal_atlas/{2014,2016}_eng/` (59 PDFs) | 0              |
| SIPRI    | `pdfs_full/` (59 PDFs)         | `sipri_data/pdfs/` (15 PDFs)              | 0              |
| CEOBS    | `pdfs_full/` (16 PDFs)         | `ceobs_data/pdfs/` (1 PDF)                | 0              |

**Trampa documentada:** `csis_pdfs/CSIS_catalog-2.json` declara 3 descargas correctas con destino
`csis_pdfs/SpaceThreat_{2023,2024,2025}.pdf`, pero ese directorio **solo contiene el catálogo**.
Los 3 documentos sí existen, en `pdfs_full/Space_Threat_Assessment/`, bajo el nombre del servidor
(`CSIS_250425-swope-space-threat.pdf`). Lo mismo ocurre con MAPP-OEA: su catálogo reporta 68 fallos
sobre 78 intentos (63× HTTP 404, 5× HTTP 503), pero el pipeline 1 obtuvo 31 informes por otra ruta.

**Leer un solo catálogo da una imagen falsa de la cobertura.**

### 4.5 Los archivos `*_registro.json` (solo F3)

Metadatos de pipeline con tres diccionarios: `urls` (url→ruta), `hashes` (md5→ruta) y `articulos`
(url→ruta de JSON). Son el mapeo url↔archivo que falta en el resto de fuentes.

| Archivo                    | urls  | hashes | articulos |
| -------------------------- | ----- | ------ | --------- |
| `sipri_full_registro.json` | 57    | 57     | 50        |
| `resdal_registro.json`     | 46    | 46     | —         |
| `mapp_registro.json`       | 31    | 31     | —         |
| `ceobs_full_registro.json` | 16    | 16     | 20        |
| `ceeep_registro.json`      | **0** | **0**  | 80        |

`ceeep_registro.json` tiene `urls` y `hashes` vacíos: CEEEP no descargó PDFs, solo metadatos de
artículos de revista.

---

## 5. PDFs: análisis de extracción

**760 archivos · 36.825 páginas · 137,0 M caracteres útiles**

### 5.1 Distribución

```
Páginas:  mín 1 · mediana 19 · media 49 · máx 1.330
          1 pág: 13   2–5: 91   6–20: 287   21–50: 184
          51–100: 92  101–300: 75  >300: 16
```

### 5.2 Extraibilidad y densidad por observatorio

| Observatorio          | PDFs   | Páginas | Págs. solo imagen | Caracteres  | c/pág     | **Requiere OCR** |
| --------------------- | ------ | ------- | ----------------- | ----------- | --------- | ---------------- |
| CSIS_Aerospace        | 110    | 7.810   | 94                | 29.458.730  | 3.772     | 3                |
| RESDAL                | 105    | 3.366   | 27                | 23.380.895  | 6.946     | 0                |
| SWF_Counterspace      | 68     | 4.075   | 48                | 17.925.278  | 4.399     | 0                |
| AI_Index_Stanford     | 44     | 4.289   | 2                 | 15.023.169  | 3.503     | 0                |
| CSET_Georgetown       | 127    | 3.145   | 7                 | 8.740.481   | 2.779     | 1                |
| ILIA_Latam            | 10     | 1.745   | 24                | 7.875.777   | 4.513     | 0                |
| SIPRI                 | 74     | 2.010   | 37                | 7.102.845   | 3.534     | 2 (los HTML)     |
| ESA_Space_Debris      | 24     | 2.021   | 2                 | 6.978.494   | 2.345     | 0                |
| MAPP_OEA              | 33     | 2.183   | 69                | 6.201.596   | 2.841     | 0                |
| UNOOSA                | 31     | 2.388   | 72                | 6.049.097   | 2.533     | 0                |
| DAIO                  | 33     | 1.654   | 1                 | 3.824.952   | 2.313     | 0                |
| CEOBS                 | 17     | 720     | 2                 | 2.415.462   | 3.355     | 0 ⚠ (ver §5.5)   |
| **Alertas_Tempranas** | **62** | **869** | **604**           | **999.893** | **1.151** | **47**           |
| RutaN_GEIAL           | 5      | 269     | 2                 | 863.303     | 3.209     | 0                |
| CENIA                 | 12     | 222     | 1                 | 622.179     | 2.803     | 0                |
| INPE                  | 4      | 56      | 1                 | 92.082      | 1.644     | 0                |

### 5.3 Los 51 PDFs que requieren OCR

| Fuente                | N      | Naturaleza                                                                                                                      |
| --------------------- | ------ | ------------------------------------------------------------------------------------------------------------------------------- |
| **Alertas_Tempranas** | **47** | Escaneos JPEG RGB 300 dpi, 2547×3510 px. 604 de 869 páginas son imagen pura                                                     |
| CSIS_Aerospace        | 3      | `2022-national-defense-strategy-npr-mdr` (0/20 págs), `nasa-act1958` (0/13), `battle-networks-3-compressed` (32 chars / 9 págs) |
| CSET_Georgetown       | 1      | `Data_Snapshot/...-5.pdf` — infografía de 1 página                                                                              |

429,8 MB para 869 páginas en Alertas Tempranas ≈ **500 KB por página**, confirmando escaneo de alta
resolución. **Impacto:** las preguntas q033–q050 dependen de esta fuente. Sin OCR en español solo
quedan los 363 JSON de resumen (288.814 caracteres en total, mediana de 642 por alerta).

### 5.4 Falsos positivos: por qué no basta muestrear las primeras páginas

Un primer análisis basado solo en las páginas 1–3 marcó **59** PDFs como "sin texto". La extracción
completa demuestra que **6 de ellos son perfectamente extraíbles** — simplemente tienen portada e
índice en imagen:

| Caracteres reales | c/pág | 1er texto en pág. | Archivo                                                                 |
| ----------------- | ----- | ----------------- | ----------------------------------------------------------------------- |
| 238.395           | 1.339 | 4                 | `MAPPOEA_2008-las-madres-de-la-candelaria.pdf`                          |
| 230.701           | 2.746 | 1                 | `MAPPOEA_revista-mappoea-15-anos-hechos-de-paz-1pag-1.pdf`              |
| 179.934           | 2.249 | 5                 | `CSIS_2022-national-defense-strategy-npr-mdr.pdf`                       |
| 174.056           | 1.642 | 4                 | `MAPPOEA_2008-una-experiencia-de-justicia-comunitaria-conciliemos.pdf`  |
| 129.922           | 1.382 | 4                 | `MAPPOEA_2008-la-memoria-como-forma-de-resistencia-de-los-arhuacos.pdf` |
| 23.073            | 1.442 | 5                 | `CSIS_2024-dod-commercial-space-integration-strategy.pdf`               |

> **Regla para el pipeline:** clasificar por **caracteres por página sobre el documento completo**,
> nunca por una muestra de las primeras páginas. El coste de OCR sobre 6 documentos innecesarios es
> alto, y en el caso de `MAPPOEA_2008-las-madres-de-la-candelaria` se habría perdido u OCRizado
> innecesariamente un documento con 238 K caracteres perfectos.

### 5.5 ⚠ Corrupción de codificación: el caso CEOBS-Sudán

`CEOBS/pdfs_full/2025/CEOBS_minamata-convention-initial-assessment-for-sudan.pdf` **pasa todos los
filtros de "tiene texto"** —393.686 caracteres, 180 páginas— pero **176 de sus 180 páginas son
ilegibles**:

```
Extraído : 7DEOH\x03RI\x03&RQWHQWV  0MWX\x04SJ\x04%GVSR]QW\x04ERH\x04%FFVIZMEXMSRW
Real     : Table of Contents        List of Acronyms and Abbreviations
```

La fuente incrustada carece de tabla `ToUnicode`, así que poppler devuelve **índices de glifo** en
vez de Unicode. El desplazamiento no es uniforme: la cabecera se recupera con `+29`
(`T`=0x54 → `7`=0x37) pero el cuerpo necesita `+28` — el documento mezcla dos subconjuntos de fuente
con offsets distintos. **No es reparable con un desplazamiento único; requiere OCR o mapeo de
glifos con PyMuPDF.**

**Verificado: es el único archivo del corpus con este fallo.** Un barrido de los 760 PDFs buscando
el mismo patrón (texto latino sin palabras funcionales comunes) no encontró ningún otro caso.

> **Regla para el pipeline:** además de contar caracteres, validar que el texto extraído contiene
> palabras funcionales del idioma esperado. Un documento con 393 K caracteres y **cero** apariciones
> de `the`/`of`/`and` es ruido, no contenido.

### 5.6 ⚠ Contaminación con bytes NUL: los informes ESA

6 de los 11 _Space Environment Report_ de ESA traen bytes NUL intercalados en el texto:

| Archivo                      | Bruto   | Sin NUL | NUL        | Form feeds | Págs. reales |
| ---------------------------- | ------- | ------- | ---------- | ---------- | ------------ |
| `ESA_...-i10r0-20260501.pdf` | 247.634 | 209.297 | **38.337** | 357        | 151          |
| `ESA_...-i9r1-20251021.pdf`  | 238.239 | 201.295 | 36.944     | 351        | 146          |
| `ESA_...-i9r0-20250331.pdf`  | 233.035 | 196.794 | 36.241     | 343        | 144          |
| `ESA_...-i8r0-20240719.pdf`  | 201.233 | 172.381 | 28.852     | 240        | 121          |
| `ESA_...-i7r1-20230912.pdf`  | 199.698 | 170.941 | 28.757     | 237        | 124          |
| `ESA_...-i6r0-20220422.pdf`  | 193.033 | 165.613 | 27.420     | 233        | 120          |

Dos consecuencias:

1. **El texto es correcto tras `text.replace('\x00','')`.** Verificado: 6.207 apariciones de palabras
   funcionales inglesas en `i9r0`. No es mojibake.
2. **Los _form feeds_ no coinciden con las páginas.** `i9r0` tiene 343 `\f` pero solo 144 páginas:
   199 son espurios, dentro del contenido. Partir por `\f` para paginar **inflaría el recuento en
   +955 páginas a nivel de corpus** (37.780 vs 36.825 reales).

> **Regla para el pipeline:** obtener el número de páginas de `pdfinfo`, nunca contando `\f`.
> Limpiar `\x00` de todo texto extraído.

### 5.7 Cifrado: no es un obstáculo

**88 PDFs vienen cifrados** (AES-256: 46, AES: 38, RC4: 4), y **71 declaran `copy:no`**.
Verificado extrayendo el texto **completo** de los 88:

> **88 de 88 se extraen sin ningún problema.** Son permisos declarativos que poppler ignora
> legítimamente. No hace falta desencriptar ni usar `qpdf --decrypt`.

_(Un análisis previo basado en 2 páginas reportó 6 fallos; los 6 eran escaneos, no cifrado.)_

### 5.8 Propiedades técnicas

**Versiones PDF:** 1.7 (348), 1.6 (159), 1.4 (155), 1.5 (74), 1.3 (21), 1.2 (1), ilegible (2).

**Etiquetado** (estructura de accesibilidad, útil para extraer tablas): 361 sí / 397 no.

**Productores:** Adobe PDF Library (274), Acrobat Distiller (60), Microsoft Word (47), 3-Heights (22),
Google Docs Renderer (8), iLovePDF (7), sin metadato (116).
**Creadores:** ~150 son Adobe InDesign — informes maquetados **a dos columnas**.

> **Regla para el pipeline:** usar siempre `pdftotext -layout`. Sin ese flag, las ~150 maquetas de
> InDesign entrelazan las columnas y producen texto sin sentido semántico.

**Advertencias de sintaxis:** 125 PDFs emiten avisos por `stderr` (mayoritariamente
`Invalid Font Weight` en los informes de AI Index). Son inocuos: `exit code 0` y texto correcto.
Solo los 2 HTML devuelven `exit code 1`.

### 5.9 Documentos singulares

**Los más extensos:**

| Págs.                 | Archivo                                                |
| --------------------- | ------------------------------------------------------ |
| 1.330                 | `CSIS_bills-115hr2810eh.pdf` — texto legislativo NDAA  |
| 1.120                 | `CSIS_plaw-116publ92.pdf` — ley pública                |
| 765                   | `CSIS_fy2019-presidents-budget-nasa.pdf`               |
| 691                   | `CSIS_sp1235v2web.pdf`                                 |
| 502 / 457 / 425 / 386 | `AIINDEX_ai-index-report-{2024,2025,2026,2023}.pdf`    |
| 456                   | `AIINDEX_ai-index-2025-chinese-version.pdf` (en chino) |
| 371                   | `SWF_global-counterspace-capabilities-2026-hr.pdf`     |

Los 4 textos legislativos de CSIS suman ~3.900 páginas (11 % del corpus) con baja densidad semántica
para la mayoría de preguntas. Candidatos a despriorizar.

**Los 11 mixtos** (texto correcto pero >10 % de páginas solo imagen) — no requieren OCR completo,
solo OCR selectivo si esas páginas importan:

| % págs. imagen | Archivo                                                                         |
| -------------- | ------------------------------------------------------------------------------- |
| 18,8 %         | `ILIA_2025-executive-summary.pdf` (3/16)                                        |
| 18,8 %         | `CSIS_2024-dod-commercial-space-integration-strategy.pdf` (3/16)                |
| 18,2 %         | `SWF_...victoria-samson-quad-nations-security-dialogue...pdf` (2/11)            |
| 16,7 %         | `ESA_st-space-49e.pdf` (2/12)                                                   |
| 12,7 %         | `CSIS_rumsfeldcommission.pdf` (21/165)                                          |
| 12,5 %         | `UNOOSA_annual-report-2022.pdf` (12/96)                                         |
| 11,8 %         | `UNOOSA_annual-report-2021.pdf` (12/102)                                        |
| 11,1 %         | `SWF_2023-executive-summary-english.pdf` (2/18)                                 |
| 11,1 %         | `MAPPOEA_2013-plan-de-choque-para-la-restitucion...pdf` (6/54)                  |
| 10,7 %         | `MAPPOEA_2008-las-madres-de-la-candelaria.pdf` (19/178)                         |
| 10,6 %         | `MAPPOEA_2008-la-memoria-como-forma-de-resistencia-de-los-arhuacos.pdf` (10/94) |

**Densidad de imágenes** — 649 de 760 PDFs tienen ≥1 imagen en sus primeras 5 páginas. Casos que
romperán un extractor de imágenes ingenuo:

- `MAPPOEA_2010-acompanando-una-oportunidad-para-la-paz.pdf`: **14.623 imágenes en 5 páginas**
  (escaneo fragmentado en miles de tiles).
- `RESDAL_atlas-2016-ing-*.pdf`: 800–1.400 imágenes por 5 páginas (atlas cartográficos).

### 5.10 Los 47 nombres de PDF duplicados: NO son traducciones del mismo documento

Todos en CSET: `CSET_center-for-security-and-emerging-technology-{N}.pdf` existe a la vez en
`pdfs/Reports/` (61 archivos) y `pdfs/Translation/` (46 archivos).

**Verificado abriendo los pares — son documentos completamente distintos, no original y traducción:**

| N   | `Reports/`                                                              | `Translation/`                                                             |
| --- | ----------------------------------------------------------------------- | -------------------------------------------------------------------------- |
| 10  | _"When AI Builds AI"_ — informe de taller (1.563 KB, 0 caracteres CJK)  | Traducción de la normativa china de control de exportaciones (388 KB, CJK) |
| 11  | _"China's Embodied AI: A Path to AGI"_ (2.477 KB, 0 CJK)                | Traducción de un plan del equivalente chino de la NASA (272 KB, CJK)       |
| 25  | _"Policy Takeaways for Biotech Manufacturing Apprenticeships"_ (109 KB) | Traducción de directrices de seguridad (218 KB, CJK)                       |

La colisión ocurre porque el scraper usó el **título genérico de la página** ("Center for Security
and Emerging Technology") como nombre para todos los documentos sin título propio.

> **Regla para el pipeline:** la ruta completa es el identificador; el basename **no es único**.
> Confirmado que no hay ningún par con MD5 idéntico en todo el corpus.

### 5.11 Idiomas — son 8, no 3

Verificado por detección de escritura Unicode sobre el texto extraído:

| Idioma / escritura   | Dónde                                                              | Ejemplos verificados                                                          |
| -------------------- | ------------------------------------------------------------------ | ----------------------------------------------------------------------------- |
| **Inglés**           | AI_Index, CSET, DAIO, CSIS, ESA, CEOBS, SIPRI, RESDAL, UNOOSA, SWF | —                                                                             |
| **Español**          | CENIA, ILIA, RutaN, MAPP-OEA, Alertas, CEEEP                       | —                                                                             |
| **Portugués**        | **INPE** (los 55 JSON y los 4 PDFs)                                | _"O Instituto Nacional de Pesquisas Espaciais…"_                              |
| **Chino (CJK)**      | SWF, AI_Index, CSET (46 traducciones)                              | `SWF_gcsr-2026-execsum-chi.pdf` — 3.179 caract. CJK                           |
| **Árabe**            | SWF, UNOOSA                                                        | `UNOOSA_st-space-088a.pdf` — 1.867 caract. árabes                             |
| **Ruso (cirílico)**  | SWF                                                                | `SWF_gcsr-2026-execsum-rus.pdf` — 10.876 caract. cirílicos                    |
| **Coreano (hangul)** | SIPRI                                                              | `SIPRI_0226-milai-procurement-kr.pdf` — 957 hangul + 393 latinos              |
| **Japonés**          | CSIS                                                               | `CSIS_bingen-earth-uchu-japanese-0120025final.pdf` — CJK 1.022 + hiragana 540 |

**20 PDFs son predominantemente de escritura no latina** (algunos, como el japonés de CSIS, mezclan
ambas: 1.752 caracteres latinos + 1.022 CJK + 540 hiragana). Un detector de idioma basado en vocales
o en palabras funcionales latinas los marcará como corruptos: hay que **discriminar por rango
Unicode antes** de aplicar cualquier heurística léxica.

Las preguntas están en español y la mayor parte del corpus en inglés → **la recuperación
cross-lingual no es opcional.**

---

## 6. JSON: 964 archivos, 4,35 M caracteres de texto

Integridad: **0 errores de parseo, 100 % UTF-8, 0 BOM, 0 URLs duplicadas.**

### 6.1 Familia A — Artículo web scrapeado

Núcleo común: `url`, `title`, `date`, `body_paragraphs` (lista) y `body_text` (la misma lista
concatenada con `\n\n`). **`body_paragraphs` y `body_text` son redundantes** — elegir uno.

| Fuente           | N   | Campos propios                                                       | Caracteres | Rango temporal |
| ---------------- | --- | -------------------------------------------------------------------- | ---------- | -------------- |
| Atlantic_Council | 186 | `authors`, `excerpt`, `tags`                                         | 1.572.838  | 2020–2026      |
| CSIS_Aerospace   | 102 | `authors`, `topics`, `pdf_links`, `images`                           | 1.565.133  | 2018–2026      |
| SWF_Counterspace | 55  | `authors`, `topics`, `pdf_links`, `external_links`, `internal_links` | 267.662    | 2010–2026      |
| INPE             | 55  | `excerpt`, `pdf_links`, **`science_links`**, `images`                | 175.131    | 2023–2026      |
| SIPRI            | 52  | `authors`, `topics`, `pdf_links`, `images`                           | 79.694     | 2024–2026      |
| CEOBS            | 19  | `authors`, `categories`, `pdf_links`, `images`                       | 163.111    | 2025–2026      |
| ESA_Space_Debris | 16  | `excerpt`, `pdf_links`, `images`, `tags`                             | 120.406    | 2022–2026      |

Completitud medida:

```
Atlantic_Council  100 % en los 8 campos · body_text 1.082 / 6.463 / 48.229 (mín/mediana/máx)
CSIS_Aerospace    authors 101/102 · topics 101/102 · images 25/102 · body_text 60 / 2.230 / 297.739
SWF_Counterspace  authors 50/55 · topics 48/55 · excerpt 43/55
SIPRI             authors 29/52 (44 % SIN AUTOR) · images 0/52 (siempre vacío)
ESA_Space_Debris  date 7/16 (56 % SIN FECHA) · tags 0/16 (siempre vacío)
CEOBS             date 10/19 (47 % sin fecha) · authors 0/19 (siempre vacío)
INPE              100 % en url/title/date · 52 de 55 son de 2026
```

### 6.2 Familia B — Página institucional (CENIA, 15 archivos)

`url`, `title`, `sections` (`{heading, paragraphs}`), `lists`, `links` (`{text,url}`), `pdf_links`,
`images` (`{src,alt}`), y el booleano **`contenido_limitado`** que marca extracción incompleta.
Solo 11 de 15 traen `sections` con contenido; 6 de 15 no dan texto suficiente para detectar idioma.

### 6.3 Familia C — Alertas Tempranas (363 archivos) — el núcleo de F3

Esquema: `url`, `title`, `fields`, `body_paragraphs`, `pdf_links`, `doc_links`, **`alerta_meta`**.

`alerta_meta` está **relleno al 100 % en los 363 archivos**:

| Campo                      | Cobertura | Únicos | Contenido                                                                |
| -------------------------- | --------- | ------ | ------------------------------------------------------------------------ |
| `codigo`                   | 363/363   | 363    | Código oficial `NNN-AA` (p. ej. `001-22`)                                |
| `tipo`                     | 363/363   | **2**  | `Inminencia` (197) · `Estructural` (166)                                 |
| `fecha_emision`            | 363/363   | 302    | ISO `YYYY-MM-DD` — **el único campo de fecha ya normalizado del corpus** |
| `tema_clave`               | 363/363   | 362    | Resumen narrativo del escenario de riesgo                                |
| `municipios`               | 363/363   | 289    | Formato `Municipio (Departamento)`                                       |
| `detail_url` / `detail_id` | 363/363   | 363    | Portal de la Defensoría                                                  |

Distribución: 2017 (1), 2018 (86), 2019 (56), 2020 (54), 2021 (29), 2022 (34), 2023 (39), 2024 (27),
2025 (20), 2026 (17).

**Volumen de texto real:** 288.814 caracteres en total.
Por alerta: mín 189 · p25 502 · **mediana 642** · p75 863 · máx 5.415.
**21 alertas tienen menos de 50 palabras** — son resúmenes mínimos, no informes.

**`fields`, `pdf_links` y `doc_links` están vacíos en los 363 archivos.** Campos del esquema que
nunca se poblaron. El informe completo está en los PDFs escaneados (§5.3).

### 6.4 Familia D — Catálogos

Listas de objetos que documentan la descarga. **Cada catálogo existe duplicado en `.json` y `.csv`
con contenido idéntico** (aunque el orden de columnas puede diferir).

| Catálogo               | Registros | Estado de descargas                                          |
| ---------------------- | --------- | ------------------------------------------------------------ |
| `RESDAL_catalog-2`     | 95        | **95/95 OK** — Atlas 2005→2024, ESP/ENG, por país y capítulo |
| `MAPPOEA_mapp-catalog` | 78        | **10 OK, 63× 404, 5× 503**                                   |
| `DAIO_catalog-2`       | 35        | 33 OK, 1× 404, 1 `no_url`                                    |
| `AMAZONUW_tiles-index` | 262       | **73 OK, 189× 404**                                          |
| `sipri_full_catalogo`  | 50        | Con enlaces a PDF por artículo                               |
| `resdal_catalogo`      | 46        | Pipeline alterno                                             |
| `mapp_catalogo`        | 31        | Pipeline alterno, todos OK                                   |
| `ceobs_full_catalogo`  | 20        |                                                              |
| `ceeep_catalogo`       | 80        | Revista _Seguridad y Poder Terrestre_                        |
| `CSIS_catalog-2`       | 3         | 3 OK (destino incorrecto, ver §4.4)                          |
| `RUTAN_catalog-2`      | 2         | 2 OK                                                         |
| `DEFENSA21_catalog-2`  | 5         | **5/5 error, 0 entries**                                     |

`SIPRI_catalog-2.json` y `CEOBS_catalog-2.json` no son listas sino objetos de resumen con contadores
agregados (`rss_articles`, `web_publications`, `pdfs_downloaded`, `scraped_at`).

### 6.5 Los JSON sin texto propio

`MAPP_OEA` y `RESDAL` aportan **0 caracteres de texto** en sus JSON: sus 3 archivos son
`*_catalogo.json` + `*_registro.json` + catálogo del pipeline 2. Todo su contenido está en los PDFs.

---

## 7. CSV: 26 archivos

Todos UTF-8 sin BOM, **0 filas irregulares** con un parser CSV real. Dos grupos.

### 7.1 Datasets de investigación de AI Index (17 archivos, ~78 MB)

**PubMed — bibliometría** (`Research_Development/datasets/`):

| Archivo                                                   | Filas       | Cols              |
| --------------------------------------------------------- | ----------- | ----------------- |
| `AIINDEX_pubmed-artificial-intelligence-csv.csv`          | **111.775** | 12                |
| `AIINDEX_pubmed-robotics-csv.csv`                         | 61.521      | 12                |
| `AIINDEX_pubmed-machine-learning-csv.csv`                 | 46.514      | 12                |
| `AIINDEX_pubmed-computer-vision-csv.csv`                  | 12.020      | 12                |
| `AIINDEX_pubmed-nlp-csv.csv`                              | 6.822       | **11** ⚠          |
| `AIINDEX_pubmed-{ai,ml,cv,nlp,robotics}-timeline-csv.csv` | 44–67       | 2 (`Year, Count`) |

Esquema de 12 columnas: `(índice sin nombre), PMID, Title, Authors, Citation, First Author,
Journal/Book, Publication Year, Create Date, PMCID, NIHMS ID, DOI`.

**ClinicalTrials.gov — ensayos clínicos** (`Healthcare_Medicine/datasets/`):

| Archivo                                                  | Filas | Cols |
| -------------------------------------------------------- | ----- | ---- |
| `AIINDEX_clinicaltrials-robotics-csv.csv`                | 1.343 | 27   |
| `AIINDEX_clinicaltrials-computer-science-csv.csv`        | 870   | 27   |
| `AIINDEX_clinicaltrials-computer-vision-csv.csv`         | 573   | 27   |
| `AIINDEX_clinicaltrials-machine-learning-csv.csv`        | 374   | 27   |
| `AIINDEX_clinicaltrials-artificial-intelligence-csv.csv` | 313   | 27   |
| `AIINDEX_clinicaltrials-nlp-csv.csv`                     | 23    | 27   |
| `AIINDEX_lit-covid-ai-covid-literature-csv.csv`          | 8.866 | 3    |

### 7.2 ⚠ Cuatro trampas de parseo verificadas

**1. Un CSV está delimitado por TABULADORES.**
`AIINDEX_lit-covid-ai-covid-literature-csv.csv` usa `\t` pese a la extensión `.csv`. Es el único.

**2. Ese mismo archivo tiene 8.188 saltos de línea DENTRO de campos entrecomillados.**

```
Filas lógicas reales : 8.866
Líneas físicas       : 17.054     ← lo que devuelve `wc -l`
```

Cualquier lectura línea a línea (`wc -l`, `split('\n')`, Spark sin `multiline=true`,
`pandas.read_csv` con motor incorrecto) **duplicará y corromperá el dataset**.

**3. Caracteres separadores Unicode que rompen `str.splitlines()` de Python.**

| Archivo                                  | Carácter      | Ocurrencias |
| ---------------------------------------- | ------------- | ----------- |
| `pubmed-artificial-intelligence-csv.csv` | `U+2029` (PS) | 2           |
| `pubmed-computer-vision-csv.csv`         | `U+2029` (PS) | 2           |
| `pubmed-robotics-csv.csv`                | `U+2029` (PS) | 2           |
| `pubmed-machine-learning-csv.csv`        | `U+2028` (LS) | 1           |

`splitlines()` parte por estos caracteres; `csv.reader` con `newline=''` no. Con `splitlines()` el
archivo de 111.775 filas devuelve 111.777 con 4 filas desalineadas.

**4. Espacios duros U+00A0 muy extendidos.**

| Archivo                                   | NBSP  |
| ----------------------------------------- | ----- |
| `clinicaltrials-robotics-csv.csv`         | 1.256 |
| `clinicaltrials-computer-science-csv.csv` | 824   |
| `clinicaltrials-computer-vision-csv.csv`  | 537   |
| `pubmed-artificial-intelligence-csv.csv`  | 364   |
| `clinicaltrials-machine-learning-csv.csv` | 339   |
| `pubmed-robotics-csv.csv`                 | 338   |
| … 7 archivos más                          | 9–276 |

Concentrados en la columna `Age` (`18 Years to 80 Years \xa0 (Adult, Older Adult)`).
**`str.strip()` no los elimina.** Usar `.replace(' ',' ')` antes.

**Además:** el esquema no es homogéneo — `pubmed-nlp-csv.csv` tiene 11 columnas frente a las 12 de
sus 4 hermanos (le falta la columna índice inicial). Concatenar sin alinear cabeceras desplaza todos
los campos. Y los campos multivalor usan **pipe `|` como separador interno**
(`Artificial Intelligence|Glaucoma`).

### 7.3 `AMAZONUW_amazonunderworld-data.csv` — el dataset geoespacial

486 KB, **4.369 filas × 32 columnas**. Extraído de los vector tiles.

```
tile_zoom, tile_x, tile_y, fid,
au_ID_concatenated, au_country, au_level1, au_level2,
b_ADM1_PCODE, b_ADM2_PCODE, b_ADM1_ES, b_ADM2_ES, b_ADM1_PT, b_ADM2_PT,
au_area_km2, au_population, au_invest_with_presence, au_no_info,
grupo_EMC, grupo_EMBF, grupo_ELN, grupo_CDF_AGC, grupo_Seg_Marquetalia,
grupo_Los_Lobos, grupo_Los_Choneros, grupo_CV, grupo_PCC, grupo_Others,
total_grupos_presentes, grupos_detalle_ES, grupos_detalle_PT, grupos_detalle_EN
```

> **⚠ De las 4.369 filas, solo 999 tienen datos.** Las 3.370 restantes son teselas de zoom bajo con
> geometría pero sin atributos. Tras deduplicar por municipio quedan **986 municipios únicos**.

| Zoom  | Filas     | Con datos de grupo |
| ----- | --------- | ------------------ |
| 3     | 457       | 2                  |
| 4     | 452       | 2                  |
| 5     | 507       | 2                  |
| **6** | **2.953** | **993**            |

**Cobertura geográfica (municipios únicos):** Brasil 772, **Colombia 87**, Ecuador 40, Bolivia 34,
Perú 32, Venezuela 22.

**Presencia por grupo armado** (municipios únicos con valor `SI`):

| Grupo                                         | Municipios |
| --------------------------------------------- | ---------- |
| `grupo_CV` (Comando Vermelho)                 | 403        |
| `grupo_PCC` (Primeiro Comando da Capital)     | 165        |
| `grupo_Others`                                | 148        |
| `grupo_EMC` (Estado Mayor Central)            | 57         |
| `grupo_CDF_AGC` (Comandos de Frontera / AGC)  | 41         |
| `grupo_Los_Lobos`                             | 40         |
| `grupo_EMBF`                                  | 31         |
| `grupo_Seg_Marquetalia` (Segunda Marquetalia) | 31         |
| `grupo_ELN`                                   | 25         |
| `grupo_Los_Choneros`                          | 18         |

`total_grupos_presentes`: 0 → 324 municipios · 1 → 451 · 2 → 137 · 3 → 62 · 4 → 12.
**324 municipios tienen `au_no_info = SI`** (sin información, no ausencia de grupos).

> **Notas de tipado:** las columnas de grupo son cadenas `'SI'`/`'NO'`, no booleanos.
> Los códigos `b_ADM1_PCODE`/`b_ADM2_PCODE` siguen el estándar OCHA (`CO41`, `CO41319`, `BO0801`),
> lo que permite unir con shapefiles administrativos oficiales.
> El dataset es **regional amazónico**: solo 87 municipios colombianos, insuficiente por sí solo
> para q041–q043 (Chocó, Antioquia, Norte de Santander, Arauca no son todos amazónicos).

### 7.4 Espejos de catálogo (9 archivos)

Réplica del contenido de los catálogos JSON. El orden de columnas puede diferir del orden de claves
del JSON (p. ej. `CSIS_catalog-2.csv` empieza por `nombre, scraped_at, status…` y el JSON por
`nombre, titulo, page_url…`). El contenido es idéntico.

`SWF_report-data.csv` (40 filas × 4 columnas) usa formato **largo clave-valor**
(`seccion, campo, valor, url`), único en el corpus.

---

## 8. La regla de renombrado: cómo mapear catálogos a archivos

**El problema:** los catálogos citan nombres del servidor (`ATLAS-2024-ESP.pdf`,
`daio_study2634_fragmented_efforts_....pdf`) pero el corpus fue renombrado a
`{CÓDIGO}_{slug}`. Una búsqueda literal falla en el 100 % de los casos.

**La regla verificada** — normalizar el **basename de la URL**, no el campo de ruta local:

```python
import os, re, urllib.parse, unicodedata

def nombre_estandarizado(url, codigo_observatorio):
    """Convierte la URL de un catálogo al nombre real en disco. Tasa de acierto: 99,5%."""
    base = os.path.basename(urllib.parse.unquote(urllib.parse.urlparse(url).path))
    stem, ext = os.path.splitext(base)
    s = ''.join(c for c in unicodedata.normalize('NFD', stem)   # quitar acentos
                if unicodedata.category(c) != 'Mn')
    s = s.lower().replace('_', '-').replace(' ', '-')
    s = re.sub(r'[^a-z0-9.-]', '-', s)
    s = re.sub(r'-+', '-', s).strip('-')
    c = codigo_observatorio.lower()
    if s.startswith(c + '-'):          # quitar prefijo redundante: daio-study… -> study…
        s = s[len(c) + 1:]
    return f"{codigo_observatorio}_{s}{ext.lower() or '.pdf'}"
```

Resultado sobre los 7 catálogos con rutas de PDF (220 referencias):

| Catálogo                    | Refs.   | Exacto  | Sufijo `-2` | Prefijo | Sin resolver   |
| --------------------------- | ------- | ------- | ----------- | ------- | -------------- |
| `RESDAL_catalog-2.json`     | 95      | 95      | —           | —       | 0              |
| `resdal_catalogo.json`      | 46      | 45      | —           | —       | **1**          |
| `DAIO_catalog-2.json`       | 33      | 23      | **10**      | —       | 0              |
| `mapp_catalogo.json`        | 31      | 30      | —           | 1       | 0              |
| `MAPPOEA_mapp-catalog.json` | 10      | 10      | —           | —       | 0              |
| `CSIS_catalog-2.json`       | 3       | 3       | —           | —       | 0              |
| `RUTAN_catalog-2.json`      | 2       | 2       | —           | —       | 0              |
| **Total**                   | **220** | **208** | **10**      | **1**   | **1** (99,5 %) |

**Dos matices imprescindibles:**

1. **Usar el campo de URL, no el de ruta.** Para CSIS hay que usar `pdf_url` (no `dest`), para RutaN
   `url` (no `path`), para DAIO `url_pdf` (no `filename`). Con los campos de ruta local la tasa de
   acierto cae a 0 % en CSIS y RutaN.
2. **Sufijo `-2` por colisión.** 10 estudios de DAIO se guardaron como `DAIO_study23NN-2.pdf` en vez
   de `DAIO_study23NN.pdf`. Hay que probar ambas variantes.

---

## 9. Otros formatos

### 9.1 PBF — vector tiles (73 archivos, 17 MB)

`Amazon_Underworld/tiles/{z}/{x}/{y}.pbf`. Decodificados a nivel de protobuf:

| Propiedad         | Valor                                                              |
| ----------------- | ------------------------------------------------------------------ |
| Formato           | **Mapbox Vector Tile v2**                                          |
| Compresión        | **NINGUNA — protobuf crudo** (empiezan por `0x1a`, no por `1f 8b`) |
| Capas             | **1 sola: `au_compilado_R02`** (idéntica en las 73 teselas)        |
| `extent`          | 4096 en las 73                                                     |
| Features          | **11.906 en total** — mín 1, mediana 124, máx 1.263 por tesela     |
| Teselas ilegibles | **0**                                                              |

Cobertura: z3 (6), z4 (15), z5 (54), z6 (187 intentadas) → **73 descargadas de 262, 189 con HTTP 404.**

```python
import mapbox_vector_tile
tile = mapbox_vector_tile.decode(open(ruta, 'rb').read())   # SIN gzip.decompress()
```

> En la práctica no hace falta tocarlos: `AMAZONUW_amazonunderworld-data.csv` (§7.3) ya contiene los
> atributos en formato tabular. Los `.pbf` solo aportan la geometría.

### 9.2 Imágenes (9 archivos, 1,2 MB)

Todas en `SWF_Counterspace/swf_counterspace_2026/images/`. Verificado por magic bytes: 8 JPEG + 1 AVIF.
**Al menos tres son figuras de datos del informe Global Counterspace 2026:**

| Archivo                                               | Tamaño | Contenido                             |
| ----------------------------------------------------- | ------ | ------------------------------------- |
| `SWF_69caf750...-stoplight-chart-execsummary-web.jpg` | 352 KB | Matriz semáforo del resumen ejecutivo |
| `SWF_69cac182...-table-5-1-web.jpg`                   | 288 KB | Tabla 5-1 renderizada como imagen     |
| `SWF_6a063f3c...-asat-by-country-2026.jpg`            | 41 KB  | Capacidades ASAT por país             |

Esta información tabular **no existe en ningún formato textual del corpus** y es directamente
relevante para q018, q024 y q026. Requiere un modelo de visión.

El AVIF (`...victoriasamson-web.avif`, 15 KB) es una foto de perfil, sin valor informativo.

### 9.3 TXT (1 archivo)

`SWF_full-text.txt` (12,6 KB): volcado del informe SWF 2026 con cabecera `SOURCE:` / `SCRAPED:`.
**Calidad baja** — arrastra el menú de navegación completo del sitio ("News & Media / About /
Reports / Events…") antes del contenido. Requiere limpieza de _boilerplate_.

### 9.4 XLSX (6 archivos)

| Archivo                                | Hoja          | Filas XML    | **Filas con datos** | Contenido                                                 |
| -------------------------------------- | ------------- | ------------ | ------------------- | --------------------------------------------------------- |
| `AIINDEX_lit-covid-...xlsx`            | `lit_covid`   | 8.867        | 8.867               | **Duplicado exacto del CSV homónimo**                     |
| `AIINDEX_mag-conferences-list.xlsx`    | `Conferences` | **999**      | **28** ⚠            | 27 conferencias (AAAI, ACL, CVPR, NeurIPS…), **8 sin ID** |
| `AIINDEX_mag-author-lifecycle.xlsx`    | `Sheet1`      | 3            | 3                   | **Solo 2 autores**: Andrew Ng, Yann LeCun                 |
| `AIINDEX_mag-publications-fields.xlsx` | `Sheet1`      | 7            | 7                   | 6 campos de IA, columna `Status` = `Inprogress`           |
| `FASE ORDENADA CODEFEST.xlsx`          | `F1`,`F3`     | 6, 21        | 6, **12**           | Set de referencia (§3.3)                                  |
| `Indice_Datos_Codefest.xlsx`           | 3 hojas       | 23, 5, 1.827 | 23, 5, 1.827        | Índice maestro (§3.2)                                     |

> **⚠ `mag-conferences-list.xlsx` no tiene 999 conferencias.** El XML declara 999 elementos `<row>`
> pero **971 están vacíos**. El contenido real son 27 conferencias, de las cuales 8 (ROS, ROScon,
> WMT, ACM FAT\*, ACM IVA, Indaba, Interspeech, RightsCon) ni siquiera tienen ID.
> Junto con `mag-author-lifecycle` (2 autores) y `mag-publications-fields` (`Status: Inprogress`),
> son **tres datasets abandonados a medias en el origen**.

**Aviso de tipado:** los IDs numéricos están como flotantes en notación científica
(`3.2634855E7` en vez de `32634855`; `2.104401652E9` para un Author ID). Al leer con
`openpyxl`/`pandas` hay que castear a `int` o los PMIDs quedan corruptos.
**El CSV equivalente no tiene este problema — preferir siempre el CSV cuando exista.**

### 9.5 Ruido

9 archivos `.DS_Store` (6.148 bytes cada uno) en F1, F2, F3 y 6 subcarpetas. Excluir del pipeline.
Indican que el corpus se ensambló desde macOS.

---

## 10. Inventario completo de anomalías

### Bloqueantes

| #   | Anomalía                                                         | Evidencia                                                                                   |
| --- | ---------------------------------------------------------------- | ------------------------------------------------------------------------------------------- |
| 1   | **51 PDFs requieren OCR**                                        | 47 Alertas Tempranas (JPEG 300 dpi) + 3 CSIS + 1 CSET. Afecta a q033–q050                   |
| 2   | **`CEOBS_minamata-...-sudan.pdf`: 176 de 180 páginas ilegibles** | Glifos sin `ToUnicode`; 393.686 caracteres de basura que pasan cualquier filtro de longitud |
| 3   | **`Wilson_Center` vacío**                                        | 0 entradas en el directorio; 0 en las 8 columnas del índice                                 |
| 4   | **`Defensa21_LatAm` sin contenido**                              | `articulos-2.json` = `[]`; los 5 feeds RSS con `status:"error"`, `entries:0`                |
| 5   | **2 archivos `.pdf` son HTML**                                   | `SIPRI_22136.pdf`, `SIPRI_hsrc20lmip20report...pdf`                                         |

### Codificación y extracción

| #   | Anomalía                                    | Evidencia                                                                                      |
| --- | ------------------------------------------- | ---------------------------------------------------------------------------------------------- |
| 6   | **Bytes NUL en 6 informes ESA**             | Hasta 38.337 por archivo. Se limpia con `replace('\x00','')`                                   |
| 7   | **Form feeds espurios en los mismos 6 ESA** | `i9r0`: 343 `\f` para 144 páginas. Paginar por `\f` infla el corpus en +955 páginas            |
| 8   | **20 PDFs en escritura no latina**          | Árabe, ruso, coreano, japonés, chino. Los detectores léxicos latinos los marcan como corruptos |
| 9   | **125 PDFs emiten avisos de sintaxis**      | Mayoría `Invalid Font Weight` (AI Index). Inocuos, `exit code 0`                               |
| 10  | **~150 PDFs maquetados a dos columnas**     | Adobe InDesign. Sin `pdftotext -layout` el texto queda entrelazado                             |

### Calidad de metadatos

| #   | Anomalía                                   | Evidencia                                                                                                                                                                                                                                   |
| --- | ------------------------------------------ | ------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------- |
| 11  | **`tags` de Atlantic Council inservibles** | 6 conjuntos distintos en 186 docs (tamaños 138–140); un solo conjunto cubre 159 docs                                                                                                                                                        |
| 12  | **Campos siempre vacíos**                  | `ESA.tags` 0/16 · `CEOBS.authors` 0/19 · `SIPRI.images` 0/52 · `Alertas.fields`/`.pdf_links`/`.doc_links` 0/363                                                                                                                             |
| 13  | **Fechas ausentes**                        | ESA 9/16 (56 %) · CEOBS 9/19 (47 %)                                                                                                                                                                                                         |
| 14  | **Autores ausentes**                       | SIPRI 23/52 (44 %)                                                                                                                                                                                                                          |
| 15  | **Formatos de fecha heterogéneos**         | `May 21, 2026` (Atlantic) · `2018-06-01T15:48:40+00:00` (CSIS) · `01/04/2025` (ESA, **d/m vs m/d ambiguo**) · `2023-10-09` (INPE) · `2024` (CEEEP). **Solo `Alertas.fecha_emision` está en ISO limpio**                                     |
| 16  | **`authors` contaminado con cargos**       | Atlantic: `['David Bray', 'Nonresident Senior Fellow', 'Former Distinguished Fellow']` — un artículo lista 9 "autores" que son 4 personas + títulos. SIPRI: un "autor" es `'Dr Michal Krelina is an Associate Senior Researcher at SIPRI.'` |
| 17  | **Usuario de CMS como autor**              | `'sscott'` en Atlantic Council `page_17`                                                                                                                                                                                                    |
| 18  | **`body_text` con rango extremo**          | CSIS: de 60 a 297.739 caracteres. Los de ~60 son placeholders sin contenido                                                                                                                                                                 |
| 19  | **21 alertas con <50 palabras**            | Mínimo 189 caracteres (`016-18`)                                                                                                                                                                                                            |

### Formatos y parseo

| #   | Anomalía                                   | Evidencia                                                                                                  |
| --- | ------------------------------------------ | ---------------------------------------------------------------------------------------------------------- |
| 20  | **CSV con delimitador TAB**                | `lit-covid-ai-covid-literature-csv.csv`                                                                    |
| 21  | **8.188 saltos de línea dentro de campos** | Mismo archivo: 8.866 filas lógicas vs **17.054 líneas físicas**                                            |
| 22  | **U+2028/U+2029 rompen `splitlines()`**    | 4 CSV de PubMed (1–2 ocurrencias cada uno)                                                                 |
| 23  | **NBSP U+00A0 masivo**                     | 4.561 en 13 archivos; hasta 1.256 en `clinicaltrials-robotics`                                             |
| 24  | **Esquema CSV inconsistente**              | `pubmed-nlp-csv.csv` con 11 columnas frente a 12 de sus hermanos                                           |
| 25  | **XLSX con IDs en notación científica**    | `3.2634855E7` en vez de `32634855`                                                                         |
| 26  | **3 XLSX abandonados**                     | `conferences` (28/999 filas), `author-lifecycle` (2 autores), `publications-fields` (`Status: Inprogress`) |
| 27  | **PBF sin comprimir**                      | Protobuf crudo; `gzip.decompress()` falla                                                                  |

### Estructurales

| #   | Anomalía                                                  | Evidencia                                                                                                              |
| --- | --------------------------------------------------------- | ---------------------------------------------------------------------------------------------------------------------- |
| 28  | **47 basenames duplicados que NO son el mismo documento** | CSET `Reports/` vs `Translation/`: documentos completamente distintos con nombre colisionado. 0 pares con MD5 idéntico |
| 29  | **Catálogos apuntan a rutas inexistentes**                | `csis_pdfs/` solo contiene el catálogo; los 3 PDFs están en `pdfs_full/Space_Threat_Assessment/`                       |
| 30  | **189 vector tiles con HTTP 404**                         | 73 de 262 en Amazon Underworld                                                                                         |
| 31  | **68 de 78 descargas fallidas en MAPP-OEA**               | 63× 404, 5× 503 — recuperado por el pipeline paralelo (31 PDFs)                                                        |
| 32  | **Solo 999 de 4.369 filas útiles en el CSV geoespacial**  | 986 municipios únicos; solo 87 colombianos                                                                             |
| 33  | **Doble numeración en el set de referencia**              | `2,3,4` vs `q0047–q0052`, ninguna alineada con `q001–q050`                                                             |
| 34  | **Referencias a un chunking inexistente**                 | IDs `DOC-NNNN-chunk-NNNN` sin mapeo incluido                                                                           |
| 35  | **Columna `PBF (Mapas)` mal etiquetada**                  | Cuenta 74 = 73 PBF + 1 AVIF                                                                                            |
| 36  | **Solo 8 de 21 fuentes tienen catálogo**                  | Para las otras 13, el índice maestro es la única referencia                                                            |

---

## 11. Mapa pregunta → fuente

### F1 · `q001`–`q016` — IA y capacidades estratégicas

| Fuente                                                | Aporte                                                                                                     | Estado                          |
| ----------------------------------------------------- | ---------------------------------------------------------------------------------------------------------- | ------------------------------- |
| **DAIO** (33 PDFs, 1.654 pág, 3,8 M car.)             | Estudios país por país de IA en defensa (Brasil, Bélgica, Ucrania, Finlandia…) — **la fuente más directa** | Texto limpio                    |
| **CSET Georgetown** (127 PDFs, 8,7 M car.)            | Semiconductores, talento, política US-China + 46 traducciones del chino                                    | 1 requiere OCR                  |
| **AI Index Stanford** (44 PDFs + 17 CSV, 15,0 M car.) | Métricas globales 2023–2026 + datasets bibliométricos                                                      | Texto limpio                    |
| **ILIA LatAm** (10 PDFs, 7,9 M car.)                  | Índice Latinoamericano de IA — talento y madurez regional (q004, q005)                                     | Texto limpio (ES)               |
| **Atlantic Council** (186 JSON, 1,6 M car.)           | Análisis geopolíticos de tecnología                                                                        | JSON limpio, **ignorar `tags`** |
| **CENIA** (12 PDFs + 15 JSON)                         | Ecosistema chileno de IA                                                                                   | 6 JSON sin texto útil           |
| **RutaN GEIAL** (5 PDFs)                              | Ecosistemas de innovación LatAm                                                                            | Texto limpio (ES)               |
| ~~Defensa21 LatAm~~                                   | **Sin contenido**                                                                                          | —                               |

### F2 · `q017`–`q032` — Seguridad del entorno espacial

| Fuente                                                | Aporte                                                                                                              | Estado                                 |
| ----------------------------------------------------- | ------------------------------------------------------------------------------------------------------------------- | -------------------------------------- |
| **SWF Counterspace** (68 PDFs + 55 JSON, 17,9 M car.) | Global Counterspace Capabilities 2010–2026 — **la referencia canónica** para ASAT, láseres, RPO, guerra electrónica | Texto limpio + 3 figuras JPG con datos |
| **CSIS Aerospace** (110 PDFs + 102 JSON, 29,5 M car.) | Space Threat Assessment 2018–2026 + textos legislativos                                                             | 3 requieren OCR                        |
| **UNOOSA** (31 PDFs, 6,0 M car.)                      | Derecho espacial internacional 2021–2026 (q017)                                                                     | Multilingüe (EN/ES/AR/RU/ZH)           |
| **ESA Space Debris** (24 PDFs + 16 JSON, 7,0 M car.)  | Desechos orbitales, informes anuales (q026)                                                                         | **Limpiar bytes NUL**                  |
| **INPE** (4 PDFs + 55 JSON)                           | Perspectiva brasileña / cooperación regional                                                                        | **Portugués**                          |

### F3 · `q033`–`q050` — Dinámicas territoriales

| Fuente                                        | Aporte                                                                                                                 | Estado                             |
| --------------------------------------------- | ---------------------------------------------------------------------------------------------------------------------- | ---------------------------------- |
| **Alertas Tempranas** (363 JSON + 62 PDFs)    | Defensoría del Pueblo de Colombia. `alerta_meta` con municipio, tipo y fecha ISO — **el dato más granular del corpus** | JSON ✓ / **47 PDFs requieren OCR** |
| **MAPP-OEA** (33 PDFs, 2.183 pág, 6,2 M car.) | Informes semestrales de misión de paz. **La fuente que el set de referencia cita para q0047–q0052**                    | Texto limpio (ES/EN)               |
| **RESDAL** (105 PDFs, 23,4 M car.)            | Atlas comparado de defensa LatAm 2005–2024                                                                             | Texto limpio; JSON sin contenido   |
| **SIPRI** (74 PDFs + 52 JSON, 7,1 M car.)     | Gasto militar, transferencias de armas, tecnologías emergentes                                                         | 2 archivos son HTML                |
| **CEEEP** (80 JSON)                           | Revista peruana _Seguridad y Poder Terrestre_, con `abstract`, `doi`, `keywords`                                       | JSON limpio (ES)                   |
| **CEOBS** (17 PDFs + 19 JSON, 2,4 M car.)     | Impacto ambiental de conflictos (q035, q036)                                                                           | **1 PDF ilegible (176/180 págs)**  |
| **Amazon Underworld** (CSV + 73 PBF)          | Presencia de grupos armados georreferenciada                                                                           | **Solo 87 municipios colombianos** |
| ~~Wilson Center~~                             | **Vacío**                                                                                                              | —                                  |

---

## 12. Especificación del pipeline de ingesta

### 12.1 Orden de ejecución

```
1. Filtrar por magic bytes            → descarta los 2 HTML disfrazados
2. Ingerir los 964 JSON               → 4,35 M caracteres, texto ya limpio, coste cero
3. pdftotext -layout sobre 707 PDFs   → 137,0 M caracteres
4. Post-proceso obligatorio           → NUL, validación léxica, paginación
5. OCR selectivo sobre 51 PDFs        → Tesseract `spa` (47 de ellos son de Alertas)
6. OCR/visión sobre 1 PDF + 3 JPG     → CEOBS-Sudán y las figuras de SWF
7. CSV y XLSX como fuente estructurada aparte, NO como prosa
```

### 12.2 Reglas no negociables

| Regla                                                          | Motivo                                                   |
| -------------------------------------------------------------- | -------------------------------------------------------- |
| `pdftotext -layout` siempre                                    | ~150 documentos maquetados a dos columnas                |
| Nº de páginas desde `pdfinfo`, **nunca** contando `\f`         | 6 informes ESA inflan el conteo en +955 páginas          |
| `text.replace('\x00','')` en todo texto de PDF                 | Hasta 38.337 NUL por archivo en ESA                      |
| Validar presencia de palabras funcionales del idioma           | Detecta el caso CEOBS-Sudán (393 K caracteres de basura) |
| Clasificar OCR por **c/pág del documento completo**            | Muestrear 3 páginas produce 6 falsos positivos           |
| Discriminar escritura Unicode **antes** de heurísticas léxicas | 20 PDFs en árabe/ruso/coreano/japonés/chino              |
| Ruta completa como identificador, nunca el basename            | 47 colisiones en CSET entre documentos distintos         |
| `csv.reader` con `newline=''`, nunca `splitlines()`            | U+2028/U+2029 en 4 CSV; 8.188 saltos embebidos en otro   |
| `.replace(' ',' ')` antes de `.strip()`                        | 4.561 NBSP en 13 archivos                                |
| Preferir el CSV al XLSX cuando existan ambos                   | El XLSX corrompe los IDs a notación científica           |
| `mapbox_vector_tile.decode()` **sin** `gzip.decompress()`      | Los PBF son protobuf crudo                               |
| Descartar el campo `tags` de Atlantic Council                  | 6 valores distintos en 186 documentos                    |
| Resolver catálogo→archivo con la función de §8                 | Los nombres del catálogo no existen literalmente         |

### 12.3 Modelo de identificadores

- **Clave primaria:** el `DOC_ID` (`F{n}-{CÓDIGO}-{NNN}`) del `Inventario de Archivos`. Es la única
  clave estable, y cubre los 1.826 archivos del corpus.
- **Deduplicación:** por hash de contenido. Verificado que no hay duplicados exactos, pero sí
  solapamiento parcial entre pipelines.
- **Trazabilidad al _gold set_:** emparejar por el texto del fragmento; los IDs
  `DOC-NNNN-chunk-NNNN` no son reproducibles.

### 12.4 Chunking

- Mediana de 19 páginas por PDF con cola larga (16 documentos > 300 páginas). Un presupuesto fijo de
  chunks por documento desperdiciará los cortos y truncará los largos.
- Los 4 textos legislativos de CSIS (~3.900 páginas, 11 % del corpus) tienen baja densidad semántica.
  Despriorizar.
- Las 363 alertas son cortas (mediana 642 caracteres): **un chunk por alerta**, no trocear.
  Enriquecer cada chunk con `municipios`, `tipo` y `fecha_emision` de `alerta_meta` — es el mejor
  metadato de filtrado del corpus.
- Los 11 PDFs mixtos (§5.9) no necesitan OCR completo; solo OCR selectivo de sus páginas-imagen.

### 12.5 Validación

`FASE ORDENADA CODEFEST.xlsx` aporta **15 pares pregunta→fragmento verificados** (5 en F1, 10 en F3),
que cubren **8 de las 50 preguntas**. Muestra pequeña, pero suficiente para comprobar que el pipeline
recupera el documento correcto antes de escalar. Todas sus referencias resuelven a archivos reales
tras aplicar §8.

**Limitación conocida:** las 8 preguntas cubiertas usan una numeración distinta de la del PDF oficial
(§3.3), así que el emparejamiento debe hacerse por el **texto** de la pregunta, no por su índice.

---

## Apéndice · Comandos de verificación

```bash
CORPUS="/home/saro/ad-astra/CORPUS CODEFEST AD ASTRA 2026"

# Inventario por extensión
find "$CORPUS" -type f | sed 's/.*\.//' | tr 'A-Z' 'a-z' | sort | uniq -c | sort -rn

# Detectar archivos cuya extensión miente (encuentra los 2 HTML disfrazados de PDF)
python3 - <<'EOF'
import glob, os
for p in glob.glob(os.environ.get('CORPUS','.')+'/**/*.pdf', recursive=True):
    if not open(p,'rb').read(4).startswith(b'%PDF'):
        print('NO ES PDF:', p)
EOF

# Clasificar extraibilidad REAL (documento completo, no muestra)
find "$CORPUS" -name "*.pdf" | while read f; do
  pages=$(pdfinfo "$f" 2>/dev/null | awk '/^Pages:/{print $2}')
  chars=$(pdftotext -layout "$f" - 2>/dev/null | tr -d '\0' | tr -d '[:space:]' | wc -c)
  [ -n "$pages" ] && [ "$pages" -gt 0 ] && \
    echo "$((chars/pages)) c/pag  $pages pags  $f"
done | sort -n | head -60          # los primeros son los candidatos a OCR

# Confirmar que un PDF es escaneo (resolución y formato de imagen)
pdfimages -list -f 1 -l 2 "$CORPUS/F3_Dinamicas_Territoriales/Alertas_Tempranas/pdfs/Informes/ALERTAS_informes007.pdf"

# Detectar el fallo de glifos sin ToUnicode (CEOBS-Sudán)
pdftotext "$CORPUS/F3_Dinamicas_Territoriales/CEOBS/pdfs_full/2025/CEOBS_minamata-convention-initial-assessment-for-sudan.pdf" - | head -3

# Contar bytes NUL en los informes ESA
for f in "$CORPUS"/F2_*/ESA_Space_Debris/pdfs/SDO_Publications/*.pdf; do
  echo "$(pdftotext "$f" - | tr -cd '\0' | wc -c)  $(basename "$f")"
done

# Filas lógicas vs líneas físicas en el CSV con saltos embebidos
python3 -c "
import csv
p='$CORPUS/F1_IA_y_Capacidades_Estrategicas/AI_Index_Stanford/recursos/Healthcare_Medicine/datasets/AIINDEX_lit-covid-ai-covid-literature-csv.csv'
print('filas CSV reales:', sum(1 for _ in csv.reader(open(p,newline=''),delimiter='\t'))-1)
print('lineas fisicas  :', sum(1 for _ in open(p,'rb'))-1)"

# Verificar que los PBF son protobuf crudo (no gzip)
xxd -l 8 "$CORPUS/F3_Dinamicas_Territoriales/Amazon_Underworld/tiles/6/18/"*.pbf | head -3
#   1a xx xx ...  -> protobuf crudo   |   1f 8b ... -> gzip (NO es el caso)

# Duplicados reales por contenido (devuelve vacío: no hay ninguno)
find "$CORPUS" -name "*.pdf" -exec md5sum {} + | sort | uniq -d -w32

# Leer cualquier XLSX sin dependencias externas (un .xlsx es un ZIP de XML)
python3 -c "
import zipfile; print(zipfile.ZipFile('$CORPUS/Indice_Datos_Codefest.xlsx').namelist())"
```
