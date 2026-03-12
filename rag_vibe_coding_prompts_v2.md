# RAG Refactor — Prompts de Vibe Coding

> **Ejecutar en orden estricto.** Cada prompt es atómico: no avanzar al siguiente hasta que el anterior compile y pase sus tests.

---

## Contexto del proyecto — leer antes de ejecutar cualquier prompt

Este proyecto es un sistema RAG (Retrieval-Augmented Generation) que asiste a un desarrollador en la generación de pruebas de software. El sistema actualmente funciona pero tiene problemas de calidad que este plan corrige de raíz.

### Qué hace el sistema hoy

Indexa documentos de un proyecto de software en ChromaDB y, cuando el usuario hace una consulta ("genera un test unitario para `saveUser`"), recupera contexto relevante y se lo pasa a un LLM para que genere la respuesta. También indexa notas diarias del desarrollador que deben tener prioridad máxima en el contexto recuperado.

### Cuáles son los problemas actuales

**Problema 1 — Mezcla de tipos de prueba.** El sistema tiene una sola colección plana en ChromaDB. Cuando se pide un test unitario, el sistema puede devolver tests de integración o funcionales como contexto, porque semánticamente son similares. El LLM genera tests incorrectos o mezclados como resultado.

**Problema 2 — Métodos inventados.** Existe un documento `.docx` de Word que describe los métodos reales de cada componente del proyecto. El sistema actual no lo identifica correctamente, entonces el LLM no sabe qué métodos existen y los inventa. Esto produce tests que no compilan.

**Problema 3 — Notas diarias ignoradas.** El desarrollador escribe notas diarias con contexto actualizado del proyecto (decisiones recientes, cambios de arquitectura, métodos deprecados). Esas notas deben aparecer siempre primero en el contexto recuperado porque corrigen información desactualizada de documentos más viejos. Actualmente compiten en igualdad de condiciones con el resto.

**Problema 4 — Respuestas genéricas.** El Multi-Query Retrieval expande semánticamente cada consulta para maximizar el recall, lo que trae contexto amplio pero irrelevante. Para generar pruebas se necesita lo opuesto: contexto específico y preciso del componente exacto que se está testeando.

**Problema 5 — Documentos Word no procesados.** Los documentos de métodos están en formato `.docx`. El sistema actual no tiene soporte para leer Word, por lo que ese contexto nunca llega al índice.

### Qué hace este plan

Refactoriza el sistema en 12 pasos atómicos, de menor a mayor complejidad, sin romper lo que funciona. Los cambios principales son:

- **4 colecciones separadas** en ChromaDB en lugar de una: `unit_tests`, `integration_tests`, `functional_tests`, `project_docs`. La separación garantiza que una búsqueda de test unitario nunca devuelva tests de integración.
- **Lector de `.docx`** que extrae texto, secciones, tablas y bloques de código de documentos Word antes de clasificarlos e indexarlos.
- **Clasificador automático** que decide a qué colección va cada documento según su contenido y nombre de archivo, sin intervención manual.
- **Chunking estructural** donde un test completo es un chunk, nunca se corta dentro de un `assert`, y un método completo con su firma es un chunk, nunca se corta a la mitad.
- **Query Router** que reemplaza el Multi-Query Retrieval: en lugar de expandir la consulta hacia afuera, la enruta al destino correcto directamente.
- **Validador de métodos** que construye un registro de métodos reales desde los documentos indexados y detecta cuando el LLM inventa uno que no existe.
- **Caché semántico** que cachea resultados completos de búsqueda (no embeddings individuales) y se invalida automáticamente cuando llega una nota diaria nueva.

### Tecnologías del proyecto

- **ChromaDB** como vector store
- **OpenAI API o Ollama** para embeddings
- **Python** como lenguaje del sistema RAG
- **Documentos fuente**: `.py`, `.ts`, `.js`, `.java`, `.kt`, `.md`, `.txt`, `.docx`

### Archivos que se crean o modifican

