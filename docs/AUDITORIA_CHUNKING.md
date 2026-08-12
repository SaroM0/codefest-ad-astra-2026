# Auditoría de chunking — CODEFEST AD ASTRA 2026

**Estado:** no apto para indexar o entregar en su estado actual.  
**Alcance:** implementación de chunking, integración con ingesta y salida de la última corrida completa.  
**Fecha:** 11 de agosto de 2026.

Este documento contrasta la implementación con el [enunciado del reto](CODEFEST_2026-1.pdf), en particular la sección 3 (chunking y metadata) y la sección 9 (límite de 250 palabras).

## Veredicto ejecutivo

El componente usa correctamente [iter_documents e iter_blocks](../src/adastra/core/documents.py), por lo que sí consume tanto bloques inline como los documentos grandes referenciados mediante "blocks_ref". Se verificaron 141 documentos con bloques externalizados.

Aun así, el chunker **no es apto para retrieval**: incumple metadata obligatoria, trunca contenido, ignora decisiones que ya tomó la ingesta y produce fragmentos demasiado pequeños y sin contexto.

| Severidad | Hallazgos |
| --- | --- |
| Bloqueante | Fenómeno inválido; corte destructivo de oraciones largas |
| Alta | Ignora "structured_only" y señales de ingesta; fragmentación por bloque; no escala; rutas inconsistentes |
| Media | Segmentación multilingüe frágil; conteo de tokens erróneo; reporte y prueba inseguros |

## Evidencia de la corrida auditada

| Métrica | Resultado |
| --- | ---: |
| Documentos canónicos | 1.731 |
| Bloques reales leídos | 1.084.350 |
| Chunks escritos | 1.089.761 |
| Chunks de 3 palabras o menos | 398.582 (36,6 %) |
| Chunks de 10 palabras o menos | 598.137 (54,9 %) |
| Chunks de 50 palabras o menos | 847.750 (77,8 %) |
| Chunks sin puntuación final ".?!" | 920.997 (84,5 %) |
| Unidades de más de 250 palabras | 654 |
| De las anteriores sin terminador esperado | 406 |

Los JSONL derivados se ubican en "artifacts/chunking/encoder_default/". Deben regenerarse una vez se corrija la implementación.

## Hallazgos detallados

### CHK-01 — "fenomeno" vale 0 en todos los chunks reales

**Severidad: bloqueante**

El reto exige un entero 1, 2 o 3. La ingesta persiste "F1", "F2" o "F3"; el chunker intenta convertirlo directamente con "int(...)" y, cuando falla, utiliza 0 como fallback. Los 1.089.761 chunks reales quedaron con "fenomeno: 0".

**Impacto:** incumple la metadata obligatoria e inutiliza los filtros temáticos.

