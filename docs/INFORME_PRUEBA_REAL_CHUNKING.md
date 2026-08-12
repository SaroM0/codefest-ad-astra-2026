# Informe de prueba real de chunking

**Fecha:** 12 de agosto de 2026  
**Versión auditada:** commit 58bbef0  
**Alcance:** ejecución de la CLI actual contra los artefactos reales de ingesta, inspección de documentos reales y pasada diagnóstica en memoria.

Este documento registra una prueba de ejecución, no solo una revisión estática. Complementa [la auditoría de seguimiento](AUDITORIA_CHUNKING_SEGUIMIENTO.md).

## Resumen ejecutivo

**Resultado: fallido. No es posible generar el índice de chunks con la implementación actual.**

La prueba real termina antes de emitir el primer chunk por una incompatibilidad entre el chunker y el modelo de calidad que produce la ingesta. Una pasada diagnóstica controlada, que adaptó solamente esa interfaz en memoria y no escribió artefactos, confirmó que tras corregir el bloqueo aún permanecen problemas de límite, encabezados y cobertura.

| Área | Resultado |
| --- | --- |
| Ejecución real de la CLI | Falla al primer documento |
| Lectura de ingesta real | Alcanzada; falla al convertir el primer chunk |
| Escritura final de JSONL | No se produce |
| Pruebas automatizadas | No ejecutables: falta pytest |
| Límite interno de 220 | No garantizado |
| Máximo de 250 palabras para salida | No garantizado |

## Método de prueba

### Ejecución real

Se ejecutó la implementación sin modificar el código ni los documentos:

~~~bash
.venv/bin/python -m adastra.chunking --artifacts artifacts --limit 3
~~~

Resultado:

~~~text
exit=2
'DocumentQuality' object has no attribute 'overall_score'
~~~

La ejecución creó archivos temporales de cero bytes, que fueron retirados al finalizar la prueba. No se sobrescribieron los artefactos previos.

### Pasada diagnóstica controlada

Para explorar los problemas que quedan después del error bloqueante, se reutilizaron los mismos CanonicalDocument reales. Solo en memoria se expuso un adaptador con los valores existentes de:

~~~text
doc.quality.confidence.score
doc.quality.confidence.basis
~~~

No se modificó el código fuente, ningún documento de ingesta ni la salida de chunking. Esta pasada **no constituye una ejecución válida**: permite observar el comportamiento posterior que actualmente permanece inaccesible por la regresión de calidad.

## Hallazgos

### REAL-01 — la CLI no puede procesar ningún documento real

**Severidad: bloqueante**

El primer documento de la corrida, F1-AIINDEX-001, contiene una calidad válida de ingesta:

~~~json
{
  "confidence": {
    "score": 0.9312,
    "basis": "title_match"
  },
  "usable": true
}
~~~

Pero el chunker intenta leer campos que no existen:

~~~python
q_score = doc.quality.overall_score
q_basis = doc.quality.basis
~~~

El contrato real define los campos bajo doc.quality.confidence. Por ello se produce:

~~~text
AttributeError: 'DocumentQuality' object has no attribute 'overall_score'
~~~

**Impacto:** la etapa falla antes del primer chunk, la escritura temporal queda vacía y no hay salida consumible por embeddings.

