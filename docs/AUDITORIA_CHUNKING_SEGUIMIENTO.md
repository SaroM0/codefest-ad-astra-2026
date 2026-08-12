# Auditoría de seguimiento — nueva implementación de chunking

**Fecha:** 12 de agosto de 2026  
**Commit auditado:** \`530f275\` (\`ahora si :C\`)  
**Alcance:** \`src/adastra/chunking/\`, su contrato con ingesta y ejecución en memoria contra los artefactos de la corrida completa.

Este documento complementa [la auditoría inicial](AUDITORIA_CHUNKING.md). No sustituye sus recomendaciones de arquitectura: registra cuáles hallazgos fueron corregidos y cuáles persisten en la nueva implementación.

## Veredicto

**No aprobar para generar el índice final todavía.**

La implementación cambió favorablemente en aspectos de contrato y escalabilidad, pero todavía puede producir fragmentos demasiado largos, perder bloques marcados por ingesta y desasociar encabezados de su contenido. Además, no cuenta con pruebas automatizadas ni una corrida persistida de la versión actual.

## Hallazgos corregidos

| Hallazgo inicial | Estado | Evidencia |
| --- | --- | --- |
| Fenómeno convertido a \`0\` | Corregido | \`_phenomenon_number()\` normaliza \`F1\`, \`F2\`, \`F3\` a 1, 2 y 3 y falla ante un valor inválido. |
| Truncamiento destructivo de oraciones | Corregido parcialmente | Ya no existe \`_trim_words()\`; las unidades grandes se conservan completas. |
| Lectura de \`blocks_ref\` | Correcto | Sigue usando \`iter_blocks(doc, paths)\`. |
| Documentos \`structured_only\` indexados | Corregido | Se saltan antes de iterar bloques. |
| Materialización de todos los chunks | Corregido | Escribe JSONL incrementalmente mediante \`write_line()\`. |
| \`--artifacts\` leía una ruta y escribía otra | Corregido | La misma instancia de \`ArtifactPaths\` se usa como entrada y salida. |
| Resumen no válido como JSON | Corregido | Usa \`json.dumps()\`. |

## Evidencia de ejecución

La revisión ejecutó \`chunk_documents()\` en memoria sobre todos los documentos no \`structured_only\` de la ingesta existente, sin reescribir los artefactos.

| Métrica | Resultado |
| --- | ---: |
| Documentos considerados | 1.713 |
| Documentos que generaron chunks | 1.712 |
| Chunks generados | 101.341 |
| Chunks por encima de 220 tokens de la heurística actual | 6.376 |
| Chunks por encima de 250 palabras | 2.569 |
| Chunks de 10 palabras o menos | 2.775 |
| Chunks de 3 palabras o menos | 569 |
| Chunks formados solo por un heading | 115 |

Los artefactos presentes todavía pertenecen al formato anterior (\`artifacts/chunking/encoder_default/\`). La implementación nueva escribe en \`artifacts/chunking/chunks.jsonl\`, pero no había una corrida persistida de esa versión al momento de esta revisión.

## Hallazgos pendientes

### SEG-01 — el chunker no garantiza el límite de tamaño

**Severidad: alta**

El presupuesto por defecto se llama \`max_words\`, pero se aplica mediante \`_token_count()\`, una heurística que cuenta palabras y signos de puntuación. Más importante: los bloques de tipo \`heading\`, \`list_item\`, \`table_row\`, \`table_text\` y \`caption\` no pasan por \`_split_unit()\`; se emiten completos aunque superen el límite.

La ejecución generó 6.376 chunks por encima de 220 tokens heurísticos y 2.569 chunks de más de 250 palabras. Un ejemplo real de \`table_text\` tuvo 549 tokens heurísticos y más de 500 palabras.

El reto permite que retrieval divida un chunk recuperado de más de 250 palabras, pero ese componente todavía no existe. Por tanto, esta salida no puede conectarse directamente a la lista final de fragmentos sin incumplir el formato.

**Código:** [processor.py:259](../src/adastra/chunking/processor.py#L259), [processor.py:270](../src/adastra/chunking/processor.py#L270).

**Corrección requerida:**

1. Definir una política explícita para tablas y listas largas: preservar cabecera + grupos de filas, o enviarlas al flujo estructurado.
2. Separar “presupuesto de embedding” de “límite de presentación de 250 palabras”.
3. Implementar en retrieval el particionado de salida solicitado por el reto, o garantizar que todo chunk indexado puede convertirse en fragmentos válidos sin cortar oraciones.
4. Reportar y revisar toda unidad excepcionalmente larga.

### SEG-02 — detector de abreviaturas impide cortes de oración normales

**Severidad: alta**

La función considera abreviatura cualquier secuencia latina de una a tres letras seguida de punto. Esto clasifica como abreviaturas finales normales como \`is.\`, \`es.\` o \`the.\`.

Ejemplos reproducidos:

~~~text
"This is a sentence. This is another sentence."
→ una sola unidad

"El fin es. La siguiente oración debe iniciar aquí."
→ una sola unidad
~~~

El defecto acumula varias oraciones en una unidad, agrava los chunks sobredimensionados y reduce la cohesión esperada. También divide listas enumeradas de forma incorrecta: \`1. First point. 2. Second point.\` produce unidades como \`"1."\` y \`"First point. 2."\`.

**Código:** [processor.py:104](../src/adastra/chunking/processor.py#L104), [processor.py:122](../src/adastra/chunking/processor.py#L122).

**Corrección requerida:** reemplazar la regla genérica de 1–3 caracteres por un diccionario de abreviaturas contextual y por reglas para iniciales, enumeraciones y referencias. Es preferible usar un segmentador multilingüe (spaCy/ICU/Stanza) y conservar reglas locales solo para casos de corpus.

### SEG-03 — se elimina boilerplate que la ingesta decidió preservar

**Severidad: alta**

El nuevo código descarta todo bloque \`is_boilerplate\` salvo los de tipo \`heading\`. En la ingesta auditada existen:

| Tipo | Bloques descartados por esta política |
| --- | ---: |
| \`caption\` | 135.843 |
| \`paragraph\` | 2.077 |
| **Total no-heading** | **137.920** |

La ingesta marca esos bloques y documenta que no deben eliminarse universalmente: las Alertas Tempranas pueden incluir su código identificador en cabeceras o pies. La segmentación los emite como \`caption\`, precisamente el tipo que esta implementación descarta.

**Código:** [processor.py:193](../src/adastra/chunking/processor.py#L193), [segmentación de ingesta](../src/adastra/ingestion/parsers/pdf/segmentation.py#L166).

**Corrección requerida:** deduplicar boilerplate a nivel de documento, pero mantener los identificadores de alerta y otra información útil. La exclusión debe depender de la fuente, el texto y la función del bloque; no solo de \`block.type\`.

### SEG-04 — el heading se adjunta al chunk anterior, no al contenido que titula

**Severidad: media-alta**

No existe un estado de “heading pendiente”. Si un encabezado cabe en el chunk actual, se concatena al final del contenido de la sección anterior. El siguiente chunk, que contiene la nueva sección, queda sin contexto.

Reproducción con un documento mínimo y presupuesto de ocho tokens:

~~~text
Chunk 0: "Alpha beta gamma.\n\nNext section"
Chunk 1: "Delta epsilon zeta."
~~~

El comportamiento invierte la relación semántica deseada. También se encontraron 115 chunks compuestos únicamente por un heading.

**Código:** [processor.py:259](../src/adastra/chunking/processor.py#L259), [processor.py:272](../src/adastra/chunking/processor.py#L272).

**Corrección requerida:** almacenar el último heading como contexto pendiente y anteponerlo al primer chunk de contenido posterior. Cuando una sección exceda el tamaño, repetir el heading o guardar \`section_path\` como metadata en todos sus chunks.

### SEG-05 — \`num_tokens\` no corresponde a un encoder real

**Severidad: media**

\`_token_count()\` tokeniza con una expresión regular y cuenta puntuación como token. No hay encoder ni tokenizer declarado. Por eso no se puede verificar si una entrada cabe realmente en el modelo de embeddings que se seleccione.

**Código:** [processor.py:95](../src/adastra/chunking/processor.py#L95).

**Corrección requerida:** usar el tokenizer del encoder elegido y registrar \`encoder_name\` y \`tokenizer_revision\`. Si hace falta el límite del reto, conservar \`num_words\` por separado.

### SEG-06 — calidad y método de extracción siguen sin llegar a la metadata

**Severidad: media**

Aunque la ingesta proporciona calidad, base de confianza y método de extracción, \`ChunkRecord\` solo conserva bloque, tipo, página, idioma y escritura. No conserva \`quality_score\`, \`quality_basis\`, \`extraction_method\` ni \`segmentation_confidence\`.

Esto limita filtros y ponderación en retrieval. En los artefactos actuales existe un documento con confianza 0 y base \`unverified\`; la implementación no tiene una política general para evitar indexar datos así.

**Código:** [ChunkRecord](../src/adastra/chunking/processor.py#L54), [chunk_documents](../src/adastra/chunking/processor.py#L239).

### SEG-07 — se eliminaron las pruebas y no hay validación end-to-end

**Severidad: alta**

El commit elimina \`scripts/chunking/test_chunking.py\` y no existe una suite de tests de chunking. La compilación del paquete pasa, pero no hay cobertura automatizada de:

- \`blocks_ref\`;
- normalización de fenómeno;
- límites de oración;
- headings;
- boilerplate;
- tablas largas;
- \`structured_only\`;
- rutas \`--artifacts\`;
- salida JSONL y resumen.

Además, no había salida generada por la implementación actual: los artefactos existentes corresponden al layout anterior con \`encoder_default\`.

**Corrección requerida:** crear pruebas aisladas con \`tmp_path\` que no escriban en \`artifacts/\` del repositorio, y añadir una prueba de integración de muestra que valide el JSONL final.

## Observaciones adicionales

- La escritura incremental es una mejora correcta, pero abre directamente los destinos con modo \`"w"\`. Un fallo a mitad de corrida deja un artefacto parcial. Se recomiendan archivos temporales y reemplazo atómico.
- \`chunks.jsonl\` y \`metadata.jsonl\` contienen el mismo objeto completo. Si no existe un consumidor que necesite ambos formatos, deben consolidarse para evitar duplicación.
- El parámetro \`min_words\` se recibe y se elimina explícitamente; todavía no cumple ninguna función de agrupación de chunks cortos.

## Prioridad de corrección

### P0 — requerida antes de indexar

1. Corregir la segmentación de oración y agregar tests de regresión para \`is.\`, \`es.\`, abreviaturas y listas.
2. Definir tratamiento de tablas/listas largas y garantizar cumplimiento de 250 palabras en la salida final.
3. Corregir la política de boilerplate para preservar códigos y datos de trazabilidad.
4. Restaurar una suite automatizada y ejecutar una corrida de muestra persistida.

### P1 — calidad de recuperación

1. Asociar headings con el contenido posterior.
2. Integrar tokenizer real del encoder.
3. Propagar calidad, método de extracción y confianza.
4. Implementar escritura atómica.

## Conclusión

La nueva implementación es un avance claro respecto de la primera: ya es streaming, respeta \`structured_only\`, normaliza fenómeno y no trunca texto. Aun así, los tres problemas principales —límites de tamaño, segmentación de oraciones y borrado de boilerplate— alteran directamente la calidad, cobertura y conformidad de los fragmentos. Deben resolverse antes de considerar terminado el chunking.