**Ubicación:** [processor.py:67-70](../src/adastra/chunking/processor.py#L67-L70).

**Corrección:** normalizar explícitamente "F1" → 1 y fallar ante cualquier valor desconocido. Un campo obligatorio nunca debe degradarse a un valor fuera del esquema.

### CHK-02 — trunca oraciones largas y destruye texto

**Severidad: bloqueante**

Cuando una unidad no cabe en "max_words", el código aplica "_trim_words()" y conserva solo el prefijo. La corrida tiene 654 unidades de más de 250 palabras; 406 ni siquiera finalizan en ".?!". Se pierde el resto del texto sin registro.

Esto viola el requisito de completitud lingüística y el requisito de conservar el texto original.

**Ubicación:** [processor.py:93-98](../src/adastra/chunking/processor.py#L93-L98).

**Corrección:**

1. No cortar dentro de una oración.
2. Preservar completa una oración excepcionalmente larga y marcarla como excepción.
3. Para tablas, listas o layout no-prosa, aplicar una política específica: agrupar filas con cabecera o enviar a revisión. Nunca truncar.
4. Validar cobertura: todo bloque indexable debe aparecer íntegro en uno o más chunks, salvo exclusiones registradas.

### CHK-03 — ignora clasificación, calidad y segmentación de ingesta

**Severidad: alta**

La ingesta entrega "indexing_hint", calidad, "is_boilerplate", "segmentation_confidence", tipo de bloque, página y método de extracción. El chunker prácticamente ignora estas señales.

- Indexa 18 documentos "structured_only", con al menos 260.168 bloques de texto. El contrato del paquete indica que estos datos deben filtrarse y agregarse, no embebirse fila por fila.
- Indexa 147.472 bloques marcados como boilerplate.
- No transporta calidad ni confianza; retrieval no puede rebajar OCR o segmentación insegura.
- No aprovecha los tipos "heading", "paragraph", "list_item", "table_row" ni "caption".

**Ubicación:** [processor.py:59-75](../src/adastra/chunking/processor.py#L59-L75) y [contrato del paquete](../src/adastra/chunking/__init__.py).

**Corrección:** excluir "structured_only" antes de iterar, definir una política explícita para boilerplate, y propagar confianza, página, bloque y método de extracción a cada chunk.

### CHK-04 — un chunk por bloque produce contexto pobre

**Severidad: alta**

El acumulador se reinicia por cada ContentBlock. Títulos, viñetas, captions y celdas de tabla acaban como chunks independientes. En la salida aparecen fragmentos como "Artificial Intelligence", "Index Report 2024" y "CHAPTER 1:".

La proporción de chunks minúsculos confirma que no se representan ideas o argumentos cohesivos: 54,9 % tiene diez palabras o menos.

**Corrección:**

- Mantener headings como contexto jerárquico del texto posterior.
- Acumular párrafos consecutivos de la misma sección hasta el presupuesto de tokens.
- Agrupar listas relacionadas, salvo que cada viñeta sea autosuficiente.
- Para tablas, conservar título/cabecera y grupos de filas relacionados, o encaminar al recuperador estructurado.
- Aplicar solapamiento solo entre ventanas de prosa consecutivas de una misma sección.

### CHK-05 — el separador de oraciones no cubre el corpus multilingüe

**Severidad: media**

La expresión regular solo reconoce ".?!" seguidos de mayúscula latina. Rompe abreviaturas como "Dr.", listas como "1.", saltos seguidos de minúscula y puntuación de chino, árabe, ruso, japonés o coreano. La ingesta documenta ocho idiomas.

Se detectaron 31.087 casos donde el primer resultado de la regla contiene tres palabras o menos; entre los ejemplos reales están "1.", "2." y "models.".

**Ubicación:** [processor.py:43-52](../src/adastra/chunking/processor.py#L43-L52).

**Corrección:** usar segmentación multilingüe y sumar reglas de excepción para abreviaturas, citas y numeración. La estrategia debe considerar idioma y escritura dominante.

### CHK-06 — materializa el corpus completo y duplica la salida

**Severidad: alta**

"write_chunks()" crea una lista de todos los chunks antes de escribir. Con 1,09 millones de registros consume memoria innecesariamente y contradice la interfaz streaming de ingesta. Después serializa la lista dos veces: "chunks.jsonl" y "metadata.jsonl", ambos de unos 581 MB y con contenido equivalente.

**Ubicación:** [processor.py:148-150](../src/adastra/chunking/processor.py#L148-L150).

**Corrección:** emitir JSONL incrementalmente; si se requieren dos archivos, escribir ambos al mismo tiempo sin materializar toda la colección. Usar archivos temporales y reemplazo atómico al completar.

### CHK-07 — "--artifacts" puede leer una corrida y escribir en otra

**Severidad: alta**

La CLI acepta "--artifacts", pero "write_chunks()" crea "ArtifactPaths()" sin ese argumento. La entrada se lee desde "ADASTRA_ARTIFACTS" o el directorio por defecto, mientras la salida se escribe bajo la ruta indicada. Es posible indexar una corrida vieja y publicarla como otra.

**Ubicación:** [processor.py:138-146](../src/adastra/chunking/processor.py#L138-L146) y [__main__.py:18-23](../src/adastra/chunking/__main__.py#L18-L23).

**Corrección:** crear una sola instancia "ArtifactPaths(Path(out_root))" para entrada y salida; validar la existencia de "ingestion/documents/" y registrar la versión de ingesta consumida.

### CHK-08 — "num_tokens" cuenta palabras, no tokens

**Severidad: media**

La implementación usa "len(text.split())". Esto no equivale a los tokens del encoder y puede incumplir su longitud máxima de entrada. El campo obligatorio se persiste con un significado incorrecto.

**Ubicación:** [processor.py:32-33](../src/adastra/chunking/processor.py#L32-L33).

**Corrección:** contar con el tokenizer del encoder seleccionado, por ejemplo "transformers.AutoTokenizer", y guardar el nombre y revisión del tokenizer en el manifiesto. Para el límite de presentación del reto, usar un campo separado como "num_words".

### CHK-09 — se pierde trazabilidad útil

**Severidad: media**

"fuente" conserva correctamente la ruta relativa original, suficiente para el mínimo del reto. Pero no se propagan URL de fuente cuando existe, observatorio, página o rango de páginas, IDs/tipos de bloque, método de extracción ni calidad.

Esto limita citas y depuración, especialmente para PDFs, OCR y tablas.

### CHK-10 — reporte inválido y prueba que modifica artefactos reales

**Severidad: media**

El reporte se escribe con "str(dict)", que no es JSON válido. La prueba de humo crea "TEST-0001" en "artifacts/ingestion/" y ejecuta el chunker sobre el corpus completo: puede contaminar resultados y sobrescribir una salida real.

**Ubicación:** [processor.py:151-154](../src/adastra/chunking/processor.py#L151-L154) y [test_chunking.py:13-60](../scripts/chunking/test_chunking.py#L13-L60).

**Corrección:** usar "json.dumps()" y mover fixtures a un directorio temporal. Las pruebas no deben escribir en "artifacts/" del proyecto.

## Alternativas de implementación

### Opción recomendada: chunker propio, estructural y streaming

Esta es la opción recomendada. La ingesta ya resolvió orden de lectura, bloques, tablas, encabezados, idioma, OCR, calidad y procedencia. Reemplazarla por un cargador genérico duplicaría trabajo y perdería trazabilidad.

~~~text
CanonicalDocument
  → filtro por indexing_hint y calidad
  → agrupación estructural por sección y tipo de bloque
  → segmentación de oraciones por idioma
  → ventanas dentro del límite de tokens del encoder
  → validación de texto, metadata e IDs
  → JSONL incremental y manifiesto
~~~

Esta opción ofrece el mejor control de contrato, reproducibilidad y memoria para el corpus heterogéneo.

### LangChain "langchain-text-splitters"

LangChain ofrece "RecursiveCharacterTextSplitter", splitters por tokens y splitters estructurales para HTML, Markdown y JSON. La [documentación oficial](https://docs.langchain.com/oss/python/integrations/splitters/index) recomienda el splitter recursivo como baseline general y destaca preservar la estructura documental.

**Cuándo usarlo:** como baseline rápido después de agrupar los bloques propios en unidades de prosa y conservar manualmente la metadata de ingesta.

**Precauciones:**

- No debe recibir corpus crudo ni sustituir "iter_blocks()".
- La función de longitud debe usar el tokenizer del encoder.
- Debe pasar por un validador de límites de oración y cobertura de texto.
- El splitter recursivo por caracteres no entiende tablas ni garantiza por sí mismo los requisitos del reto.
- Los splitters de cabeceras HTML/Markdown solo aplican donde exista esa estructura; en PDFs de este proyecto la estructura confiable ya está en ContentBlock.

### LangGraph: sirve para orquestar, no para chunkear

LangGraph **no es un paquete de chunkers**. Es un framework de orquestación de flujos y agentes con estado, persistencia y revisión humana ([documentación oficial](https://langchain-ai.github.io/langgraph/index.html)).

Podría servir para:

- reanudar el proceso después de fallos;
- enviar casos de OCR, tablas o baja confianza a revisión humana;
- ejecutar configuraciones experimentales y registrar resultados;
- coordinar ingesta → chunking → embeddings → evaluación.

No es necesario para el algoritmo de chunking. Un proceso Python determinista, con manifiestos y checkpoints, es más simple y fácil de auditar. Si se adopta LangGraph, debe **envolver** el chunker determinista; no decidir cortes mediante un LLM.

### Segmentación de oraciones: spaCy, Stanza o ICU

| Opción | Ventaja | Consideración |
| --- | --- | --- |
| spaCy Sentencizer | Ligero y configurable; maneja puntuación Unicode, incluido "。" | Añadir reglas para abreviaturas y referencias. [Docs](https://spacy.io/api/sentencizer) |
| spaCy SentenceRecognizer/modelos por idioma | Fronteras aprendidas para prosa | Más pesado; evaluar cobertura de los ocho idiomas. [Docs](https://spacy.io/api/sentencerecognizer) |
| ICU BreakIterator (PyICU) | Segmentación Unicode multilingüe madura | Dependencia nativa; validar empaquetado |
| Stanza | Pipeline multilingüe entrenado | Mayor costo de modelos y ejecución |

Una opción pragmática es spaCy/ICU para la frontera inicial, más reglas de dominio para "Dr.", "et al.", "Fig." y numeración, junto con una política separada para tablas.

### Unstructured, LlamaIndex y chunking semántico

- **Unstructured:** útil si todavía falta extracción y detección de elementos. Aquí puede ser un experimento para PDFs o tablas difíciles, pero no debe reemplazar la ingesta existente.
- **LlamaIndex:** sus divisores por oración, tokens y semántica sirven como baseline; deben adaptarse al contrato CanonicalDocument y no reemplazar metadata o validaciones.
- **Chunking semántico basado en embeddings:** puede detectar cambios de tema, pero sobre más de un millón de bloques aumenta costo y tiempo. Probarlo solo sobre un subconjunto representativo, después de un baseline estructural correcto, y decidir con métricas.

## Diseño objetivo

### Política de datos

1. Excluir "structured_only" de la ruta vectorial y reservarlo para filtros/agregaciones estructuradas.
2. Omitir boilerplate por defecto; conservar únicamente el que aporte identidad y deduplicarlo por documento.
3. No descartar baja calidad en silencio: registrar el motivo y decidir explícitamente excluir o ponderar.
4. Preservar ruta original, URL cuando exista, fenómeno, idioma, páginas, bloques origen, método de extracción y calidad.

### Política de tamaño

- Definir el presupuesto de índice según el tokenizer y la longitud máxima del encoder.
- Respetar el máximo de 250 **palabras** en la presentación de retrieval.
- Iniciar con un solapamiento de 10–20 % solo entre prosa consecutiva de la misma sección; ajustar mediante evaluación.
- No truncar nunca una oración o fila que exceda el presupuesto; registrarla y aplicarle una política específica.

### Metadata adicional recomendada

~~~json
{
  "source_url": "… o null",
  "observatory_code": "…",
  "language": "… o null",
  "page_start": 12,
  "page_end": 13,
  "block_ids": ["…"],
  "block_types": ["heading", "paragraph"],
  "section_path": ["Capítulo 2", "Resultados"],
  "quality_score": 0.92,
  "quality_basis": "title_match",
  "tokenizer_name": "…",
  "pipeline_version": "…"
}
~~~

## Plan de corrección

### P0 — antes de regenerar el índice

1. Normalizar y validar fenómeno.
2. Eliminar truncamientos y validar cobertura de texto.
3. Corregir el uso coherente de "--artifacts".
4. Escribir en streaming y de forma atómica.
5. Aislar fixtures en temporales y corregir el JSON del reporte.

### P1 — mejorar retrieval

1. Aplicar las políticas de "structured_only", boilerplate y calidad.
2. Agrupar por sección, párrafo, lista y tabla usando ContentBlock.
3. Reemplazar el regex por segmentación multilingüe.
4. Contar tokens con el tokenizer del encoder.
5. Propagar trazabilidad de página, bloque, fuente y calidad.

### P2 — experimentación controlada

1. Comparar el baseline estructural con LangChain recursivo/tokenizado y, si aporta, semantic chunking.
2. Variar tamaño, solapamiento y tratamiento de tablas sobre un conjunto fijo.
3. Elegir por NDCG@10, F1@3, tasa de chunks válidos, memoria y tiempo; no por intuición.

## Criterios de aceptación y pruebas

- "fenomeno" debe pertenecer a {1, 2, 3} en el 100 % de chunks.
- Todos los campos obligatorios deben estar presentes y tipados correctamente.
- "num_tokens" debe coincidir con el tokenizer declarado.
- No puede perderse texto indexable, salvo exclusiones explícitas y reportadas.
- Cero cortes dentro de oración y ningún chunk vacío.
- IDs únicos y posiciones consecutivas por documento.
- Cero documentos "structured_only" en el JSONL vectorial.
- Pruebas de boilerplate, calidad y "blocks_ref".
- Prueba de ruta no predeterminada mediante "--artifacts".
- Fixtures de español, inglés, portugués, chino, árabe, ruso, coreano y japonés; además de abreviaturas, listas, tablas y oraciones largas.
- Prueba de escritura streaming con fixture grande y reporte JSON parseable.

## Conclusión

La ingesta ya ofrece la base correcta para la siguiente etapa. La prioridad no es añadir un agente ni reemplazar la ingesta: es implementar un chunker estructural, determinista, multilingüe y validado que aproveche ese contrato. LangChain puede acelerar un baseline y LangGraph puede orquestar ejecuciones complejas, pero ninguno reemplaza la trazabilidad, la completitud lingüística ni la metadata exigida por el reto.

