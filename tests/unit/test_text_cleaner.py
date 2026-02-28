from app.utils.text_cleaner import TextCleaner

class TestTextCleaner:
    def setup_method(self):
        self.cleaner = TextCleaner()

    def test_removes_page_number_dashes(self):
        result = self.cleaner.clean("Contenido. - 12 - Más contenido.")
        assert "- 12 -" not in result

    def test_collapses_whitespace(self):
        result = self.cleaner.clean("Texto   con    espacios")
        assert "  " not in result

    def test_removes_pagina_reference(self):
        result = self.cleaner.clean("Texto. Página 3 de 20. Más.")
        assert "Página 3 de 20" not in result

    def test_preserves_percentages(self):
        result = self.cleaner.clean("Cobertura del 90% completada.")
        assert "90%" in result
