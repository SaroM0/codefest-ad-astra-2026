# Reporte de fallo de chunking y propuesta de corrección

**Fecha:** 12 de agosto de 2026  
**Alcance:** ejecución en memoria del chunker actual contra todos los artefactos normalizados de ingesta.  
**Artefactos analizados:** `artifacts/ingestion/documents/`

## Resumen ejecutivo

El componente de chunking puede leer y transformar los documentos normalizados, incluidos los documentos cuyos bloques viven en archivos externos (`blocks_ref`). Sin embargo, **no garantiza el límite configurado de 220 tokens heurísticos por chunk**.

En la corrida completa se generaron **136.945 chunks**; **1.109** excedieron el límite. El caso más grande alcanzó **5.011 tokens heurísticos**:

| Campo | Valor |
| --- | --- |
| Documento | `F2-SWF-034` |
| Chunk | `F2-SWF-034-chunk-0041` |
| Tamaño | 5.011 tokens heurísticos |
| Página | 6 |
| Tipos de bloque | `heading`, `paragraph` |

Este comportamiento es incompatible con un presupuesto fijo de embeddings y puede impedir la indexación, aumentar costos o causar que retrieval tenga que truncar evidencia.

## Datos de la ejecución

La corrida no escribió ni modificó `artifacts/chunking/`; se ejecutó el generador en memoria.

| Métrica | Resultado |
| --- | ---: |
| Documentos canónicos revisados | 1.731 |
| Documentos `structured_only` excluidos | 18 |
| Documentos que produjeron chunks | 1.712 |
| Documentos sin contenido chunkable | 1 |
| Chunks generados | 136.945 |
| Chunks mayores de 220 tokens heurísticos | 1.109 |
| Chunks sin `quality_score` o `quality_basis` | 0 |
| Documentos con `blocks_ref` | 141 |
| Tiempo de ejecución | 43,47 s |

La entrada normalizada cubre los tres fenómenos y los formatos PDF, JSON, CSV, XLSX, JPEG y texto plano. La lectura de bloques externos funcionó correctamente, por lo que el problema no está en el contrato de entrada sino en la estrategia de fragmentación.

## Causa técnica

La función `_split_unit()` en [`src/adastra/chunking/processor.py`](../src/adastra/chunking/processor.py) intenta dividir un bloque por párrafos y después por oraciones. Si no encuentra más de una oración, conserva el bloque completo:

```python
sentences = _split_sentences(text)
if len(sentences) == 1:
    return [text.strip()], 1
```

Textos tabulares, filas largas, listas, URLs, fragmentos de PDF con orden de lectura pobre y prosa sin puntuación pueden caer en esta ruta. El contador `oversize_units` detecta parte del problema, pero no evita que el chunk sobredimensionado se emita.

Existe además un caso de borde con encabezados: aunque el código calcula el presupuesto del heading pendiente, este presupuesto no participa en la decisión de si una unidad cabe antes de agregarla. Por ello un heading puede hacer que un chunk, que ya estaba en el límite, supere `max_words`.

## Impacto

- El tamaño de entrada del modelo de embeddings no queda garantizado.
- Un chunk muy largo puede fallar al vectorizarse o ser truncado sin evidencia del contenido descartado.
- La recuperación puede devolver texto demasiado largo para el límite de presentación de 250 palabras.
- Los títulos de sección pueden amplificar los excesos si se añaden sin descontarlos del presupuesto.
- `num_tokens` es una estimación basada en regex; no representa necesariamente los tokens del tokenizer del encoder elegido.

## Solución propuesta

### 1. Garantizar un límite duro

Extender `_split_unit()` con una última estrategia de división. La política recomendada es:

| Tipo de contenido | División preferida | Fallback obligatorio |
| --- | --- | --- |
| Prosa | Párrafos y oraciones | Palabras/tokens |
| Listas | Ítems completos | Palabras/tokens dentro del ítem |
| Tablas | Filas o grupos de filas | Columnas/texto por tokens |
| Texto de página | Oraciones | Palabras/tokens |
| URL o unidad excepcional | Mantener si cabe | Cortar por tokens y registrar la razón |

El fallback debe devolver fragmentos de como máximo `max_words`. Si se implementa solapamiento para mejorar contexto, el solapamiento también debe contar dentro del límite.

```python
if len(sentences) == 1 and _token_count(text) > max_words:
    return _split_by_words(text, max_words), 1
```

Para tablas, conviene añadir una ruta explícita que agrupe `table_row` y conserve una cabecera cuando sea necesaria; no debe depender únicamente de puntuación.

### 2. Contabilizar el heading antes de insertar contenido

Antes de agregar una unidad, calcular:

```python
required = current_words + heading_budget + unit_words
```

Si `required > max_words`, se debe emitir el chunk actual o decidir una política explícita para el heading: emitirlo como chunk independiente, guardarlo como metadato de sección, o repetirlo en texto siempre descontándolo del presupuesto. Se recomienda guardar además `section_heading` y repetir el heading en `texto` solo cuando cabe.

### 3. Usar el tokenizer real del encoder

Reemplazar o complementar `_token_count()` con el tokenizer del modelo de embeddings elegido. Mantener dos métricas distintas:

- `embedding_tokens`: presupuesto técnico del encoder.
- `word_count`: límite de presentación de retrieval (por ejemplo, 250 palabras).

No deben tratarse como equivalentes.

### 4. Registrar la estrategia y excepciones

Añadir campos de trazabilidad a `ChunkRecord`, por ejemplo:

```python
split_strategy: str  # sentence, paragraph, table_rows, hard_token_split
oversize_reason: str | None
section_heading: str | None
```

El resumen de chunking debe incluir cantidades por estrategia y verificar que no quedan chunks por encima del presupuesto, salvo una excepción explícita autorizada.

### 5. Reforzar las pruebas

Actualizar `tests/chunking/test_processor.py` para usar un `DocumentQuality` real en vez de `MagicMock`. Añadir pruebas para un bloque de miles de tokens sin puntuación, tablas y listas largas, heading más contenido en el límite, documentos con `blocks_ref`, exclusión de `structured_only` y la propagación de calidad.

La invariante principal debe ser: todo chunk final cumple el límite del tokenizer y el límite de palabras de salida, o declara una excepción verificable.

## Criterio de aceptación

La corrección se considera aprobada cuando una corrida completa:

1. procesa los 1.713 documentos indexables sin error;
2. conserva la lectura de los 141 documentos con `blocks_ref`;
3. genera chunks con calidad y procedencia completas;
4. deja **cero chunks** por encima del presupuesto del encoder, salvo excepciones explícitas documentadas y contadas;
5. publica un `summary.json` con métricas de tamaño, estrategias de división y excepciones; y
6. pasa pruebas unitarias y una prueba de integración con artefactos reales de muestra.
