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
        logger.info(f"Generating report for {daily_input.report_date} | {daily_input.report_type}")

        style_examples = style_context.as_context_string

        # Executive summary is not rendered for test reports (summary is in the table)
        if daily_input.report_type in (
            ReportType.FUNCTIONAL_TESTS,
            ReportType.INTEGRATION_TESTS,
            ReportType.UNIT_TESTS,
        ):
            executive_summary = ""
        else:
            executive_summary = self._generate_executive_summary(daily_input, style_examples)
        sections   = self._generate_sections(daily_input, style_examples)
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
        _TEST_TYPES = {ReportType.FUNCTIONAL_TESTS, ReportType.INTEGRATION_TESTS, ReportType.UNIT_TESTS}
        if data.report_type in _TEST_TYPES:
            total   = len(data.test_cases)
            passed  = sum(1 for t in data.test_cases if t.status == "PASS")
            failed  = sum(1 for t in data.test_cases if t.status == "FAIL")
            blocked = sum(1 for t in data.test_cases if t.status == "BLOCKED")

            type_desc = {
                ReportType.FUNCTIONAL_TESTS:  "pruebas funcionales (Caja Negra)",
                ReportType.INTEGRATION_TESTS: "pruebas de integración (Caja Negra + Blanca)",
                ReportType.UNIT_TESTS:        "pruebas unitarias (Caja Blanca)",
            }.get(data.report_type, "pruebas")

            # Extra metrics for white-box types
            extra = ""
            if data.report_type in (ReportType.INTEGRATION_TESTS, ReportType.UNIT_TESTS):
                avg_cov = sum(t.coverage_pct or 0 for t in data.test_cases) / max(total, 1)
                extra = f"- Cobertura promedio lograda: {avg_cov:.1f}%\n"

            user_prompt = f"""
Genera el RESUMEN EJECUTIVO de un informe de {type_desc}.

DATOS:
- Proyecto: {data.project_name} v{data.project_version}
- Fecha: {data.report_date}
- Ambiente: {data.environment}
- Total casos: {total} | Exitosos: {passed} | Fallidos: {failed} | Bloqueados: {blocked}
{extra}- Responsable: {data.prepared_by}

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
        _TEST_TYPES = {ReportType.FUNCTIONAL_TESTS, ReportType.INTEGRATION_TESTS, ReportType.UNIT_TESTS}
        # For test reports, all content goes into the per-case tables — no body sections needed
        if data.report_type in _TEST_TYPES:
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
        _TEST_TYPES = {ReportType.FUNCTIONAL_TESTS, ReportType.INTEGRATION_TESTS, ReportType.UNIT_TESTS}
        if data.report_type in _TEST_TYPES:
            total   = len(data.test_cases)
            passed  = sum(1 for t in data.test_cases if t.status == "PASS")
            failed  = sum(1 for t in data.test_cases if t.status == "FAIL")
            blocked = sum(1 for t in data.test_cases if t.status == "BLOCKED")
            defects = [d for t in data.test_cases for d in (t.defects or [])]

            extra_context = ""
            if data.report_type == ReportType.INTEGRATION_TESTS:
                techniques = list({t.test_technique for t in data.test_cases if t.test_technique})
                avg_cov    = sum(t.coverage_pct or 0 for t in data.test_cases) / max(total, 1)
                extra_context = (
                    f"- Técnicas empleadas: {', '.join(techniques) or 'N/A'}\n"
                    f"- Cobertura promedio: {avg_cov:.1f}%\n"
                )
            elif data.report_type == ReportType.UNIT_TESTS:
                frameworks  = list({t.test_framework for t in data.test_cases if t.test_framework})
                avg_cov     = sum(t.coverage_pct or 0 for t in data.test_cases) / max(total, 1)
                extra_context = (
                    f"- Frameworks de prueba: {', '.join(frameworks) or 'N/A'}\n"
                    f"- Cobertura promedio: {avg_cov:.1f}%\n"
                )

            type_desc = {
                ReportType.FUNCTIONAL_TESTS:  "pruebas funcionales",
                ReportType.INTEGRATION_TESTS: "pruebas de integración",
                ReportType.UNIT_TESTS:        "pruebas unitarias",
            }.get(data.report_type, "pruebas")

            test_context = (
                f"- Total de casos ejecutados: {total}\n"
                f"- Aprobados: {passed} | Fallidos: {failed} | Bloqueados: {blocked}\n"
                f"- Defectos registrados: {json.dumps(defects, ensure_ascii=False) if defects else 'Ninguno'}\n"
                f"{extra_context}"
            )
        else:
            type_desc    = "avance de proyecto"
            done         = sum(1 for t in data.tasks if t.status == "DONE")
            total        = len(data.tasks)
            test_context = (
                f"- Tareas completadas: {done}/{total}\n"
                f"- Riesgos: {json.dumps(data.risks, ensure_ascii=False)}"
            )

        prompt = f"""
Genera las CONCLUSIONES Y RECOMENDACIONES del informe de {type_desc}.

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