| Orden | Prompt | Archivo | Acción |
|-------|--------|---------|--------|
| 1 | PROMPT 1 | — | Solo auditoría, sin cambios |
| 2 | PROMPT 2 | `rag_schema.py` | Crear |
| 3 | PROMPT 2.5 | `docx_reader.py` | Crear (soporte Word) |
| 4 | PROMPT 3 | Inicialización ChromaDB | Modificar |
| 5 | PROMPT 4 | `document_classifier.py` | Crear |
| 6 | PROMPT 5 | `structural_chunker.py` | Crear |
| 7 | PROMPT 6 | `document_ingestion_pipeline.py` | Crear |
| 8 | PROMPT 7 | `query_router.py` | Crear |
| 9 | PROMPT 8 | `method_validator.py` | Crear |
| 10 | PROMPT 9 | `semantic_cache.py` | Crear |
| 11 | PROMPT 10 | Archivo principal RAG + `migrate_to_v2.py` | Actualizar + crear |
| 12 | PROMPT 11 | Tests + limpieza | Validar y limpiar |

---

## PROMPT 1 — Auditoría del sistema actual

```
Analiza todos los archivos del proyecto relacionados con el sistema RAG.
Busca específicamente:
1. Dónde se configura ChromaDB (colecciones, parámetros)
2. Cómo se hace el chunking de documentos actualmente
3. Cómo está implementado el Multi-Query Retrieval
4. Qué campos de metadata se guardan hoy por documento
5. Cómo funciona el LRU Cache actual
6. Dónde y cómo se aplica el Recency Boosting

No modifiques nada. Solo genera un reporte con:
- Nombre exacto de cada archivo relevante y su ruta
- Fragmento de código clave de cada punto anterior
- Lista de problemas detectados según este sistema deseado:
  * 4 colecciones separadas: unit_tests, integration_tests,
    functional_tests, project_docs
  * Tipos de prueba diferenciados con precisión máxima
  * Notas diarias con prioridad máxima sobre documentos regulares
  * Documentos .docx de Word como fuente soportada
  * Documentos de métodos identificados, nunca métodos inventados
```

---

## PROMPT 2 — Definir el esquema de metadata y constantes

```
En el proyecto RAG, crea un archivo llamado `rag_schema.py` con:

1. Enum DocType con los valores:
   UNIT_TEST, INTEGRATION_TEST, FUNCTIONAL_TEST,
   METHOD_DOC, PROJECT_DOC, DAILY_NOTE

2. Enum CollectionName con los valores:
   UNIT_TESTS = "unit_tests"
   INTEGRATION_TESTS = "integration_tests"
   FUNCTIONAL_TESTS = "functional_tests"
   PROJECT_DOCS = "project_docs"

3. Función get_collection_for_doc_type(doc_type: DocType) -> CollectionName
   que mapea:
   UNIT_TEST        → UNIT_TESTS
   INTEGRATION_TEST → INTEGRATION_TESTS
   FUNCTIONAL_TEST  → FUNCTIONAL_TESTS
   METHOD_DOC       → PROJECT_DOCS
   PROJECT_DOC      → PROJECT_DOCS
   DAILY_NOTE       → PROJECT_DOCS

4. Dataclass DocumentMetadata con los campos:
   doc_type: DocType       (obligatorio)
   test_type: str          (solo para tests: "unit"|"integration"|"functional")
   component: str          (nombre de la clase o módulo, ej: "UserService")
   method_name: str        (método específico si aplica, sino "")
   language: str           (lenguaje de programación del código)
   framework: str          (framework de testing: "jest", "pytest", "junit", etc.)
   is_daily_note: bool
   note_date: str          (formato ISO "2024-01-15", sino "")
   source_file: str        (ruta del archivo original)
   priority_score: float   (1.0 por defecto, 2.0 para daily notes)

5. Tests unitarios para get_collection_for_doc_type que validen
   todos los mappings.

No modifiques ningún archivo existente todavía.
```

---

## PROMPT 2.5 — Soporte para archivos .docx de Word

