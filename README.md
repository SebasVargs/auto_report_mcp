# automatizationAI (Auto-Report GCP + RAG + AI)

**Generación automática de informes profesionales en Word (.docx) mediante arquitectura RAG + OpenAI.**

Este sistema actúa como un **Agente Documental Inteligente** que no solo genera reportes a partir de recolecciones de datos interactivos, sino que **aprende tu estilo de redacción** a partir de informes históricos, y mantiene una **Base de Conocimiento Inteligente** (Knowledge Base) consolidando notas.

---

## 🚀 Características Principales

1. **Recolección Guiada e Interactiva por Terminal (CLI)**: Recopila datos de pruebas y progreso diario haciendo preguntas inteligentes dependiendo del tipo de reporte seleccionado.
2. **Soporte Multi-Reporte**: Soporta múltiples formatos de informes de pruebas de software:
   - 🛡️ **Pruebas Funcionales** (Caja Negra)
   - 🧩 **Pruebas de Integración** (Caja Negra y Caja Blanca)
   - ⚙️ **Pruebas Unitarias** (Caja Blanca pura)
   - 📈 **Avance de Proyectos** (Project Progress)
3. **Manejo de Evidencia en Imágenes**: Integra capturas de pantalla de evidencia directamente desde la ruta de descargas al documento Word `.docx` final, con escalado y formatos automáticos.
4. **Base de Conocimiento Inteligente (RAG)**:
   - **Ingesta de Históricos**: Procesa documentos `.docx` antiguos para que la IA imite tu redacción.
   - **Manejo de Notas (Consolidación Inteligente)**: Permite ingresar notas técnicas manuales. Si detecta notas similares previas usando similitud semántica, utiliza la IA para **fusionarlas**, preservando la base de datos sin contradicciones ni redundancias.
   - **Chat Interactivo**: Consulta el conocimiento adquirido del proyecto con retención de historial de conversación.
5. **Generación de Word Nativa**: Renderiza tablas complejas, índices técnicos, y reportes maquetados nativamente usando `python-docx`.
6. **Integración con Google Drive**: Sincroniza reportes de contexto, imágenes de evidencia, y guarda los reportes resultantes directamente en la nube.
7. **Recuperación Ante Fallos**: Mantiene sesiones en memoria temporal `.session_checkpoint.json` durante la recolección de datos masiva interactiva para evitar pérdida de trabajo ante cierres inesperados.

---

## 📂 Estructura del Proyecto

```text
automatizationAI/
├── app/
│   ├── main.py              # Entrypoint principal
│   ├── config.py            # Configuración centralizada (Pydantic Settings)
│   ├── models/
│   │   └── report_model.py  # Modelos de Datos Centrales (Report Type, Test Cases)
│   ├── services/
│   │   ├── ai_service.py    # Abstracción de OpenAI (Prompts, Generación y Fusión)
│   │   ├── word_service.py  # Construcción del .docx dinámico
│   │   ├── data_service.py  # Persistencia de JSONs crudos
│   │   ├── drive_service.py # Interacción con la API de Google Drive
│   │   └── interactive_narrative_assistant.py # Agente de ayuda interactiva en consola
│   └── rag/
│       ├── knowledge_ingestion.py   # Ingesta de contexto y consolidación de notas
│       ├── knowledge_retriever.py   # Consulta interactiva (Chat RAG)
│       ├── vector_store.py          # Abstracción de ChromaDB local
│       ├── retriever.py             # Recuperación de Estilos de escritura
│       └── embedding_service.py     # Embeddings modelo OAI
├── data/
│   ├── raw_reports/         # Informes históricos para contexto RAG
│   ├── input_images/        # Directorio temporal de evidencias
│   └── daily_inputs/        # Archivos JSON estructurados en proceso
├── vector_db/               # Almacenamiento local persistente ChromaDB
├── output_reports/          # .docx generados localmente
└── cli.py                   # 🖥️ CLI Principal del Sistema
```

---

## 🛠️ Instalación y Configuración

### 1. Clonar y configurar entorno

```bash
python -m venv venv
source venv/bin/activate
pip install -r requirements.txt
```

### 2. Variables de Entorno

```bash
cp .env.example .env
# Edita el .env introduciendo tu OPENAI_API_KEY y credenciales de Google
```
> **Nota de modelo AI:** El CLI y la generación usan modelos eficientes y predictivos mediante JSON Mode (e.g. `gpt-4o`).

### 3. Credenciales de Drive
Coloca tu archivo `credentials.json` en la raíz (generado desde Google Cloud Console) y tu token `token.json` se generará automáticamente en el primer inicio de sesión.

---

## 💻 Uso de la Interfaz CLI

El corazón operativo para el usuario humano es el archivo `cli.py` (interfaz Rich interactiva). Ejecuta:

```bash
python cli.py
```

### Menú Principal

- **[ 📝 Generar un Informe ]**:
  Inicia un cuestionario guiado que captura información por cada tipo de informe. Soporta subida de imágenes, sugerencias de IA dinámicas, autoguardado en memoria y render final de documento en Word.
  
- **[ 📚 Base de Conocimiento del Proyecto ]**:
  Permite sincronizar reportes `.docx` antiguos de Google Drive o agregar notas manuales de contexto del proyecto. Aquí se activará la consola si detecta un tema repetido, preguntando si deseas **Merge** (Fusionar con IA) para evitar fragmentación.

- **[ 🔍 Consultar Conocimiento (Chat) ]**:
  Una interfaz interactiva RAG. Conversa con tus notas de conocimiento de manera libre y fluida.

- **[ 🗂️  Listar Informes ]**:
  Comprueba tu historial de informes locales finalizados.

---

## 🧠 Arquitectura de Prompts & Test Types

El sistema cuenta con manejo modular según la metodología:
- `FUNCTIONAL_TESTS`: Captura ejecución, entrada/condiciones, resultados esperados y reales en ambiente de prueba (Caja Negra).
- `INTEGRATION_TESTS`: Incluye campos mixtos para evaluar integración, como validaciones de método, y tipo/porcentaje de Cobertura (Caja Mixta).
- `UNIT_TESTS`: Solicita exclusivamente variables de entorno de dependencias y código, como **Covered Class**, **Covered Method** y **Test Framework** (ej. Jest/PyTest) (Caja Blanca).

Cada uno procesado en `word_service.py` hacia un template matriz unificado pero variante algorítmicamente para el .docx final.

---

## ⚡ Pruebas

```bash
pytest
```
Soporta pruebas unitarias y validación general de componentes de negocio de la carpeta `tests/`.

---

**AutomatizationAI** fue construido enfocándose en la minimización de tiempos de reporte manual, centralización del contexto de negocio, y diseño arquitectónico limpio a nivel de prompts y componentes.
