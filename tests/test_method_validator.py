"""
Tests unitarios para method_validator.py
"""

import pytest

from app.rag.method_validator import (
    MethodRegistry,
    MethodGroundingFilter,
    build_system_prompt,
    FilterResult,
)


@pytest.fixture
def registry() -> MethodRegistry:
    reg = MethodRegistry()
    reg.add_component("UserService", [
        "save_user", "find_by_id", "delete_user", "authenticate",
    ], {
        "save_user": "def save_user(self, user: UserDTO) -> User",
        "find_by_id": "def find_by_id(self, user_id: int) -> Optional[User]",
        "delete_user": "def delete_user(self, user_id: int) -> bool",
        "authenticate": "def authenticate(self, email: str, password: str) -> Token",
    })
    return reg


@pytest.fixture
def grounding_filter() -> MethodGroundingFilter:
    return MethodGroundingFilter()


# ─────────────────────────────────────────────────
# MethodRegistry
# ─────────────────────────────────────────────────

class TestMethodRegistry:

    def test_get_real_methods(self, registry):
        methods = registry.get_real_methods("UserService")
        assert "save_user" in methods
        assert "find_by_id" in methods
        assert len(methods) == 4

    def test_unknown_component_returns_empty(self, registry):
        methods = registry.get_real_methods("NonExistentService")
        assert methods == []

    def test_get_signature(self, registry):
        sig = registry.get_signature("UserService", "save_user")
        assert "UserDTO" in sig
        assert "-> User" in sig

    def test_components_list(self, registry):
        assert "UserService" in registry.components


# ─────────────────────────────────────────────────
# MethodGroundingFilter
# ─────────────────────────────────────────────────

class TestMethodGroundingFilter:

    def test_detects_hallucinated_methods(self, grounding_filter, registry):
        response = """
Aquí tienes el test:

```python
def test_save_user():
    service = UserService()
    service.save_user(user)
    service.update_profile(user)  # este no existe
    service.send_notification()   # este tampoco
```
"""
        result = grounding_filter.filter_hallucinated_methods(
            response, "UserService", registry
        )
        assert result.has_hallucinations is True
        assert "update_profile" in result.hallucinated_methods
        assert "send_notification" in result.hallucinated_methods

    def test_no_hallucinations_with_real_methods(self, grounding_filter, registry):
        response = """
```python
def test_save():
    service.save_user(user)
    service.find_by_id(1)
```
"""
        result = grounding_filter.filter_hallucinated_methods(
            response, "UserService", registry
        )
        assert result.has_hallucinations is False
        assert result.hallucinated_methods == []

    def test_warning_appended_on_hallucination(self, grounding_filter, registry):
        response = "service.fake_method()"
        result = grounding_filter.filter_hallucinated_methods(
            response, "UserService", registry
        )
        assert "⚠️ ADVERTENCIA" in result.filtered_response
        assert "fake_method" in result.filtered_response

    def test_real_methods_tracked(self, grounding_filter, registry):
        response = "service.save_user(dto)\nservice.delete_user(1)"
        result = grounding_filter.filter_hallucinated_methods(
            response, "UserService", registry
        )
        assert "save_user" in result.real_methods_used
        assert "delete_user" in result.real_methods_used

    def test_unknown_component_no_filtering(self, grounding_filter, registry):
        response = "service.any_method()"
        result = grounding_filter.filter_hallucinated_methods(
            response, "UnknownService", registry
        )
        assert result.has_hallucinations is False
        assert result.filtered_response == response


# ─────────────────────────────────────────────────
# build_system_prompt
# ─────────────────────────────────────────────────

class TestBuildSystemPrompt:

    def test_contains_component_name(self, registry):
        prompt = build_system_prompt("UserService", registry)
        assert "UserService" in prompt

    def test_contains_real_methods(self, registry):
        prompt = build_system_prompt("UserService", registry)
        assert "save_user" in prompt
        assert "find_by_id" in prompt

    def test_contains_signatures(self, registry):
        prompt = build_system_prompt("UserService", registry)
        assert "UserDTO" in prompt
        assert "-> User" in prompt

    def test_critical_rule_present(self, registry):
        prompt = build_system_prompt("UserService", registry)
        assert "REGLA CRÍTICA" in prompt