```
Antes de crear las colecciones de ChromaDB, el sistema debe poder leer
archivos .docx como fuente de documentos del proyecto.

1. Agrega "python-docx" a requirements.txt si no está.

2. Crea `docx_reader.py` con clase DocxReader:

   Dataclass DocxContent con campos:
   - raw_text: str
   - sections: list[str]            (divididas por headings)
   - tables: list[list[list[str]]]  (matrices celda por celda)
   - metadata_hints: dict
   - filename: str
   - file_path: str

   Método read(file_path: str) -> DocxContent:
   a. Recorrer todos los párrafos del documento en orden
   b. Headings (style.name contiene "Heading") → delimitadores de sección
   c. Bloques monospace (Courier, Consolas, estilo "Code") → delimitar con
      @@CODE_START@@ y @@CODE_END@@ para tratarlos como código
   d. Preservar tablas celda por celda
   e. Ignorar imágenes y objetos embebidos

   Método extract_metadata_hints(doc) -> dict con campos:
   - has_code_blocks: bool
   - has_tables: bool
   - heading_count: int
   - first_heading: str
   - word_count: int
   - detected_keywords: list[str]  (primeras 20 palabras únicas significativas)
   - possible_component: str
     (busca "Clase: X", "Módulo: X", "Service", "Repository", "Controller"
     en los primeros 3 headings)
   - possible_methods: list[str]
     (patrones de firma dentro de bloques @@CODE@@:
     "nombreCamelCase(", "def nombre_", "function nombre")

   Método read_directory(dir_path: str) -> list[DocxContent]:
   Lee todos los .docx de un directorio.
   Loggear archivos que fallen (corruptos o protegidos con contraseña).

3. Este módulo NO modifica ningún archivo existente todavía.
   Los prompts 4, 5 y 6 lo integrarán cuando sean ejecutados.

4. Tests unitarios para DocxReader:
   Crear un .docx de fixture con python-docx dentro del propio test
   (un documento con 2 headings, 1 tabla, 1 bloque monospace).
   Verificar:
   - sections tiene 2 entradas
   - tables tiene 1 entrada con la estructura correcta
   - el bloque monospace está delimitado con @@CODE_START@@
   - metadata_hints["has_code_blocks"] = True
   - metadata_hints["has_tables"] = True
```

---

## PROMPT 3 — Crear las 4 colecciones en ChromaDB

```
En el archivo donde se inicializa ChromaDB, realiza los siguientes
cambios usando el esquema de rag_schema.py:

1. Crea la función initialize_collections(chroma_client) -> dict[str, Collection]
   que use get_or_create para las 4 colecciones:
   "unit_tests", "integration_tests", "functional_tests", "project_docs"
   Cada colección usa la misma embedding_function que el proyecto hoy.
   La función retorna un dict con las 4 colecciones accesibles por nombre.

2. Crea la función get_collection(collections: dict, doc_type: DocType) -> Collection
   que use get_collection_for_doc_type() de rag_schema.py.

3. NO migres datos todavía. NO elimines la colección anterior todavía.
   Solo agrega las nuevas colecciones en paralelo.

4. Test de integración con ChromaDB in-memory:
   - Las 4 colecciones existen tras llamar a initialize_collections
   - get_collection retorna la colección correcta para cada DocType
```

---

## PROMPT 4 — Clasificador de tipo de documento

