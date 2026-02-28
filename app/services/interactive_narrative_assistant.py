from __future__ import annotations

from dataclasses import dataclass, field

from app.config import get_settings
from app.providers import get_llm_provider
from app.providers.base import LLMProvider
from app.rag.knowledge_retriever import KnowledgeRetriever
from app.utils.logger import get_logger

logger = get_logger(__name__)
settings = get_settings()

# Ordered sections and their display labels
SECTIONS: list[tuple[str, str]] = [
    ("description",       "Descripción / Objetivo"),
    ("preconditions",     "Precondiciones"),
    ("steps",             "Pasos de ejecución"),
    ("expected_results",  "Resultados esperados"),
    ("actual_results",    "Resultados reales"),
    ("status",            "Estado (PASS / FAIL / BLOCKED)"),
]

_SUGGESTION_SYSTEM = """Eres un asistente técnico de QA que ayuda a redactar casos de prueba profesionales.
Tu tarea es generar una propuesta de texto para una sección específica de un caso de prueba de software.

REGLAS:
- Responde en español técnico y formal.
- Basa tu sugerencia en el contexto de pruebas pasadas provisto (si existe).
- Ten en cuenta las secciones ya completadas en esta sesión para mantener coherencia.
- IMPORTANTE: Adapta estrictamente tu sugerencia a la información que el usuario ya ha ingresado en "SECCIONES YA COMPLETADAS". Si el usuario ingresó datos específicos, pasos o precondiciones, tu sugerencia debe continuar lógicamente esa misma narrativa.
- Genera texto concreto, no genérico. Usa nombres de campos, módulos o funcionalidades reales cuando estén disponibles.
- Para listas (preconditions, steps, expected_results, actual_results): devuelve cada ítem en una línea separada con " - " al inicio.
- Para "status": devuelve únicamente PASS, FAIL o BLOCKED.
- Para "description": devuelve un párrafo de 2-3 oraciones.
- NUNCA uses frases vacías como "Se realizó la prueba" o "Resultado correcto".
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

    def to_dict(self) -> dict:
        return {
            "module":            self.module,
            "test_name":         self.test_name,
            "description":       self.description,
            "preconditions":     self.preconditions,
            "steps":             self.steps,
            "expected_results":  self.expected_results,
            "actual_results":    self.actual_results,
            "status":            self.status,
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

    For each section it:
    1. Queries project_knowledge RAG for similar past test cases
       (recency-boosted so recent notes surface first).
    2. Asks the LLM to generate a suggestion based on RAG context + sections already filled.
    3. Returns the suggestion so the CLI can display it and let the user accept or override it.
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
    ) -> str:
        """
        Generate an AI suggestion for `section_key` given the current draft state.

        Returns:
            A suggestion string. For list-type fields it is a newline-separated
            list prefixed with ' - '. For status it is PASS/FAIL/BLOCKED.
        """
        # Build a dynamic RAG query incorporating recent user inputs
        query_parts = [f"caso de prueba {draft.module} {draft.test_name}"]

        # Add context from immediately preceding sections to steer the RAG search
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

        section_label  = dict(SECTIONS).get(section_key, section_key)
        context_so_far = draft.as_context_so_far()

        user_prompt = self._build_prompt(
            section_key=section_key,
            section_label=section_label,
            module=draft.module,
            test_name=draft.test_name,
            context_so_far=context_so_far,
            rag_context=rag_context,
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
    ) -> str:
        rag_block = (
            f"CASOS DE PRUEBA SIMILARES DEL HISTORIAL:\n{rag_context}"
            if rag_context
            else "No se encontraron casos similares en el historial."
        )

        list_instruction = (
            "Si es una lista, separa cada ítem con salto de línea y prefijo ' - '."
            if section_key not in ("description", "status")
            else ""
        )
        status_instruction = (
            "Devuelve solo PASS, FAIL o BLOCKED."
            if section_key == "status"
            else ""
        )

        return (
            f'Necesito una sugerencia para la sección "{section_label}" '
            f"del siguiente caso de prueba.\n\n"
            f"MÓDULO: {module}\n"
            f"CASO: {test_name}\n\n"
            f"{rag_block}\n\n"
            f"SECCIONES YA COMPLETADAS EN ESTA SESIÓN:\n"
            f"{context_so_far if context_so_far else '(ninguna aún)'}\n\n"
            f'Genera ÚNICAMENTE el contenido para la sección "{section_label}".\n'
            f"{list_instruction}\n"
            f"{status_instruction}\n\n"
            f'Responde con JSON: {{"suggestion": "<texto de la sugerencia>"}}'
        )


# ─────────────────────────────────────────────────
# Helpers for CLI consumption
# ─────────────────────────────────────────────────

def parse_list_suggestion(suggestion: str) -> list[str]:
    """
    Convert a suggestion string like:
        ' - Paso uno\n - Paso dos\n - Paso tres'
    into:
        ['Paso uno', 'Paso dos', 'Paso tres']
    """
    lines  = suggestion.strip().splitlines()
    result = []
    for line in lines:
        stripped = line.strip().lstrip("-").lstrip("•").strip()
        if stripped:
            result.append(stripped)
    return result


LIST_SECTIONS = {"preconditions", "steps", "expected_results", "actual_results"}