# auto-report-mcp

**Generación automática de informes profesionales en Word (.docx) mediante arquitectura MCP + RAG + OpenAI.**

---

## ¿Qué hace este sistema?

1. **Aprende tu estilo de redacción** a partir de tus informes históricos (.docx) usando RAG (Retrieval Augmented Generation)
2. **Genera automáticamente** informes Word profesionales cada día (lunes a viernes, 7:00 AM)
3. **Imita tu forma de escribir** usando fragmentos de tus informes anteriores como contexto
4. Soporta dos tipos de informes:
   - Pruebas funcionales (`functional_tests`)
   - Avance de proyectos (`project_progress`)

---

## Estructura del proyecto

```
auto-report-mcp/
├── app/
│   ├── main.py              # Entrypoint FastAPI + Scheduler
│   ├── config.py            # Configuración central (pydantic-settings)
│   ├── mcp/
│   │   ├── server.py        # MCP Router — endpoints de tools
│   │   └── tools/
│   │       ├── generate_report_tool.py    # Orquestador principal
│   │       ├── fetch_daily_data_tool.py   # Carga datos del día
│   │       ├── retrieve_style_tool.py     # Consulta RAG
│   │       └── save_report_tool.py        # Persistencia de manifests
│   ├── rag/
│   │   ├── ingest_documents.py  # Pipeline de ingesta histórica
│   │   ├── vector_store.py      # Abstracción ChromaDB
│   │   ├── retriever.py         # Estrategia de recuperación RAG
│   │   └── embedding_service.py # OpenAI embeddings con retry
│   ├── services/
│   │   ├── ai_service.py        # Generación narrativa con GPT-4o
│   │   ├── word_service.py      # Construcción del .docx
│   │   ├── data_service.py      # Carga/guardado de inputs diarios
│   │   └── scheduler_service.py # APScheduler — jobs automáticos
│   ├── models/
│   │   └── report_model.py      # Todos los modelos Pydantic
│   └── utils/
│       ├── logger.py
│       └── text_cleaner.py
├── data/
│   ├── raw_reports/         # ← Coloca aquí tus .docx históricos
│   ├── processed_chunks/    # Registry de ingesta (auto-generado)
│   └── daily_inputs/        # JSON con datos del día (YYYY-MM-DD_type.json)
├── vector_db/               # ChromaDB persistence (auto-generado)
├── output_reports/          # Informes .docx generados (auto-generado)
├── scripts/
│   ├── run_ingestion.py     # CLI: ingestar informes históricos
│   └── run_daily_generation.py  # CLI: generar informe manual
└── tests/
```

---

## Instalación y configuración

### 1. Clonar y configurar entorno

```bash
python -m venv venv
source venv/bin/activate   # Windows: venv\Scripts\activate
pip install -r requirements.txt
```

### 2. Configurar variables de entorno

```bash
cp .env.example .env
# Editar .env y agregar tu OPENAI_API_KEY
```

### 3. Ingestar informes históricos

Coloca tus informes anteriores en `data/raw_reports/` y ejecuta:

```bash
python scripts/run_ingestion.py

# Ver estadísticas de la base vectorial:
python scripts/run_ingestion.py --stats

# Ingestar un archivo específico:
python scripts/run_ingestion.py --file data/raw_reports/mi_informe.docx
```

### 4. Preparar datos del día

Crea el archivo de datos en `data/daily_inputs/` con el formato:

```
data/daily_inputs/YYYY-MM-DD_functional_tests.json
data/daily_inputs/YYYY-MM-DD_project_progress.json
```

Ver `data/daily_inputs/2025-01-15_functional_tests.json` como ejemplo completo.

### 5. Generar un informe manualmente

```bash
python scripts/run_daily_generation.py
python scripts/run_daily_generation.py --date 2025-01-15
python scripts/run_daily_generation.py --date 2025-01-15 --type project_progress
```

---

## Ejecutar el servidor (generación automática)

```bash
# Desarrollo
python -m app.main

# Con Docker
docker-compose up -d
```

El scheduler genera automáticamente el informe de pruebas funcionales cada día hábil a las **7:00 AM** (zona horaria configurada en `.env`).

---

## API REST (MCP Tools)

| Endpoint | Método | Descripción |
|----------|--------|-------------|
| `GET /mcp/tools` | GET | Lista todas las tools disponibles |
| `POST /mcp/tools/generate_report` | POST | Genera un informe completo |
| `POST /mcp/tools/trigger_daily` | POST | Trigger manual (mismo que el scheduler) |
| `POST /mcp/tools/fetch_daily_data` | POST | Carga el input JSON del día |
| `POST /mcp/tools/retrieve_style` | POST | Consulta RAG — para debug |
| `GET /mcp/tools/list_reports` | GET | Lista informes generados |
| `GET /health` | GET | Health check con estado de ChromaDB |

Documentación interactiva: `http://localhost:8000/docs`

---

## Formato del input diario (JSON)

### Pruebas funcionales

```json
{
  "report_date": "2025-01-15",
  "report_type": "functional_tests",
  "project_name": "Mi Proyecto",
  "project_version": "2.3.1",
  "environment": "QA",
  "prepared_by": "Nombre del QA",
  "test_cases": [
    {
      "test_id": "TC-001",
      "test_name": "Nombre del caso de prueba",
      "module": "Módulo del sistema",
      "status": "PASS",  // PASS | FAIL | BLOCKED | SKIP
      "execution_time_s": 1.2,
      "defects": [],
      "notes": ""
    }
  ],
  "risks": ["Riesgo 1"],
  "next_steps": ["Acción 1"]
}
```

---

## Tests

```bash
pytest                          # Todos los tests
pytest tests/unit/              # Solo unitarios
pytest --cov=app --cov-report=html  # Con cobertura
```

---

## Decisiones técnicas clave

| Decisión | Justificación |
|----------|---------------|
| **ChromaDB local** | Sin servidor externo — zero-config, portátil, suficiente para <1M chunks |
| **APScheduler BackgroundScheduler** | No bloquea el event loop de FastAPI; fácil de reemplazar por Celery |
| **JSON mode en OpenAI** | Elimina parsing frágil de markdown — respuestas estructurales garantizadas |
| **Ingesta idempotente (SHA-256)** | Re-ingestar los mismos archivos no genera duplicados |
| **Batch embeddings** | Una sola llamada API por lote de hasta 100 textos — eficiencia de costo |
| **Overlap en chunks (150 tokens)** | Preserva contexto semántico en los bordes de fragmentos |
| **Multi-query RAG** | Varias queries focalizadas capturan diferentes aspectos de estilo |