```
Crea `document_classifier.py` con clase DocumentClassifier.

El clasificador debe aceptar tanto str como DocxContent (de docx_reader.py)
como parámetro content en todos sus métodos.

1. Método classify_test_type(content, filename) -> DocType

   UNIT_TEST si:
   - filename contiene: "unit", ".unit.", "_unit", "unit_"
   - content contiene: mock, stub, spy, patch, MagicMock,
     jest.fn(), vi.fn(), @patch, unittest
   - content NO contiene: database, http, api, integration,
     e2e, browser, selenium, playwright

   INTEGRATION_TEST si:
   - filename contiene: "integration", ".int.", "_int", "int_"
   - content contiene: database, db., repository, http,
     axios, fetch, requests.get, TestClient, supertest

   FUNCTIONAL_TEST si:
   - filename contiene: "e2e", "functional", "feature", "scenario"
   - content contiene: browser, page., selenium, playwright,
     cypress, Scenario:, "Given ", "When ", "Then "

   Si ninguna regla aplica con confianza > 0.6:
   retornar UNIT_TEST por defecto y loggear warning con el filename.

2. Método classify_document(content, filename) -> DocumentMetadata

   Es TEST si filename contiene: test, spec, _test., .test., Test., Spec.
   O si content tiene patrones: def test_, it(", describe(", @Test, [Test]

   Es METHOD_DOC si content tiene firmas de función con documentación
   (docstrings, JSDoc /** */, comentarios de parámetros y retorno)

   Es PROJECT_DOC en cualquier otro caso

   Si content es DocxContent:
   - Usar metadata_hints["possible_component"] como fuente primaria de component
   - Usar metadata_hints["possible_methods"] como candidatos de method_name
   - Dar mayor peso a imports dentro de bloques @@CODE@@ para detectar lenguaje

   Extraer siempre: component, method_name, language, framework

3. Método is_daily_note(content, filename) -> bool
   True si:
   - filename contiene fecha YYYY-MM-DD o "daily", "note", "diario", "nota"
   - O el contenido empieza con un heading de fecha (# 2024-01-15)

4. Tests unitarios: 3 casos positivos + 2 negativos por cada tipo.
   Usar fixtures con contenido de ejemplo real.
```

---

## PROMPT 5 — Chunking estructural por unidad lógica

```
Reemplaza el chunking actual con una clase StructuralChunker
en `structural_chunker.py`.

Regla central: la unidad mínima de chunk es la unidad lógica del código,
no un conteo de tokens.

1. Método chunk_test_file(content, metadata) -> list[dict]

   Un test completo = un chunk.
   Delimitadores por lenguaje:
   - Python:       "def test_" hasta el próximo "def test_"
   - JS/TS:        "it(" o "test(" hasta su cierre de bloque
   - Java:         "@Test" hasta el cierre "}" del método
   El chunk incluye: nombre del test + arrange + act + assert completos.

   Si un test supera 800 tokens, dividir en:
   - chunk_a: desde inicio hasta "# Arrange" / "// Given"
   - chunk_b: desde "# Act" / "// When" hasta el final del assert

   Cada chunk es un dict con:
   - content: str
   - metadata: DocumentMetadata original +
       chunk_type: "full_test" | "test_arrange" | "test_assert"
       test_name: nombre de la función extraída
       chunk_index: número de orden dentro del archivo

2. Método chunk_method_doc(content, metadata) -> list[dict]

   Un método = un chunk.
   CRÍTICO: cada chunk debe contener siempre:
   - Nombre exacto del método
   - Parámetros con sus tipos
   - Tipo de retorno
   - Descripción de qué hace
   Si falta alguno: marcar has_incomplete_signature = True en metadata.
   Nunca cortar dentro de la firma de un método.

   Para DocxContent: Heading 2 y su contenido completo = un chunk.
   Bloques @@CODE_START@@...@@CODE_END@@ → tratar como code unit.
   Si una sección supera 1200 tokens: dividir por Heading 3.

3. Método chunk_project_doc(content, metadata) -> list[dict]
   Sliding window respetando párrafos completos.
   chunk_size = 600 tokens, overlap = 100 tokens.
   Nunca cortar dentro de un párrafo.

4. Método chunk_daily_note(content, metadata) -> list[dict]
   Una nota = un chunk siempre.
   Si supera 1200 tokens: dividir por headers ##, nunca por tokens.
   Preservar la fecha en todos los chunks de la misma nota.

5. Método chunk_document(content, metadata) -> list[dict]
   Router principal que llama al método correcto según metadata.doc_type.

6. Tests: verificar especialmente que ningún chunk de test
   queda con un assert incompleto.
```

---

