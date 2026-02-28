from app.models.report_model import DailyInput, StyleContext
from app.rag.retriever import StyleRetriever


class RetrieveStyleTool:
    def execute(self, daily_input: DailyInput) -> StyleContext:
        return StyleRetriever().retrieve_style_context(daily_input)
