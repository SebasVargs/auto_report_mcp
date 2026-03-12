"""
method_validator.py — Validador de métodos para evitar alucinaciones del LLM.

Construye un registro de métodos reales desde los documentos indexados
y detecta cuando el LLM inventa métodos que no existen.
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field

from app.rag.vector_store import VectorStore
from app.rag.rag_schema import CollectionName
from app.utils.logger import get_logger

logger = get_logger(__name__)

# Patrones para extraer llamadas a métodos del texto generado por el LLM
_METHOD_CALL_PATTERNS = [
    re.compile(r"\.(\w+)\s*\("),                                # .method()
    re.compile(r"(?:self\.|this\.)(\w+)\s*\("),                  # self.method() / this.method()
    re.compile(r"def\s+(test_\w+)\s*\("),                        # def test_xxx() — skip
]

# Métodos built-in o comunes que no deben considerarse alucinaciones
_BUILTIN_METHODS = frozenset({
    "append", "extend", "insert", "remove", "pop", "clear", "sort", "reverse",
    "get", "set", "keys", "values", "items", "update", "copy",
    "join", "split", "strip", "replace", "lower", "upper", "format", "encode",
    "decode", "startswith", "endswith", "find", "count", "index",
    "add", "discard", "union", "intersection",
    "read", "write", "close", "flush", "seek",
    "print", "len", "str", "int", "float", "bool", "list", "dict", "tuple",
    "isinstance", "hasattr", "getattr", "setattr", "type",
    "assertEqual", "assertTrue", "assertFalse", "assertRaises",
    "assertIsNone", "assertIsNotNone", "assertEquals",
    "assert_called", "assert_called_once", "assert_called_with",
    "assert_called_once_with", "return_value", "side_effect",
    "patch", "mock", "MagicMock", "Mock",
    "setUp", "tearDown", "setup", "teardown",
    "describe", "it", "expect", "toBe", "toEqual", "toHaveBeenCalled",
    "fn", "spyOn", "mock", "beforeEach", "afterEach",
})

# Patrones para extraer firmas de métodos de documentos
_SIGNATURE_PATTERNS = [
    re.compile(r"def\s+(\w+)\s*\((.*?)\)(?:\s*->\s*(\S+))?", re.DOTALL),
    re.compile(r"(?:public|private|protected|static|\s)+\s+(\w+)\s+(\w+)\s*\((.*?)\)", re.DOTALL),
    re.compile(r"(?:async\s+)?function\s+(\w+)\s*\((.*?)\)"),
    re.compile(r"(\w+)\s*\((.*?)\)\s*:\s*(\w+)"),  # TS: method(params): ReturnType
]


@dataclass
class FilterResult:
    """Resultado de filtrar métodos alucinados."""
    original_response: str
    filtered_response: str
    hallucinated_methods: list[str]
    real_methods_used: list[str]
    has_hallucinations: bool = False


class MethodRegistry:
    """Registro de métodos reales extraídos de los documentos indexados."""

    def __init__(self):
        self._registry: dict[str, dict] = {}

    def build_registry(
        self,
        vector_store: VectorStore | None = None,
        collection_name: str = CollectionName.PROJECT_DOCS.value,
    ) -> dict:
        """
        Construye el registro consultando project_docs con doc_type=method_doc.
        Indexa por componente.
        """
        if vector_store is None:
            return self._registry

        try:
            # Obtener todos los chunks de tipo method_doc
            col = vector_store.get_or_create_collection(collection_name)
            if col.count() == 0:
                return self._registry

            results = col.get(
                where={"doc_type": "method_doc"},
                include=["documents", "metadatas"],
            )

            if not results or not results.get("documents"):
                return self._registry

            for doc, meta in zip(results["documents"], results["metadatas"]):
                component = meta.get("component", "")
                if not component:
                    continue

                if component not in self._registry:
                    self._registry[component] = {
                        "methods": [],
                        "signatures": {},
                    }

                # Extraer firmas del contenido
                for pattern in _SIGNATURE_PATTERNS:
                    for match in pattern.finditer(doc):
                        method_name = match.group(1)
                        if method_name not in _BUILTIN_METHODS:
                            full_sig = match.group(0).strip()
                            if method_name not in self._registry[component]["methods"]:
                                self._registry[component]["methods"].append(method_name)
                            self._registry[component]["signatures"][method_name] = full_sig

        except Exception as e:
            logger.warning(f"Failed to build method registry: {e}")

        logger.info(
            f"Method registry built: {len(self._registry)} component(s), "
            f"{sum(len(v['methods']) for v in self._registry.values())} method(s)"
        )
        return self._registry

    def add_component(self, component: str, methods: list[str], signatures: dict[str, str] | None = None):
        """Agregar un componente manualmente al registro."""
        self._registry[component] = {
            "methods": list(methods),
            "signatures": signatures or {},
        }

    def get_real_methods(self, component: str) -> list[str]:
        """Retorna métodos reales del componente. Lista vacía si no existe."""
        entry = self._registry.get(component)
        if not entry:
            logger.warning(f"Component '{component}' not found in method registry")
            return []
        return entry["methods"]

    def get_signature(self, component: str, method: str) -> str:
        """Retorna la firma de un método o string vacío si no existe."""
        entry = self._registry.get(component, {})
        return entry.get("signatures", {}).get(method, "")

    @property
    def components(self) -> list[str]:
        return list(self._registry.keys())


class MethodGroundingFilter:
    """Filtra métodos alucinados en respuestas del LLM."""

    def filter_hallucinated_methods(
        self,
        llm_response: str,
        component: str,
        registry: MethodRegistry,
    ) -> FilterResult:
        """
        Detecta métodos mencionados en la respuesta que no existen
        en el registro del componente.
        """
        real_methods = set(registry.get_real_methods(component))
        if not real_methods:
            return FilterResult(
                original_response=llm_response,
                filtered_response=llm_response,
                hallucinated_methods=[],
                real_methods_used=[],
                has_hallucinations=False,
            )

        # Extraer métodos mencionados
        mentioned = self._extract_mentioned_methods(llm_response)

        hallucinated = [m for m in mentioned if m not in real_methods and m not in _BUILTIN_METHODS]
        real_used = [m for m in mentioned if m in real_methods]

        filtered = llm_response
        if hallucinated:
            warning = (
                f"\n\n⚠️ ADVERTENCIA: Los siguientes métodos no existen en "
                f"{component} según la documentación indexada: {hallucinated}.\n"
                f"Métodos reales disponibles: {sorted(real_methods)}"
            )
            filtered = llm_response + warning

        return FilterResult(
            original_response=llm_response,
            filtered_response=filtered,
            hallucinated_methods=hallucinated,
            real_methods_used=real_used,
            has_hallucinations=bool(hallucinated),
        )

    @staticmethod
    def _extract_mentioned_methods(text: str) -> list[str]:
        """Extrae nombres de métodos mencionados en el texto."""
        methods: set[str] = set()

        # .method() pattern — word boundary ensures full name
        for match in re.finditer(r"\.(\w+)\s*\(", text):
            name = match.group(1)
            if name not in _BUILTIN_METHODS and not name.startswith("test_"):
                methods.add(name)

        # Direct function calls with word boundary: save_user(...)
        # Uses \b to avoid partial matches like 'ave_user' from 'save_user'
        for match in re.finditer(r"\b(\w+)\s*\(", text):
            name = match.group(1)
            if (name not in _BUILTIN_METHODS
                    and not name.startswith("test_")
                    and not name.startswith("def ")
                    and not name[0].isupper()  # Skip class names
                    and name != "def"
                    and len(name) > 3):
                methods.add(name)

        return list(methods)


def build_system_prompt(component: str, registry: MethodRegistry) -> str:
    """Genera el system prompt con la lista de métodos reales."""
    methods = registry.get_real_methods(component)
    signatures = []
    for m in methods:
        sig = registry.get_signature(component, m)
        signatures.append(sig if sig else m)

    methods_list = "\n".join(f"  - {s}" for s in signatures) if signatures else "  (ninguno documentado)"

    return (
        "Eres un asistente especializado en generar tests.\n"
        "REGLA CRÍTICA: Solo puedes usar métodos que existan en la documentación "
        "proporcionada. Los métodos reales disponibles en "
        f"{component} son:\n{methods_list}\n\n"
        "Si necesitas un método que no está en esta lista, menciona explícitamente "
        "que ese método no está documentado en lugar de inventarlo."
    )