## PROMPT 6 — Pipeline de ingestión con clasificación automática

```
Crea `document_ingestion_pipeline.py` con clase DocumentIngestionPipeline.

Constructor recibe:
- chroma_collections: dict de colecciones del PROMPT 3
- classifier: instancia de DocumentClassifier del PROMPT 4
- chunker: instancia de StructuralChunker del PROMPT 5
- docx_reader: instancia de DocxReader del PROMPT 2.5
- embedding_function: la misma que usa el proyecto hoy

1. Método ingest_file(file_path: str) -> IngestResult
   a. Si extensión es .docx: usar docx_reader.read() primero,
      loggear "Procesando Word: [filename]"
      Pasar DocxContent al clasificador (no el texto crudo)
   b. Clasificar con classifier.classify_document()
   c. Si is_daily_note: sobrescribir priority_score = 2.0
   d. Chunkear con chunker.chunk_document()
   e. Generar embedding y guardar en la colección correcta
   f. Retornar IngestResult: archivo procesado, colección destino,
      número de chunks generados, doc_type detectado

2. Método ingest_directory(dir_path, recursive=True) -> list[IngestResult]
   Extensiones a procesar: .py .ts .js .java .kt .md .txt .docx
   Loggear archivos ignorados.

3. Método ingest_daily_note(content: str, date: str) -> IngestResult
   Para notas escritas directo en una interfaz, sin archivo.
   date en formato ISO "2024-01-15".
   Siempre: project_docs, is_daily_note=True, priority_score=2.0

4. Método check_duplicate(content, collection_name) -> bool
   No reingestar si similitud coseno > 0.98.

5. Tests de integración con ChromaDB in-memory:
   - archivo .test.py → unit_tests
   - archivo integration.test.ts → integration_tests
   - archivo UserService.docx → project_docs
   - daily note → project_docs con priority_score = 2.0
   - sin duplicados al ingestar el mismo archivo dos veces
```

---

## PROMPT 7 — Query Router: reemplazar Multi-Query Retrieval

```
Elimina el Multi-Query Retrieval actual y crea `query_router.py`
con clase TestAwareQueryRouter.

1. Método detect_query_intent(query: str) -> QueryIntent
   Dataclass QueryIntent con:
   - wants_test: bool
   - test_type: DocType | None
   - target_component: str
   - target_method: str
   - needs_method_context: bool

   wants_test = True si contiene:
   "test", "prueba", "testear", "spec", "genera", "crea un test",
   "escribe un test", "unit test", "mock"

   test_type:
   UNIT_TEST:        "unit", "unitaria", "mock", "aislado", "sin dependencias"
   INTEGRATION_TEST: "integración", "integration", "base de datos", "api", "http"
   FUNCTIONAL_TEST:  "funcional", "e2e", "end to end", "flujo completo", "scenario"

   needs_method_context = True siempre que wants_test = True

2. Método route(query: str, collections: dict) -> RetrievalResult
   Dataclass RetrievalResult con:
   - chunks: list[dict]
   - primary_source: str
   - method_context_found: bool
   - daily_notes_included: bool

   CASO A — usuario pide generar un test:
   Paso 1: project_docs donde doc_type=METHOD_DOC,
           filtrar por component y method_name si se detectaron → top 3
   Paso 2: colección del test_type detectado,
           filtrar por component si se detectó → top 4
   Paso 3: project_docs donde is_daily_note=True,
           filtrar por component si aplica → top 2
   Resultado: daily notes SIEMPRE van primero en la lista final,
   sin importar su score de similitud.

   CASO B — usuario busca un test existente:
   Buscar solo en la colección del tipo detectado.
   Si no se detectó tipo: buscar en las 3 colecciones y combinar.

   CASO C — usuario pregunta sobre un método o funcionalidad:
   Buscar solo en project_docs.
   Orden: daily notes > method_docs > project_docs.

3. Método privado _apply_priority_scoring(chunks) -> list[dict]
   - is_daily_note = True:              score × priority_score (2.0)
   - has_incomplete_signature = True:   score × 0.3
   - component coincide exactamente:    score × 1.5
   - method_name coincide exactamente:  score × 2.0

4. Tests unitarios:
   - "genera un test unitario para UserService.saveUser" → CASO A, UNIT_TEST
   - "cómo funciona el método authenticate" → CASO C
   - "muéstrame tests de integración del repositorio" → CASO B
   - daily notes siempre primeras en resultado de CASO A
```

