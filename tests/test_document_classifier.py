"""
Tests unitarios para document_classifier.py

3 casos positivos + 2 negativos por cada tipo, más tests de is_daily_note
y classify_document con contenido de ejemplo real.
"""

import pytest

from app.rag.rag_schema import DocType
from app.rag.docx_reader import DocxContent
from app.rag.document_classifier import DocumentClassifier


@pytest.fixture
def classifier() -> DocumentClassifier:
    return DocumentClassifier()


# ─────────────────────────────────────────────────
# classify_test_type — UNIT_TEST
# ─────────────────────────────────────────────────

class TestClassifyUnitTest:

    def test_unit_by_filename(self, classifier):
        result = classifier.classify_test_type("def test_foo(): pass", "test_unit_user.py")
        assert result == DocType.UNIT_TEST

    def test_unit_by_mock_content(self, classifier):
        code = """
from unittest.mock import MagicMock, patch

@patch('app.services.user_service.UserRepository')
def test_save_user(mock_repo):
    mock_repo.save.return_value = User(id=1)
    service = UserService(mock_repo)
    result = service.save_user(UserDTO(name="test"))
    assert result.id == 1
"""
        result = classifier.classify_test_type(code, "test_user_service.py")
        assert result == DocType.UNIT_TEST

    def test_unit_by_jest_mock(self, classifier):
        code = """
describe('UserService', () => {
  it('should save user', () => {
    const mockRepo = jest.fn();
    const spy = jest.spyOn(repo, 'save');
    expect(result).toBe(true);
  });
});
"""
        result = classifier.classify_test_type(code, "user.spec.ts")
        assert result == DocType.UNIT_TEST

    def test_not_unit_when_database(self, classifier):
        code = """
from unittest.mock import MagicMock
def test_integration():
    database.connect()
    http.get('/api/users')
"""
        result = classifier.classify_test_type(code, "test_integration_db.py")
        assert result != DocType.UNIT_TEST

    def test_not_unit_when_selenium(self, classifier):
        code = """
def test_login_flow():
    browser.get('http://localhost')
    selenium.find_element('button').click()
"""
        result = classifier.classify_test_type(code, "test_e2e_login.py")
        assert result != DocType.UNIT_TEST


# ─────────────────────────────────────────────────
# classify_test_type — INTEGRATION_TEST
# ─────────────────────────────────────────────────

class TestClassifyIntegrationTest:

    def test_integration_by_filename(self, classifier):
        code = "def test_db(): db.query('SELECT 1')"
        result = classifier.classify_test_type(code, "test_integration_repo.py")
        assert result == DocType.INTEGRATION_TEST

    def test_integration_by_database_content(self, classifier):
        code = """
def test_user_repository():
    repo = UserRepository(database=test_db)
    repo.save(User(name="test"))
    result = db.query("SELECT * FROM users")
    assert len(result) == 1
"""
        result = classifier.classify_test_type(code, "test_repo.py")
        assert result == DocType.INTEGRATION_TEST

    def test_integration_by_http_client(self, classifier):
        code = """
def test_api_endpoint():
    client = TestClient(app)
    response = requests.get('/api/users')
    assert response.status_code == 200
"""
        result = classifier.classify_test_type(code, "test_api.py")
        assert result == DocType.INTEGRATION_TEST

    def test_not_integration_pure_mock(self, classifier):
        code = """
def test_pure_unit():
    mock = MagicMock()
    mock.return_value = 42
    assert mock() == 42
"""
        result = classifier.classify_test_type(code, "test_unit_calc.py")
        assert result != DocType.INTEGRATION_TEST

    def test_not_integration_e2e(self, classifier):
        code = """
Scenario: User login
  Given the user navigates to login page
  When the user enters credentials
  Then the user sees the dashboard
"""
        result = classifier.classify_test_type(code, "login.feature")
        assert result != DocType.INTEGRATION_TEST


# ─────────────────────────────────────────────────
# classify_test_type — FUNCTIONAL_TEST
# ─────────────────────────────────────────────────

