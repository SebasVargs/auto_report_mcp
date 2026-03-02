from __future__ import annotations

from dataclasses import dataclass, field
from typing import Literal

from app.config import get_settings
from app.providers import get_llm_provider
from app.providers.base import LLMProvider
from app.rag.knowledge_retriever import KnowledgeRetriever
from app.utils.logger import get_logger

logger = get_logger(__name__)
settings = get_settings()

# ─────────────────────────────────────────────────
# Sections per report type
# ─────────────────────────────────────────────────

# Functional Tests — Caja Negra only
SECTIONS_FUNCTIONAL: list[tuple[str, str]] = [
    ("description",      "Descripción / Objetivo"),
    ("preconditions",    "Precondiciones"),
    ("steps",            "Pasos de ejecución"),
    ("input_data",       "Datos de entrada (Caja Negra)"),
    ("expected_results", "Resultados esperados"),
    ("actual_results",   "Resultados reales"),
    ("status",           "Estado (PASS / FAIL / BLOCKED)"),
]

# Integration Tests — Caja Negra + Caja Blanca
SECTIONS_INTEGRATION: list[tuple[str, str]] = [
    ("description",      "Descripción / Objetivo"),
    ("test_technique",   "Técnica de prueba (ej. partición equivalencia, valores límite)"),
    ("preconditions",    "Precondiciones"),
    ("steps",            "Pasos de ejecución"),
    ("input_data",       "Datos de entrada (Caja Negra)"),
    ("covered_method",   "Método / Endpoint integrado (Caja Blanca)"),
    ("coverage_type",    "Tipo de cobertura (rama / sentencia / condición)"),
    ("expected_results", "Resultados esperados"),
    ("actual_results",   "Resultados reales"),
    ("status",           "Estado (PASS / FAIL / BLOCKED)"),
]

# Unit Tests — Caja Blanca only
SECTIONS_UNIT: list[tuple[str, str]] = [
    ("description",      "Descripción / Objetivo"),
    ("covered_class",    "Clase / Módulo bajo prueba"),
    ("covered_method",   "Método / Función bajo prueba"),
    ("test_framework",   "Framework de prueba (pytest, JUnit, Mocha…)"),
    ("coverage_type",    "Tipo de cobertura (rama / sentencia / condición / camino)"),
    ("coverage_pct",     "Porcentaje de cobertura logrado (%)"),
    ("preconditions",    "Precondiciones / Setup"),
    ("steps",            "Pasos de ejecución"),
    ("expected_results", "Resultado esperado"),
    ("actual_results",   "Resultado real"),
    ("status",           "Estado (PASS / FAIL / BLOCKED)"),
]

# Legacy alias kept for callers that still use SECTIONS directly
SECTIONS = SECTIONS_FUNCTIONAL

def get_sections_for_type(report_type: str) -> list[tuple[str, str]]:
    """Return the ordered section list for a given report type."""
    if report_type == "integration_tests":
        return SECTIONS_INTEGRATION
    if report_type == "unit_tests":
        return SECTIONS_UNIT
    return SECTIONS_FUNCTIONAL

# Fields that accept a list (bullet / numbered) rather than plain text
LIST_SECTIONS = {"preconditions", "steps", "expected_results", "actual_results", "input_data"}
# Fields that are numeric (we ask for a number, not free text)
NUMERIC_SECTIONS = {"coverage_pct"}
# Status is a fixed-choice field
STATUS_SECTIONS = {"status"}