---

## PROMPT 8 — Resolver el problema de métodos inventados

```
Crea `method_validator.py` para evitar que el LLM use métodos
que no existen en el proyecto.

1. Clase MethodRegistry (fuente de verdad de métodos reales):

   Método build_registry(project_docs_collection) -> dict
   Consulta project_docs filtrando por doc_type=METHOD_DOC.
   Construye diccionario indexado por component:
   {
     "UserService": {
       "methods": ["saveUser", "findById", "deleteUser"],
       "signatures": {
         "saveUser": "saveUser(user: UserDTO): Promise<User>",
         ...
       }
     }
   }

   Método get_real_methods(component: str) -> list[str]
   Retorna métodos reales del componente.
   Si no existe: retorna lista vacía y loggea warning.

2. Clase MethodGroundingFilter:

   Método filter_hallucinated_methods(
     llm_response, component, registry) -> FilterResult

   FilterResult tiene:
   - original_response: str
   - filtered_response: str
   - hallucinated_methods: list[str]
   - real_methods_used: list[str]
   - has_hallucinations: bool

   Lógica:
   a. Extraer métodos mencionados en llm_response
      (patrones: nombreCamelCase(), nombre_snake(), .método())
   b. Verificar cada uno contra registry.get_real_methods(component)
   c. Si hay hallucinated: añadir al final de filtered_response:
      "⚠️ ADVERTENCIA: Los siguientes métodos no existen en [component]
       según la documentación indexada: [lista].
       Métodos reales disponibles: [lista]"

3. Función build_system_prompt(component, registry) -> str
   Genera el prompt de sistema que se envía al LLM:

   "Eres un asistente especializado en generar tests.
   REGLA CRÍTICA: Solo puedes usar métodos que existan en la documentación
   proporcionada. Los métodos reales disponibles en {component} son: {lista}.
   Si necesitas un método que no está en esta lista, menciona explícitamente
   que ese método no está documentado en lugar de inventarlo."

4. Tests unitarios:
   - Detecta correctamente métodos inventados en respuesta de ejemplo
   - El warning se añade al response cuando hay hallucinations
   - El system prompt contiene la lista real de métodos
```

---

## PROMPT 9 — Caché semántico de resultados completos

```
Elimina o desactiva el LRU Cache actual que cachea embeddings individuales.
Crea `semantic_cache.py` con clase SemanticQueryCache.

Constructor recibe:
- embedding_function
- similarity_threshold: float = 0.92
- max_size: int = 300
- ttl_hours: int = 24

1. Método get(query: str, intent_key: str) -> CachedResult | None
   intent_key = f"{test_type}_{component}_{method}"
   (separa cachés de intents distintos)

   Proceso:
   a. Embedear la query entrante
   b. Comparar con embeddings cacheados del mismo intent_key
   c. Si similitud > threshold: retornar resultado cacheado
   d. Si no: retornar None

2. Método set(query, intent_key, result: RetrievalResult) -> None
   Guardar query + embedding + result.
   LRU eviction si se supera max_size.

3. Método invalidate_by_component(component: str) -> int
   Invalidar entradas del caché que involucren ese component.
   Llamar cuando se reingesta un documento.
   Retornar número de entradas invalidadas.

4. Método invalidate_daily_notes_cache() -> int
   Invalidar entradas donde daily_notes_included = True.
   Llamar cada vez que se ingesta una daily note nueva.

5. Tests unitarios:
   - Hit cuando la query es semánticamente igual
   - Miss cuando la query es diferente
   - Invalidación correcta por componente
   - Ingestar daily note invalida el caché relevante
```