class TestClassifyFunctionalTest:

    def test_functional_by_filename(self, classifier):
        code = "page.click('button')"
        result = classifier.classify_test_type(code, "test_e2e_checkout.py")
        assert result == DocType.FUNCTIONAL_TEST

    def test_functional_by_playwright(self, classifier):
        code = """
async def test_login():
    browser = await playwright.chromium.launch()
    page = await browser.new_page()
    await page.goto('http://localhost:3000')
"""
        result = classifier.classify_test_type(code, "test_login_flow.py")
        assert result == DocType.FUNCTIONAL_TEST

    def test_functional_by_gherkin(self, classifier):
        code = """
Scenario: Checkout flow
  Given the user has items in cart
  When the user clicks checkout
  Then the order is confirmed
"""
        result = classifier.classify_test_type(code, "checkout.feature")
        assert result == DocType.FUNCTIONAL_TEST

    def test_not_functional_pure_unit(self, classifier):
        code = """
def test_calculator():
    mock = MagicMock()
    assert 1 + 1 == 2
"""
        result = classifier.classify_test_type(code, "test_unit_calc.py")
        assert result != DocType.FUNCTIONAL_TEST

    def test_not_functional_db_test(self, classifier):
        code = """
def test_repo():
    database.connect()
    repository.save(item)
"""
        result = classifier.classify_test_type(code, "test_integration_repo.py")
        assert result != DocType.FUNCTIONAL_TEST


# ─────────────────────────────────────────────────
# is_daily_note
# ─────────────────────────────────────────────────

class TestIsDailyNote:

    def test_daily_note_by_filename_with_date(self, classifier):
        assert classifier.is_daily_note("hoy cambié el módulo X", "daily_2024-01-15.md")

    def test_daily_note_by_filename_keyword(self, classifier):
        assert classifier.is_daily_note("contenido", "nota_proyecto.md")

    def test_daily_note_by_header(self, classifier):
        assert classifier.is_daily_note("# 2024-03-10\nCambié el deployment", "update.md")

    def test_not_daily_note_regular_file(self, classifier):
        assert not classifier.is_daily_note("class UserService:", "user_service.py")

    def test_not_daily_note_test_file(self, classifier):
        assert not classifier.is_daily_note("def test_foo(): pass", "test_user.py")


# ─────────────────────────────────────────────────
# classify_document — full pipeline
# ─────────────────────────────────────────────────

class TestClassifyDocument:

    def test_classifies_unit_test(self, classifier):
        code = """
import pytest
from unittest.mock import MagicMock, patch

@patch('app.repo.UserRepo')
def test_create_user(mock_repo):
    mock_repo.save.return_value = User(id=1)
    service = UserService(mock_repo)
    result = service.create(UserDTO(name="test"))
    assert result.id == 1
"""
        meta = classifier.classify_document(code, "test_user_service.py")
        assert meta.doc_type == DocType.UNIT_TEST
        assert meta.test_type == "unit"
        assert meta.framework == "pytest"
        assert meta.language == "python"

    def test_classifies_daily_note(self, classifier):
        text = "# 2024-01-15\nHoy migré el módulo de pagos a la nueva API."
        meta = classifier.classify_document(text, "daily_2024-01-15.md")
        assert meta.doc_type == DocType.DAILY_NOTE
        assert meta.is_daily_note is True
        assert meta.priority_score == 2.0
        assert meta.note_date == "2024-01-15"

    def test_classifies_method_doc(self, classifier):
        code = '''
class UserService:
    def save_user(self, user: UserDTO) -> User:
        """Save a user to the database.

        :param user: The user data transfer object
        :returns: The saved User entity
        """
        return self.repo.save(user)

    def find_by_id(self, user_id: int) -> Optional[User]:
        """Find user by ID.

        :param user_id: The user ID to search
        :returns: User if found, None otherwise
        """
        return self.repo.find(user_id)

    def delete_user(self, user_id: int) -> bool:
        """Delete user.

        :param user_id: ID of the user to delete
        :returns: True if deleted
        """
        return self.repo.delete(user_id)
'''
        meta = classifier.classify_document(code, "user_service.py")
        assert meta.doc_type == DocType.METHOD_DOC
        assert meta.component == "UserService"

    def test_classifies_project_doc(self, classifier):
        text = """
# Arquitectura del Sistema

El sistema utiliza una arquitectura hexagonal con los siguientes módulos:
- Módulo de autenticación
- Módulo de reportes
- Módulo de notificaciones
"""
        meta = classifier.classify_document(text, "architecture.md")
        assert meta.doc_type == DocType.PROJECT_DOC

    def test_classifies_docx_content(self, classifier):
        docx = DocxContent(
            raw_text="class OrderService:\n@@CODE_START@@\ndef create_order(self, order):\n@@CODE_END@@",
            sections=["OrderService", "Métodos"],
            tables=[],
            metadata_hints={
                "possible_component": "OrderService",
                "possible_methods": ["create_order"],
                "has_code_blocks": True,
                "has_tables": False,
                "heading_count": 2,
                "first_heading": "OrderService",
                "word_count": 20,
                "detected_keywords": ["order", "service"],
            },
            filename="OrderService.docx",
            file_path="/docs/OrderService.docx",
        )
        meta = classifier.classify_document(docx, "OrderService.docx")
        assert meta.component == "OrderService"
        assert meta.source_file == "OrderService.docx"