_SUGGESTION_SYSTEM = """Eres un asistente técnico de QA que ayuda a redactar casos de prueba profesionales.
Tu tarea es generar una propuesta de texto para una sección específica de un caso de prueba de software.

REGLAS GENERALES:
- Responde en español técnico y formal.
- Basa tu sugerencia en el contexto de pruebas pasadas provisto (si existe).
- Ten en cuenta las secciones ya completadas en esta sesión para mantener coherencia.
- IMPORTANTE: Adapta estrictamente tu sugerencia a la información que el usuario ya ha ingresado en "SECCIONES YA COMPLETADAS".
- Genera texto concreto, no genérico. Usa nombres de campos, módulos o funcionalidades reales cuando estén disponibles.
- Para listas (preconditions, steps, expected_results, actual_results, input_data): devuelve cada ítem en una línea separada con " - " al inicio.
- Para "status": devuelve únicamente PASS, FAIL o BLOCKED.
- Para "description": devuelve un párrafo de 2-3 oraciones.
- NUNCA uses frases vacías como "Se realizó la prueba" o "Resultado correcto".

REGLAS PRUEBAS FUNCIONALES (Caja Negra):
- Enfócate en comportamiento externo observable, sin mencionar implementación interna.
- Para "input_data": especifica valores exactos de entrada (ej. usuario="admin@qa.com", contraseña="Test@123").
- Para "test_technique": sugiere partición equivalencia, valores límite, tabla de decisión o prueba de transición de estado.

REGLAS PRUEBAS DE INTEGRACIÓN (Caja Negra + Caja Blanca):
- Combina la perspectiva de flujo entre módulos (blanca) con los datos de entrada (negra).
- Para "covered_method": indica el endpoint o método exacto (ej. POST /api/users, UserService.createUser()).
- Para "coverage_type": branch, statement, condition o path según corresponda.

REGLAS PRUEBAS UNITARIAS (Caja Blanca):
- Enfócate exclusivamente en la lógica interna del método/función.
- Para "covered_class": usa notación de paquete/clase (ej. app.services.UserService).
- Para "covered_method": usa firma del método (ej. validate_email(email: str) -> bool).
- Para "coverage_pct": devuelve solo el número (ej. 87.5).
- Para "test_framework": indica el framework exacto con versión si es conocida.
"""


@dataclass
class TestCaseDraft:
    """Accumulates the user's inputs for a single test case."""
    module:           str = ""
    test_name:        str = ""
    description:      str = ""
    preconditions:    list[str] = field(default_factory=list)
    steps:            list[str] = field(default_factory=list)
    expected_results: list[str] = field(default_factory=list)
    actual_results:   list[str] = field(default_factory=list)
    status:           str = "PASS"
    # Black-box
    test_technique:   str = ""
    test_level:       str = ""
    input_data:       list[str] = field(default_factory=list)
    # White-box
    covered_method:   str = ""
    covered_class:    str = ""
    coverage_type:    str = ""
    coverage_pct:     float = 0.0
    test_framework:   str = ""

    def to_dict(self) -> dict:
        return {
            "module":           self.module,
            "test_name":        self.test_name,
            "description":      self.description,
            "preconditions":    self.preconditions,
            "steps":            self.steps,
            "expected_results": self.expected_results,
            "actual_results":   self.actual_results,
            "status":           self.status,
            "test_technique":   self.test_technique,
            "test_level":       self.test_level,
            "input_data":       self.input_data,
            "covered_method":   self.covered_method,
            "covered_class":    self.covered_class,
            "coverage_type":    self.coverage_type,
            "coverage_pct":     self.coverage_pct,
            "test_framework":   self.test_framework,
        }

    def as_context_so_far(self) -> str:
        """Serializes filled fields for use as prompt context."""
        parts = []
        if self.module:
            parts.append(f"Módulo: {self.module}")
        if self.test_name:
            parts.append(f"Caso: {self.test_name}")
        if self.description:
            parts.append(f"Descripción: {self.description}")
        if self.test_technique:
            parts.append(f"Técnica: {self.test_technique}")
        if self.covered_class:
            parts.append(f"Clase: {self.covered_class}")
        if self.covered_method:
            parts.append(f"Método: {self.covered_method}")
        if self.test_framework:
            parts.append(f"Framework: {self.test_framework}")
        if self.coverage_type:
            parts.append(f"Tipo cobertura: {self.coverage_type}")
        if self.input_data:
            parts.append("Datos de entrada:\n" + "\n".join(f"  - {d}" for d in self.input_data))
        if self.preconditions:
            parts.append("Precondiciones:\n" + "\n".join(f"  - {p}" for p in self.preconditions))
        if self.steps:
            parts.append("Pasos:\n" + "\n".join(f"  - {s}" for s in self.steps))
        if self.expected_results:
            parts.append("Resultados esperados:\n" + "\n".join(f"  - {r}" for r in self.expected_results))
        return "\n".join(parts)


