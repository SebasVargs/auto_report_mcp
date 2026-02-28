from __future__ import annotations

import json

from app.config import get_settings
from app.models.report_model import (
    DailyInput,
    GeneratedReport,
    ReportSection,
    ReportType,
    StyleContext,
)
from app.providers.base import LLMProvider
from app.providers import get_llm_provider
from app.utils.logger import get_logger

logger = get_logger(__name__)
settings = get_settings()


SYSTEM_PROMPT = """Eres un experto redactor técnico especializado en informes profesionales de software.
Tu misión es generar informes en español con el siguiente contrato de estilo:

REGLAS DE ESTILO:
- Tono: técnico, formal, preciso. Nunca coloquial.
- Voz: activa preferentemente ("El equipo ejecutó" no "fue ejecutado por el equipo")
- Párrafos: 3-5 oraciones. Sin listas innecesarias en narrativa.
- Métricas: siempre acompañadas de contexto ("83% de cobertura, superando el umbral del 80%")
- Conclusiones: orientadas a acción, no solo descriptivas.
- Nunca uses frases como "cabe destacar", "es importante mencionar", "en este sentido".
- El informe debe poder leerse por un gerente no técnico y por un líder técnico sin pérdida de información.

FORMATO DE RESPUESTA:
Responde SIEMPRE como JSON válido con la estructura que se te indique en cada solicitud.
"""