**Código afectado:** [processor.py:231](../src/adastra/chunking/processor.py#L231), [modelo de calidad](../src/adastra/core/models/quality.py#L62).

**Corrección requerida:**

~~~python
quality_score = doc.quality.confidence.score
quality_basis = doc.quality.confidence.basis
~~~

La prueba debe construir un DocumentQuality real; un MagicMock no valida el contrato entre etapas.

### REAL-02 — hay chunks reales que exceden el presupuesto interno y el límite de salida

**Severidad: alta**

En la pasada diagnóstica con documentos reales se observaron chunks por encima de 220 tokens heurísticos y, en varios casos, por encima de las 250 palabras permitidas para los fragmentos retornados.

| Documento real | Chunks | num_tokens > 220 | Texto >250 palabras |
| --- | ---: | ---: | ---: |
| F1-AIINDEX-001 | 110 | 1 | 0 detectado en esta muestra |
| F1-AIINDEX-004 | 231 | 1 | 1 |
| F2-CSIS-201 | 6.233 | 92 | 8 |
| F3-RESDAL-062 | 43 | 1 | 0 detectado en esta muestra |
| F1-CENIA-015 | 14 | 0 | 0 detectado en esta muestra |

Ejemplo real de F1-AIINDEX-004:

~~~text
chunk_id: F1-AIINDEX-004-chunk-0076
num_tokens: 459
palabras: 322
inicio: "4.2 Jobs ... India ... Ireland ... Israel ... Italy ..."
~~~

Este contenido procede de texto tabular/layout. El algoritmo intenta fragmentar todos los bloques por límites de oración, pero una tabla no necesariamente contiene oraciones. Cuando el divisor no encuentra una frontera, la unidad se conserva completa.

**Impacto:** el chunker no garantiza su propio presupuesto ni el máximo de 250 palabras que retrieval debe cumplir al entregar resultados.

**Código afectado:** [processor.py:158](../src/adastra/chunking/processor.py#L158), [processor.py:169](../src/adastra/chunking/processor.py#L169), [processor.py:303](../src/adastra/chunking/processor.py#L303).

**Punto de mejora:** definir una política por tipo:

- prosa: dividir solo en límites oracionales válidos;
- listas: agrupar ítems completos;
- tablas: preservar título/cabecera y dividir en grupos de filas;
- unidad excepcionalmente larga: registrarla y garantizar que retrieval pueda presentarla sin cortar frases.

El presupuesto de embeddings y el máximo de 250 palabras de salida son restricciones distintas y deben validarse por separado.

### REAL-03 — el título de sección puede hacer que un chunk exceda el límite

**Severidad: alta**

El encabezado se agrega después de decidir si el bloque de contenido cabe. Por tanto, el cálculo no reserva espacio para el heading.

Reproducción controlada del comportamiento real:

~~~text
max_words = 5
heading: "One Two"           → 2 tokens
párrafo: "a b c d e"         → 5 tokens

chunk producido: 7 tokens
"One Two

a b c d e"
~~~

**Código afectado:** [processor.py:313](../src/adastra/chunking/processor.py#L313), [processor.py:330](../src/adastra/chunking/processor.py#L330).

**Punto de mejora:** calcular la capacidad incluyendo el heading pendiente. Si no cabe junto al primer bloque, conservarlo como metadata section_path o diseñar una excepción explícita y medible.

### REAL-04 — se pierden headings terminales de documentos reales

**Severidad: alta**

Si un documento termina en un bloque heading, el bloque se guarda como pending_heading y nunca se emite, porque no llega un bloque de contenido posterior.

Una exploración de todos los documentos ingeridos halló:

- **92.382** headings fuente;
- **62 documentos** cuyo último bloque indexable es un heading.

Ejemplos reales que se perderían:

| Documento | Último heading |
| --- | --- |
| F1-CENIA-015 | Conclusions |
| F1-CENIA-013 | Galería |
| F1-CENIA-018 | Centro Nacional de Inteligencia Artificial |
| F1-AIINDEX-053 | T 650.725.4537 F 650.123.4567 E HAI-Policy@stanford.edu hai.stanford.edu |

No todos los headings terminales representan evidencia recuperable, pero descartarlos sin política ni reporte es pérdida silenciosa de contenido.

**Código afectado:** [processor.py:278](../src/adastra/chunking/processor.py#L278), [processor.py:349](../src/adastra/chunking/processor.py#L349).

**Punto de mejora:** al terminar el documento, emitir el heading pendiente como chunk o registrarlo explícitamente como contenido no indexado con una razón. El comportamiento debe decidirse según tipo y utilidad, no por accidente del control de flujo.

### REAL-05 — un mismo heading se repite en varios chunks

**Severidad: media**

La variable pending_heading no se reinicia después de ser incorporada. Cuando una sección genera varios chunks, el mismo heading se vuelve a anteponer a cada uno.

En F1-AIINDEX-001, la pasada diagnóstica obtuvo:

- 110 chunks;
- 23 IDs de heading repetidos en más de un chunk.

Repetir el heading como contexto puede ser una decisión válida, pero debe ser intencional y contabilizada: aumenta el volumen indexado y puede sesgar la recuperación hacia títulos repetidos. Hoy ocurre por estado residual, y además contribuye a los excesos de tamaño.

**Código afectado:** [processor.py:300](../src/adastra/chunking/processor.py#L300), [processor.py:330](../src/adastra/chunking/processor.py#L330).

**Punto de mejora:** elegir una de estas políticas y probarla:

1. heading solo en el primer chunk de la sección;
2. heading como metadata de todos los chunks;
3. heading repetido en texto, descontando su presupuesto de tokens.

### REAL-06 — segmentación mejorada, pero aún falla con abreviaturas compuestas

**Severidad: media**

La corrección separa correctamente casos como:

~~~text
"El fin es. La siguiente oración..."
→ ["El fin es.", "La siguiente oración..."]
~~~

Sin embargo, aún divide una abreviatura compuesta:

~~~text
"The U.S. has data. Next sentence."
→ ["The U.S.", "has data.", "Next sentence."]
~~~

Esto puede fragmentar evidencia a mitad de una idea. El corpus incluye documentos en inglés con referencias, siglas, iniciales y bibliografía, por lo que el caso no es puramente sintético.

**Código afectado:** [processor.py:100](../src/adastra/chunking/processor.py#L100).

**Punto de mejora:** cubrir siglas con puntos como U.S., U.K. y E.U., referencias bibliográficas y abreviaturas multilingües. Un segmentador Unicode/multilingüe con reglas de dominio será más seguro que ampliar indefinidamente el regex.

### REAL-07 — las pruebas no se pueden ejecutar y ocultan el fallo principal

**Severidad: alta**

Existe tests/chunking/test_processor.py, pero:

- pytest no está instalado en el entorno;
- pytest no figura como dependencia de desarrollo en pyproject.toml;
- al ejecutar python -m pytest -q, el resultado es:

~~~text
No module named pytest
~~~

Además, la prueba de chunking usa MagicMock con atributos overall_score y basis, que no existen en DocumentQuality. Por eso la prueba pasa por alto exactamente la regresión que bloquea la ejecución real.

**Código afectado:** [test_processor.py:43](../tests/chunking/test_processor.py#L43), [modelo real](../src/adastra/core/models/quality.py#L62).

**Punto de mejora:** agregar dependencias de test, configurar su ejecución y sustituir mocks de contrato por modelos Pydantic reales. Añadir una prueba de integración sobre artefactos de muestra que incluya un documento inline y otro con blocks_ref.

## Aspectos que sí funcionan o mejoraron

- Se conserva el acceso a bloques mediante iter_blocks, incluyendo documentos externalizados.
- structured_only se filtra antes de generar chunks.
- Se preservan captions boilerplate; ya no se elimina todo boilerplate por tipo.
- La escritura usa temporales antes de reemplazar el JSONL final.
- La normalización F1/F2/F3 a 1/2/3 sigue siendo correcta.
- Los campos de método de extracción y confianza de segmentación fueron añadidos al registro, aunque la ejecución se bloquee antes de persistirlos.

## Meta que debe alcanzar el chunking

El chunking debe transformar **todo documento indexable previamente ingerido** en chunks deterministas, completos, trazables y aptos para embeddings y retrieval. Cada chunk debe:

1. conservar el contenido sin truncar ni cortar oraciones;
2. respetar el presupuesto real del tokenizer del encoder, o declarar una excepción verificable;
3. poder convertirse en un fragmento de respuesta de **máximo 250 palabras** sin violar completitud lingüística;
4. arrastrar los campos obligatorios del reto y la procedencia/ calidad necesaria para citar y filtrar;
5. mantener el contexto estructural —sección, heading, página, tabla o lista— sin pérdidas silenciosas;
6. procesarse en streaming y producir artefactos completos o no publicar nada si una corrida falla;
7. ser verificable automáticamente contra todos los artefactos de ingesta.

## Casos que debe procesar correctamente antes de aprobar el dataset completo

La siguiente lista constituye una matriz mínima de validación para los 1.731 documentos canónicos ya ingeridos:

- Documentos con bloques inline y los **141 documentos** con blocks_ref.
- Los tres fenómenos: F1, F2 y F3, siempre serializados como 1, 2 y 3.
- Documentos full y los 18 structured_only, verificando que estos últimos no entren al índice vectorial.
- Los ocho idiomas y escrituras detectadas: español, inglés, portugués, chino, árabe, ruso, coreano y japonés.
- Texto nativo, OCR, PDF etiquetado y contenido estructurado.
- Bloques heading, paragraph, list_item, table_row, table_text, caption y page_text.
- Headings al comienzo, entre secciones, repetidos en secciones largas y al final del documento.
- Boilerplate de encabezado, pie y caption; especialmente Alertas Tempranas con códigos que sirven para trazabilidad.
- Párrafos de prosa con abreviaturas, siglas compuestas (U.S., U.K.), citas, números de lista y referencias.
- Oraciones de más de un presupuesto de embedding: deben preservarse y quedar marcadas para manejo posterior.
- Tablas anchas, texto de layout, figuras/captions y listas largas: deben mantener cabecera/contexto y cumplir la política de tamaño.
- Documentos de confianza alta, baja y unverified, propagando quality.confidence.score y basis.
- Validación de todos los campos obligatorios: doc_id, chunk_id, fuente, formato, fenomeno, posicion, num_tokens, texto.
- Tokens contados con el tokenizer del encoder que se vaya a utilizar; palabras contadas separadamente para el límite de 250.
- Fallos intencionales durante la escritura: los JSONL públicos anteriores deben quedar intactos y los temporales limpiarse o registrarse.
- Ejecución end-to-end reproducible con dependencias de test declaradas y pruebas que usen los modelos reales de ingesta.

**Criterio de aprobación:** una corrida completa debe finalizar sin excepciones, generar un manifiesto/summary válido, pasar todas las validaciones anteriores y dejar evidencia cuantitativa de excepciones, exclusiones y cobertura de texto.