class InteractiveNarrativeAssistant:
    """
    Guides the user through filling each section of a test case one by one.
    Supports functional_tests, integration_tests and unit_tests report types.
    """

    def __init__(self, provider: LLMProvider | None = None) -> None:
        self._retriever = KnowledgeRetriever(provider=provider)
        self._provider  = provider or get_llm_provider()

    # ─────────────────────────────────────────────────
    # Public API
    # ─────────────────────────────────────────────────

    def get_suggestion(
        self,
        section_key: str,
        draft: TestCaseDraft,
        report_type: str = "functional_tests",
    ) -> str:
        """Generate an AI suggestion for `section_key` given the current draft state."""
        query_parts = [f"caso de prueba {draft.module} {draft.test_name}"]

        # Steer RAG search with type-specific terms
        if report_type == "integration_tests":
            query_parts.append("integración dependencia módulo cobertura")
        elif report_type == "unit_tests":
            query_parts.append("prueba unitaria cobertura sentencia rama")
        else:
            query_parts.append("funcionalidad caja negra equivalencia")

        if section_key == "preconditions" and draft.description:
            query_parts.append(draft.description)
        elif section_key == "steps" and draft.preconditions:
            query_parts.append(" ".join(draft.preconditions[-2:]))
        elif section_key == "expected_results" and draft.steps:
            query_parts.append(" ".join(draft.steps[-2:]))
        elif section_key in ("actual_results", "status") and draft.expected_results:
            query_parts.append(" ".join(draft.expected_results[-2:]))

        rag_query   = " ".join(query_parts)[:500] + f" {section_key}"
        rag_context = self._retriever.retrieve_for_suggestion(rag_query, top_k=4)

        all_sections  = get_sections_for_type(report_type)
        section_label = dict(all_sections).get(section_key, section_key)
        context_so_far = draft.as_context_so_far()

        user_prompt = self._build_prompt(
            section_key=section_key,
            section_label=section_label,
            module=draft.module,
            test_name=draft.test_name,
            context_so_far=context_so_far,
            rag_context=rag_context,
            report_type=report_type,
        )

        try:
            result = self._provider.chat_json(
                system_prompt=_SUGGESTION_SYSTEM,
                user_prompt=user_prompt,
                temperature=0.35,
                max_tokens=600,
            )
            return result.get("suggestion", "")
        except Exception as e:
            logger.warning(f"Suggestion generation failed for section '{section_key}': {e}")
            return ""

    # ─────────────────────────────────────────────────
    # Prompt builder
    # ─────────────────────────────────────────────────

    @staticmethod
    def _build_prompt(
        section_key: str,
        section_label: str,
        module: str,
        test_name: str,
        context_so_far: str,
        rag_context: str,
        report_type: str = "functional_tests",
    ) -> str:
        rag_block = (
            f"CASOS DE PRUEBA SIMILARES DEL HISTORIAL:\n{rag_context}"
            if rag_context
            else "No se encontraron casos similares en el historial."
        )

        list_instruction = (
            "Si es una lista, separa cada ítem con salto de línea y prefijo ' - '."
            if section_key in LIST_SECTIONS
            else ""
        )
        status_instruction = (
            "Devuelve solo PASS, FAIL o BLOCKED."
            if section_key == "status"
            else ""
        )
        numeric_instruction = (
            "Devuelve solo el número (ej. 87.5). Sin texto adicional."
            if section_key in NUMERIC_SECTIONS
            else ""
        )

        type_label_map = {
            "functional_tests":  "Pruebas Funcionales (Caja Negra)",
            "integration_tests": "Pruebas de Integración (Caja Negra + Blanca)",
            "unit_tests":        "Pruebas Unitarias (Caja Blanca)",
        }
        type_label = type_label_map.get(report_type, report_type)

        return (
            f'Necesito una sugerencia para la sección "{section_label}" '
            f"del siguiente caso de prueba.\n\n"
            f"TIPO DE INFORME: {type_label}\n"
            f"MÓDULO: {module}\n"
            f"CASO: {test_name}\n\n"
            f"{rag_block}\n\n"
            f"SECCIONES YA COMPLETADAS EN ESTA SESIÓN:\n"
            f"{context_so_far if context_so_far else '(ninguna aún)'}\n\n"
            f'Genera ÚNICAMENTE el contenido para la sección "{section_label}".\n'
            f"{list_instruction}\n"
            f"{status_instruction}\n"
            f"{numeric_instruction}\n\n"
            f'Responde con JSON: {{"suggestion": "<texto de la sugerencia>"}}'
        )


# ─────────────────────────────────────────────────
# Helpers for CLI consumption
# ─────────────────────────────────────────────────

def parse_list_suggestion(suggestion: str) -> list[str]:
    """
    Convert a suggestion string like:
        ' - Paso uno\n - Paso dos'
    into:
        ['Paso uno', 'Paso dos']
    """
    lines  = suggestion.strip().splitlines()
    result = []
    for line in lines:
        stripped = line.strip().lstrip("-").lstrip("•").strip()
        if stripped:
            result.append(stripped)
    return result