---

## PROMPT 10 — Integración final y migración de datos

```
Integra todos los componentes anteriores en un único orquestador
y migra los datos existentes.

PARTE A — Orquestador principal (TestRAGSystem):

Constructor:
- Inicializa ChromaDB con las 4 colecciones (PROMPT 3)
- Instancia DocumentClassifier, StructuralChunker, DocxReader
- Instancia DocumentIngestionPipeline
- Instancia TestAwareQueryRouter
- Instancia MethodRegistry, MethodGroundingFilter
- Instancia SemanticQueryCache
- Llama a MethodRegistry.build_registry() con lo ya indexado

Método query(user_query: str) -> RAGResponse:
1. Revisar SemanticQueryCache → si hit, retornar
2. Detectar intent con QueryRouter.detect_query_intent()
3. Recuperar chunks con QueryRouter.route()
4. Si wants_test: generar system prompt con métodos reales
5. Llamar al LLM con contexto + system prompt
6. Si wants_test: filtrar con MethodGroundingFilter
7. Guardar en SemanticQueryCache
8. Retornar RAGResponse: respuesta, chunks usados, has_hallucinations

Método add_daily_note(content, date=None) -> IngestResult:
- date por defecto = hoy en ISO
- Llama a pipeline.ingest_daily_note()
- Llama a cache.invalidate_daily_notes_cache()
- Actualiza MethodRegistry

Método add_document(file_path) -> IngestResult:
- Llama a pipeline.ingest_file()
- Llama a cache.invalidate_by_component() si aplica
- Actualiza MethodRegistry si es METHOD_DOC

PARTE B — Script de migración (migrate_to_v2.py):

1. Lee todos los documentos de la colección actual (la vieja)
2. Por cada documento: reclasifica con DocumentClassifier
3. Rechunkea con StructuralChunker
4. Ingesta en la colección nueva correcta
5. Al finalizar: imprime resumen por colección
6. NO elimina la colección vieja (dejar como backup)

PARTE C — Tests end-to-end con ChromaDB in-memory:

Test 1: ingestar test unitario → query → solo tests unitarios en resultado
Test 2: ingestar UserService.docx → query "genera test para saveUser"
        → contexto tiene firma real + system prompt con métodos reales
Test 3: ingestar daily note → query sobre mismo componente
        → daily note aparece primera
Test 4: simular LLM inventando método → MethodGroundingFilter lo detecta
Test 5: misma query dos veces → segunda servida desde caché
```

---

## PROMPT 11 — Validación final y limpieza

```
Ejecuta la suite completa de tests y resuelve cualquier error.
Luego realiza estas verificaciones manuales:

1. Ejecuta migrate_to_v2.py contra los documentos reales.
   El resumen debe mostrar distribución entre colecciones
   (no todo en la misma).

2. Cinco queries de prueba obligatorias:
   a. "genera un test unitario para [método real del proyecto]"
      → solo tests unitarios + firma real del método
   b. "genera un test de integración para [componente real]"
      → solo tests de integración, sin unitarios mezclados
   c. "¿qué métodos tiene [clase real del proyecto]?"
      → documentación del método, no tests
   d. Escribe una nota diaria, ingestala, consulta el mismo componente
      → la nota aparece primera en el contexto
   e. Repite la query (a)
      → servida desde caché semántico (verificar en logs)

3. Si alguna verificación falla, reportar:
   - Qué query falló
   - Qué retornó vs qué se esperaba
   - En qué colección estaban los resultados incorrectos
   Corregir el clasificador o el router según corresponda.

4. Una vez que las 5 queries pasen:
   - Eliminar la colección vieja de ChromaDB
   - Eliminar el código del Multi-Query Retrieval anterior

5. Actualizar el README con:
   - Las 4 colecciones y qué tipo de documento va en cada una
   - Cómo agregar una daily note
   - Cómo ingestar documentos .docx de métodos
   - Formato esperado de los .docx para que el clasificador
     los detecte correctamente
```