class AIService:
    """
    Generates report narrative using any configured LLM provider.
    Provider is resolved from settings (LLM_PROVIDER env var) by default,
    but can be injected for testing or custom usage.
    """

    def __init__(self, provider: LLMProvider | None = None):
        self._provider = provider or get_llm_provider()

    def generate_report(
        self,
        daily_input: DailyInput,
        style_context: StyleContext,
    ) -> GeneratedReport:
        """
        Full report generation pipeline.
        Returns a GeneratedReport domain object.
        """
        logger.info(f"Generating report for {daily_input.report_date} | {daily_input.report_type}")

        style_examples = style_context.as_context_string

        # Executive summary is not rendered for functional_tests reports, skip the LLM call
        if daily_input.report_type == ReportType.FUNCTIONAL_TESTS:
            executive_summary = ""
        else:
            executive_summary = self._generate_executive_summary(daily_input, style_examples)
        sections = self._generate_sections(daily_input, style_examples)
        conclusions = self._generate_conclusions(daily_input, style_examples)

        return GeneratedReport(
            report_date=daily_input.report_date,
            report_type=daily_input.report_type,
            project_name=daily_input.project_name,
            environment=daily_input.environment,
            executive_summary=executive_summary,
            sections=sections,
            conclusions=conclusions,
            next_steps=daily_input.next_steps,
        )

    # ─────────────────────────────────────────────────
    # Section generators
    # ─────────────────────────────────────────────────

    def _generate_executive_summary(
        self, data: DailyInput, style_examples: str
    ) -> str:
        if data.report_type == ReportType.FUNCTIONAL_TESTS:
            total = len(data.test_cases)
            passed = sum(1 for t in data.test_cases if t.status == "PASS")
            failed = sum(1 for t in data.test_cases if t.status == "FAIL")
            user_prompt = f"""
Genera el RESUMEN EJECUTIVO de un informe de pruebas funcionales.

DATOS:
- Proyecto: {data.project_name} v{data.project_version}
- Fecha: {data.report_date}
- Ambiente: {data.environment}
- Total casos: {total} | Exitosos: {passed} | Fallidos: {failed}
- Responsable: {data.prepared_by}

EJEMPLOS DE ESTILO DE INFORMES ANTERIORES:
{style_examples[:2000]}

Responde con JSON: {{"summary": "<texto del resumen, 3-4 párrafos>"}}
"""
        else:
            done = sum(1 for t in data.tasks if t.status == "DONE")
            total = len(data.tasks)
            avg_progress = sum(t.progress_pct for t in data.tasks) // max(total, 1)
            user_prompt = f"""
Genera el RESUMEN EJECUTIVO de un informe de avance de proyecto.

DATOS:
- Proyecto: {data.project_name}
- Fecha: {data.report_date}
- Tareas completadas: {done}/{total}
- Progreso promedio: {avg_progress}%
- Responsable: {data.prepared_by}
- Notas generales: {data.general_notes}

EJEMPLOS DE ESTILO DE INFORMES ANTERIORES:
{style_examples[:2000]}

Responde con JSON: {{"summary": "<texto del resumen, 3-4 párrafos>"}}
"""
        return self._call_json(user_prompt).get("summary", "")

    def _generate_sections(
        self, data: DailyInput, style_examples: str
    ) -> list[ReportSection]:
        # For functional_tests, all content goes into the test case tables — no body sections needed
        if data.report_type == ReportType.FUNCTIONAL_TESTS:
            return []
        return self._generate_project_sections(data, style_examples)

    def _generate_project_sections(
        self, data: DailyInput, style_examples: str
    ) -> list[ReportSection]:
        tasks_data = json.dumps(
            [t.model_dump() for t in data.tasks], ensure_ascii=False, indent=2
        )
        prompt = f"""
Genera las secciones del cuerpo del informe de avance de proyecto.

DATOS DE TAREAS:
{tasks_data[:3000]}

RIESGOS: {json.dumps(data.risks, ensure_ascii=False)}
ESTILO DE REFERENCIA:
{style_examples[:1500]}

Responde con JSON:
{{
  "sections": [
    {{"title": "Estado General del Proyecto", "content": "...", "order": 1}},
    {{"title": "Avance por Área Funcional", "content": "...", "order": 2}},
    {{"title": "Tareas Bloqueadas y Plan de Acción", "content": "...", "order": 3}},
    {{"title": "Gestión de Riesgos", "content": "...", "order": 4}}
  ]
}}
"""
        data_json = self._call_json(prompt)
        return [
            ReportSection(
                title=s.get("title", f"Sección {i+1}"),
                content=s.get("content", ""),
                section_order=s.get("order", i+1),
            )
            for i, s in enumerate(data_json.get("sections", []))
        ]

    def _generate_conclusions(
        self, data: DailyInput, style_examples: str
    ) -> str:
        if data.report_type == ReportType.FUNCTIONAL_TESTS:
            total = len(data.test_cases)
            passed = sum(1 for t in data.test_cases if t.status == "PASS")
            failed = sum(1 for t in data.test_cases if t.status == "FAIL")
            blocked = sum(1 for t in data.test_cases if t.status == "BLOCKED")
            modules = list({t.module for t in data.test_cases if t.module})
            defects = [d for t in data.test_cases for d in (t.defects or [])]
            test_context = (
                f"- Total de casos ejecutados: {total}\n"
                f"- Aprobados: {passed} | Fallidos: {failed} | Bloqueados: {blocked}\n"
                f"- Módulos evaluados: {', '.join(modules) if modules else 'N/A'}\n"
                f"- Defectos registrados: {json.dumps(defects, ensure_ascii=False) if defects else 'Ninguno'}"
            )
        else:
            done = sum(1 for t in data.tasks if t.status == "DONE")
            total = len(data.tasks)
            test_context = (
                f"- Tareas completadas: {done}/{total}\n"
                f"- Riesgos: {json.dumps(data.risks, ensure_ascii=False)}"
            )

        prompt = f"""
Genera las CONCLUSIONES Y RECOMENDACIONES del informe.

CONTEXTO DEL PROYECTO:
- Proyecto: {data.project_name}
- Tipo de reporte: {data.report_type}
- Próximos pasos indicados: {json.dumps(data.next_steps, ensure_ascii=False)}

RESUMEN DE RESULTADOS:
{test_context}

ESTILO DE REFERENCIA:
{style_examples[:1500]}

REGLAS:
- Escribe 3 a 5 párrafos sólidos en español técnico y formal.
- Cada párrafo debe aportar una conclusión específica o una recomendación accionable.
- No uses viñetas ni listas, solo texto narrativo continuo.
- Las recomendaciones deben mencionar el módulo o área específica cuando aplique.
- Cierra con una perspectiva sobre los próximos pasos o estado de calidad del sistema.

Responde con JSON: {{"conclusions": "<texto completo de conclusiones y recomendaciones>"}}
"""
        return self._call_json(prompt).get("conclusions", "")

    # ─────────────────────────────────────────────────
    # Input Extraction (Natural Language -> DailyInput)
    # ─────────────────────────────────────────────────

    def extract_daily_input(self, user_text: str, metadata: dict) -> DailyInput:
        """
        Uses the LLM to convert a free-form natural language description
        into a structured DailyInput Pydantic model.
        """
        logger.info(f"Extracting JSON daily input from natural language...")
        
        schema = json.dumps(DailyInput.model_json_schema(), ensure_ascii=False)
        report_type = metadata.get("report_type", "functional_tests")
        
        system = f"""Eres un asistente experto en QA y documentación técnica de pruebas de software.
Tu objetivo es extraer información de las notas del usuario y convertirla en un JSON válido con el máximo nivel de detalle técnico posible.

ESQUEMA ESPERADO (JSON Schema):
{schema}

INSTRUCCIONES PARA PRUEBAS FUNCIONALES ('functional_tests'):
Debes rellenar cada campo del array 'test_cases' con ALTA PRECISIÓN Y DETALLE:

  📌 'test_id': Número secuencial (1, 2, 3…).
  📌 'module': Nombre del módulo o funcionalidad evaluada (ej. "Autenticación de Usuarios", "Gestión de Pedidos").
  📌 'test_name': Nombre descriptivo del caso (ej. "CP-01: Inicio de sesión con credenciales válidas").
  📌 'description': Párrafo técnico detallado que explique QUÉ funcionalidad se está validando, CUÁL es el objetivo de la prueba y CUÁL es el alcance. Mínimo 2 oraciones completas.
  📌 'preconditions': Lista de CONDICIONES PREVIAS específicas y verificables. Ejemplo:
      - "El usuario debe tener un rol de Administrador activo en el sistema"
      - "La base de datos de prueba debe estar poblada con registros de prueba según el set de datos QA-SET-001"
      - "El ambiente QA debe estar disponible y conectado a los servicios externos (API, email)"
  📌 'steps': Lista de PASOS NUMERADOS, atómicos, reproducibles y con suficiente detalle para que cualquier tester los ejecute sin ambigüedad. Ejemplo:
      - "Abrir el navegador e ingresar la URL https://app.qa.example.com/login"
      - "En el campo 'Usuario', ingresar el valor: admin@empresa.com"
      - "En el campo 'Contraseña', ingresar la contraseña correspondiente"
      - "Hacer clic en el botón 'Iniciar sesión'"
      - "Verificar que el sistema redirige al panel principal"
  📌 'expected_results': Lista de RESULTADOS ESPERADOS concretos y verificables, uno por comportamiento clave. Ejemplo:
      - "El sistema valida las credenciales y redirige al dashboard en menos de 3 segundos"
      - "El menú de navegación muestra las opciones correspondientes al rol Administrador"
  📌 'actual_results': Lista de LO QUE REALMENTE OCURRIÓ durante la ejecución. Describe el comportamiento observado con precisión. Si fue exitoso, confirma el comportamiento. Si falló, incluye el mensaje de error exacto o la desviación observada.
  📌 'status': PASS si todo funcionó según lo esperado, FAIL si hubo desviaciones, BLOCKED si no se pudo ejecutar.
  📌 'prepared_by' y 'tested_by': usar nombre de metadata.
  📌 'prepare_date' y 'test_date': usar fecha de metadata.

INSTRUCCIONES PARA AVANCE DE PROYECTO ('project_progress'):
- Extrae las 'tasks' con status IN_PROGRESS/DONE/BLOCKED y progress_pct estimado.
- Llena 'risks', 'next_steps' y 'general_notes' interpretando la narrativa del usuario.

REGLA CRÍTICA: Si la narrativa del usuario es breve, INFIERE y AMPLÍA el contenido de forma técnicamente coherente con el contexto dado. NUNCA dejes campos con valores genéricos como "Se realizó la prueba" o "Resultado correcto".
ESTRICTAMENTE devuelve SOLO JSON VÁLIDO basándote en el esquema.
"""

        user_prompt = f"""
METADATA OBLIGATORIA (Úsala para llenar los campos base):
- report_date: {metadata.get("report_date")}
- report_type: {report_type}
- project_name: {metadata.get("project_name")}
- environment: {metadata.get("environment")}
- prepared_by: {metadata.get("prepared_by")}

LO QUE EL USUARIO HIZO HOY:
"{user_text}"

Genera el JSON final completo:
"""

        data_json = self._provider.chat_json(
            system_prompt=system,
            user_prompt=user_prompt,
            temperature=0.2,
            max_tokens=settings.openai_max_tokens,
        )

        return DailyInput.model_validate(self._normalize_daily_input_json(data_json, metadata))

    def extract_daily_input_from_images(self, image_narratives: list[tuple[str, str]], metadata: dict) -> DailyInput:
        """
        Takes a list of (image_filename, user_narrative) pairs and builds a DailyInput
        ensuring exactly one TestCaseResult is created per image.
        """
        logger.info(f"Extracting JSON daily input from {len(image_narratives)} image narratives...")
        
        schema = json.dumps(DailyInput.model_json_schema(), ensure_ascii=False)
        report_type = metadata.get("report_type", "functional_tests")
        
        system = f"""Eres un asistente experto en QA y documentación técnica de pruebas de software.
Tu objetivo es tomar múltiples narrativas asociadas a imágenes de evidencia y construir un JSON consolidado de Pruebas de Integración ('functional_tests') con el MÁXIMO NIVEL DE DETALLE TÉCNICO POSIBLE.

ESQUEMA ESPERADO (JSON Schema):
{schema}

INSTRUCCIONES CRÍTICAS:
1. Genera exactamente UN objeto en 'test_cases' por cada imagen. NUNCA uses 'tasks'.
2. En cada test_case, asigna el nombre exacto de la imagen al campo 'evidence_image_filename'.
3. Para cada test_case, completa los campos con ALTA PRECISIÓN Y DETALLE:

   📌 'module': Módulo o funcionalidad evaluada (ej. "Gestión de Usuarios", "Módulo de Reportes").
   📌 'test_name': Nombre formal del caso (ej. "CP-01: Creación de usuario con datos válidos").
   📌 'description': Párrafo técnico que explique QUÉ se valida, CUÁL es el objetivo y el alcance. Mínimo 2 oraciones completas.
   📌 'preconditions': Lista específica de condiciones previas necesarias para ejecutar la prueba:
       - Estado del sistema requerido
       - Datos de prueba necesarios
       - Roles y permisos requeridos
       - Configuraciones previas
   📌 'steps': Lista de pasos numerados, ATÓMICOS y reproducibles. Cada paso debe indicar una acción concreta:
       - URL a navegar, campos a completar, botones a hacer clic
       - Datos de entrada específicos cuando aplique
       - Verificaciones intermedias
   📌 'expected_results': Lista de resultados esperados CONCRETOS y VERIFICABLES por comportamiento clave del sistema.
   📌 'actual_results': Descripción PRECISA de lo que realmente ocurrió. Si fue exitoso, confirma el comportamiento. Si falló, describe la desviación o el mensaje de error exacto observado en la imágen.
   📌 'status': PASS / FAIL / BLOCKED según lo observado.

4. Llena 'prepared_by' y 'tested_by' con el nombre de la metadata.
5. Llena 'prepare_date' y 'test_date' con la fecha de la metadata.
6. Si la narrativa es breve, INFIERE y AMPLÍA el contenido de forma coherente. NUNCA uses valores genéricos como "Se realizó la prueba" o "Resultado correcto".
7. ESTRICTAMENTE devuelve SOLO JSON VÁLIDO sin markdown extra. El reporte debe ser de tipo 'functional_tests'.
"""
        
        narratives_block = ""
        for i, (filename, text) in enumerate(image_narratives, 1):
            narratives_block += f"--- IMAGEN {i}: {filename} ---\nNARRATIVA DEL USUARIO:\n{text}\n\n"

        user_prompt = f"""
METADATA OBLIGATORIA (Úsala para llenar los campos base):
- report_date: {metadata.get("report_date")}
- report_type: {report_type}
- project_name: {metadata.get("project_name")}
- environment: {metadata.get("environment")}
- prepared_by: {metadata.get("prepared_by")}

NARRATIVAS ASOCIADAS A LAS IMÁGENES:
{narratives_block}

Genera el JSON final completo agrupando todos los test_cases:
"""

        data_json = self._provider.chat_json(
            system_prompt=system,
            user_prompt=user_prompt,
            temperature=0.2,
            max_tokens=settings.openai_max_tokens,
        )

        return DailyInput.model_validate(self._normalize_daily_input_json(data_json, metadata))
    
    # ─────────────────────────────────────────────────
    # Normalization helpers
    # ─────────────────────────────────────────────────

    @staticmethod
    def _normalize_daily_input_json(data: dict, metadata: dict | None = None) -> dict:
        LIST_STR_FIELDS = ("preconditions", "steps", "expected_results", "actual_results", "defects")

        REPORT_TYPE_ALIASES = {
            "functional_tests": "functional_tests",
            "pruebas_funcionales": "functional_tests",
            "pruebas funcionales": "functional_tests",
            "functional": "functional_tests",
            "project_progress": "project_progress",
            "avance_proyecto": "project_progress",
            "avance de proyecto": "project_progress",
            "project progress": "project_progress",
            "progress": "project_progress",
        }

        def _normalize_report_type(val: str | None, fallback: str = "functional_tests") -> str:
            if not val:
                return fallback
            normalized = val.strip().lower().replace("-", "_")
            return REPORT_TYPE_ALIASES.get(normalized, fallback)

        def _coerce_to_str(item) -> str:
            if isinstance(item, str):
                return item
            if isinstance(item, dict):
                for key in ("action", "description", "step", "text", "result", "value", "content"):
                    if key in item:
                        return str(item[key])
                return " ".join(str(v) for v in item.values() if v)
            return str(item)

        def _coerce_to_list_of_str(val) -> list[str]:
            if isinstance(val, list):
                return [_coerce_to_str(x) for x in val]
            if isinstance(val, str):
                return [val] if val.strip() else []
            if isinstance(val, dict):
                return [_coerce_to_str(val)]
            return []

        metadata = metadata or {}

        # Inyectar campos raíz faltantes desde metadata
        for field in ("report_date", "project_name", "prepared_by", "environment"):
            if not data.get(field) and metadata.get(field):
                data[field] = metadata[field]

        # Normalizar report_type
        fallback_report_type = _normalize_report_type(metadata.get("report_type"), "functional_tests")
        data["report_type"] = _normalize_report_type(data.get("report_type"), fallback_report_type)

        # Normalizar test_cases
        test_cases = data.get("test_cases", [])
        if isinstance(test_cases, list):
            for idx, tc in enumerate(test_cases, start=1):
                if not isinstance(tc, dict):
                    continue
                if not tc.get("test_id"):          # ← auto-asigna test_id si falta
                    tc["test_id"] = str(idx)       # Castear a string para cumplir tipo
                for field in LIST_STR_FIELDS:
                    if field in tc:
                        tc[field] = _coerce_to_list_of_str(tc[field])

        return data

    # ─────────────────────────────────────────────────
    # LLM call helper — delegates to provider
    # ─────────────────────────────────────────────────

    def _call_json(self, user_prompt: str) -> dict:
        """Delegates to the configured LLM provider and returns a JSON dict."""
        return self._provider.chat_json(
            system_prompt=SYSTEM_PROMPT,
            user_prompt=user_prompt,
            temperature=0.4,
            max_tokens=settings.openai_max_tokens,
        )
