from __future__ import annotations

from app.config import get_settings
from app.providers import get_llm_provider
from app.providers.base import LLMProvider
from app.rag.embedding_service import EmbeddingService
from app.rag.vector_store import VectorStore
from app.utils.logger import get_logger

logger = get_logger(__name__)
settings = get_settings()

_NOTE_BOOST = 1.50

_ANSWER_SYSTEM = """Eres un asistente técnico experto en el proyecto de software descrito en el contexto.
Tu misión es responder preguntas sobre el historial del proyecto, el estado de módulos, pruebas anteriores, decisiones técnicas y documentación de clases/métodos de código.

FUENTES DE CONOCIMIENTO DISPONIBLES:
- Notas manuales del usuario ([NOTA DEL USUARIO]) — máxima prioridad.
- Reportes de contexto (.docx) que pueden incluir arquitectura, API, clases, métodos, módulos.

REGLA DE PRIORIDAD (CRÍTICA):
- Los fragmentos etiquetados como [NOTA DEL USUARIO] representan el estado MÁS RECIENTE y son la verdad absoluta.
- Si hay información contradictoria entre un [NOTA DEL USUARIO] y un [REPORTE], la nota ANULA al reporte.
- Cuando respondas con información de una nota, debes indicarlo: "Según la nota del usuario del <fecha>...".
- Si un reporte contradice una nota, puedes mencionarlo como contexto histórico, pero deja claro que la nota es la versión vigente.

OTRAS REGLAS:
- Responde SOLO basándote en el contexto provisto. No inventes información.
- Si el contexto menciona clases, métodos o módulos de código, detállalos con precisión incluyendo sus parámetros, retornos y propósito.
- Sé técnico, preciso y conciso.
- Si el contexto no contiene suficiente información, indícalo claramente y sugiere al usuario ampliar la base de conocimiento.
- Cita siempre la fuente del fragmento (ej. "Según el reporte informe_2024-03-15.docx...").
- Responde en español."""


class KnowledgeRetriever:
    """
    Retrieves relevant fragments from the `project_knowledge` ChromaDB collection
    and uses the LLM to synthesize an answer.

    Recency Weighting:
    - Fragments with metadata type="note" get their relevance_score boosted 1.5x.
    - Re-ranked list is sorted and passed to the LLM.
    - System prompt instructs the LLM to treat [NOTA DEL USUARIO] as authoritative.

    Multi-turn:
    - answer_with_history() accepts a conversation history list so the LLM maintains
      coherence across questions in the same CLI session.
    - RAG context is fetched fresh on every turn (new search per question).
    - Falls back gracefully if the provider doesn't implement chat_json_with_history.
    """

    def __init__(self, provider: LLMProvider | None = None) -> None:
        self._vs         = VectorStore()
        self._emb        = EmbeddingService()
        self._provider   = provider or get_llm_provider()
        self._collection = settings.chroma_collection_knowledge

    # ─────────────────────────────────────────────────
    # Public API
    # ─────────────────────────────────────────────────

    def answer(self, question: str, top_k: int = 10) -> str:
        """Single-turn stateless Q&A (delegates to answer_with_history with empty history)."""
        return self.answer_with_history(question, history=[], top_k=top_k)

    def answer_with_history(
        self,
        question: str,
        history: list[dict],
        top_k: int = 10,
    ) -> str:
        """Proxies context retrieval to TestRAGSystem, but answers using LLMProvider."""
        from app.rag.rag_system import TestRAGSystem
        # We don't pass an LLM callable to TestRAGSystem because we just
        # want to use it to retrieve the chunks and intent.
        sys = TestRAGSystem()
        
        # 1. Retrieve chunks using the V2 router
        result = sys._router.route(question, sys._collections, top_k=top_k)
        
        if not result.chunks:
            return (
                "No se encontró información relevante en la base de conocimiento "
                "para responder esta pregunta. Considera alimentar el sistema con "
                "más notas o reportes del proyecto."
            )

        # 2. Build context block
        context_block = sys._build_context(result.chunks)

        # 3. Build prompts
        user_prompt = (
            "CONTEXTO DEL PROYECTO (fragmentos recuperados para esta pregunta):\n"
            f"{context_block}\n\n"
            f"PREGUNTA:\n{question}\n\n"
            "Responde basándote en el contexto anterior y en el historial de la conversación.\n\n"
            'Responde con JSON: {"answer": "<respuesta completa>"}'
        )

        # 4. Call the LLM
        try:
            # Preferred path: provider supports multi-turn natively
            response = self._provider.chat_json_with_history(
                system_prompt=_ANSWER_SYSTEM,
                history=history,
                user_prompt=user_prompt,
                temperature=0.3,
                max_tokens=1500,
            )
        except AttributeError:
            # Fallback: inject history as plain text into the user_prompt
            history_block = self._history_to_text(history)
            fallback_prompt = (
                (f"HISTORIAL DE CONVERSACIÓN PREVIA:\n{history_block}\n\n" if history_block else "")
                + user_prompt
            )
            response = self._provider.chat_json(
                system_prompt=_ANSWER_SYSTEM,
                user_prompt=fallback_prompt,
                temperature=0.3,
                max_tokens=1500,
            )

        return response.get("answer", "No se pudo generar una respuesta.")

    def retrieve_for_suggestion(self, query: str, top_k: int = 8) -> str:
        """Retrieve context for test-case suggestions.

        Bypasses the router's intent detection (which misclassifies
        suggestion queries as 'wants test') and queries project_docs
        directly, prioritising method documentation so the LLM never
        needs to invent method names.
        """
        from app.rag.rag_system import TestRAGSystem
        sys = TestRAGSystem()
        embedding = self._emb.embed(query)

        all_chunks: list[dict] = []
        col = "project_docs"

        # 1. Method docs — highest priority for grounding method names
        method_chunks = sys._router._query_collection(
            col, embedding, top_k, where={"doc_type": "method_doc"},
        )
        all_chunks.extend(method_chunks)

        # 2. General project docs (may include architecture, flows, etc.)
        general_chunks = sys._router._query_collection(
            col, embedding, top_k,
        )
        all_chunks.extend(general_chunks)

        # 3. Daily notes (user knowledge, recent context)
        note_chunks = sys._router._query_collection(
            col, embedding, 3, where={"is_daily_note": True},
        )
        if note_chunks:
            all_chunks = note_chunks + all_chunks

        # Deduplicate by id
        seen: set[str] = set()
        unique: list[dict] = []
        for c in all_chunks:
            cid = c.get("id", str(id(c)))
            if cid not in seen:
                seen.add(cid)
                unique.append(c)

        if not unique:
            return ""
        return sys._build_context(unique[:top_k])

    @staticmethod
    def _history_to_text(history: list[dict]) -> str:
        """Convert history list to readable block for fallback injection."""
        lines = []
        for msg in history:
            role    = "Usuario" if msg.get("role") == "user" else "Asistente"
            content = msg.get("content", "")
            lines.append(f"{role}: {content}")
        return "\n".join(lines)