─── INSTRUCCIONES PRUEBAS FUNCIONALES ('functional_tests') ─ CAJA NEGRA ───
Debes rellenar cada campo del array 'test_cases' con ALTA PRECISIÓN Y DETALLE:
  📌 'test_technique': Técnica de caja negra: partición de equivalencia, análisis de valores límite, tabla de decisiones o transición de estados.
  📌 'input_data': Lista de VALORES DE ENTRADA EXACTOS utilizados (ej. usuario=admin@qa.com, monto=0.01).
  📌 'module', 'test_name', 'description': documentar el comportamiento externo observable sin revelar código interno.
  📌 'preconditions', 'steps', 'expected_results', 'actual_results': mismas reglas detalladas de siempre.
  📌 'status': PASS / FAIL / BLOCKED.
  📌 Los campos de Caja Blanca (covered_method, covered_class, coverage_type, coverage_pct, test_framework) deben dejarse vacíos / 0.

─── INSTRUCCIONES PRUEBAS DE INTEGRACIÓN ('integration_tests') ─ CAJA NEGRA + BLANCA ───
  📌 Caja Negra:
    - 'test_technique': Técnica usada para diseñar los datos de prueba.
    - 'input_data': Lista de entradas específicas enviadas a la interfaz o API.
  📌 Caja Blanca:
    - 'covered_method': método o endpoint integrado (ej. POST /api/v1/orders, UserService.createOrder()).
    - 'coverage_type': rama (branch) / sentencia (statement) / condición / camino.
    - 'coverage_pct': porcentaje numérico de cobertura logrado (ej. 78.5).
  📌 Ambas cajas:
    - 'description': combina perspectiva de flujo entre módulos (qué se integra) con los datos de entrada.
    - 'test_level': 'Integration'.

─── INSTRUCCIONES PRUEBAS UNITARIAS ('unit_tests') ─ CAJA BLANCA ───
  📌 'covered_class': ruta de clase/módulo (ej. app.services.UserService, com.empresa.api.AuthController).
  📌 'covered_method': firma del método o función bajo prueba (ej. validate_token(token: str) -> bool).
  📌 'test_framework': framework y versión (ej. pytest 8.1, JUnit 5, Jest 29).
  📌 'coverage_type': branch / statement / condition / path.
  📌 'coverage_pct': porcentaje numérico de cobertura alcanzado.
  📌 'test_level': 'Unit'.
  📌 'description': describe la lógica interna del método, no el comportamiento externo.
  📌 Los campos de Caja Negra (input_data, test_technique) pueden dejarse vacíos.

─── INSTRUCCIONES AVANCE DE PROYECTO ('project_progress') ───
- Extrae las 'tasks' con status IN_PROGRESS/DONE/BLOCKED y progress_pct estimado.
- Llena 'risks', 'next_steps' y 'general_notes' interpretando la narrativa del usuario.

REGLA CRÍTICA: Si la narrativa del usuario es breve, INFIERE y AMPLÍA el contenido de forma técnicamente coherente. NUNCA dejes campos genéricos como "Se realizó la prueba".
ESTRICTAMENTE devuelve SOLO JSON VÁLIDO basado en el esquema.
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
            "functional_tests":   "functional_tests",
            "pruebas_funcionales":"functional_tests",
            "pruebas funcionales":"functional_tests",
            "functional":         "functional_tests",
            "integration_tests":  "integration_tests",
            "pruebas_integracion":"integration_tests",
            "pruebas integracion":"integration_tests",
            "integracion":        "integration_tests",
            "integration":        "integration_tests",
            "unit_tests":         "unit_tests",
            "pruebas_unitarias":  "unit_tests",
            "pruebas unitarias":  "unit_tests",
            "unitarias":          "unit_tests",
            "unit":               "unit_tests",
            "project_progress":   "project_progress",
            "avance_proyecto":    "project_progress",
            "avance de proyecto": "project_progress",
            "project progress":   "project_progress",
            "progress":           "project_progress",
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
    # Note Consolidation
    # ─────────────────────────────────────────────────

    def merge_notes(self, new_note: str, existing_notes: list[str]) -> str:
        """
        Ask the LLM to synthesize ``new_note`` and one or more ``existing_notes``
        into a single, comprehensive, up-to-date note.

        The merged result preserves all relevant knowledge, resolves
        contradictions by favouring the newest information (new_note), and
        removes redundant or outdated statements.  Returns the merged note as
        plain text.
        """
        existing_block = "\n\n".join(
            f"--- NOTA EXISTENTE {i + 1} ---\n{note}"
            for i, note in enumerate(existing_notes)
        )

        prompt = f"""Eres un asistente especializado en gestión del conocimiento técnico de proyectos de software.

Tu tarea es CONSOLIDAR las siguientes notas en UNA SOLA nota unificada, clara y sin redundancias.

REGLAS DE CONSOLIDACIÓN:
- Preserva TODA la información relevante de cada nota.
- Si hay contradicciones, prioriza la información de la NOTA NUEVA (es la más reciente).
- Elimina repeticiones y frases redundantes.
- Mantén el tono técnico y formal.
- El resultado debe ser un texto continuo y cohesivo, NO una lista de viñetas.
- No incluyas encabezados como "NOTA CONSOLIDADA:" ni prefijos de fecha — eso lo añade el sistema.

NOTAS EXISTENTES:
{existing_block}

NOTA NUEVA (más reciente — tiene prioridad en caso de contradicción):
{new_note}

Responde con JSON: {{"merged_note": "<texto consolidado completo>"}}
"""
        return self._call_json(prompt).get("merged_note", new_note)

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