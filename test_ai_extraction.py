import asyncio
import sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).parent))

from app.services.ai_service import AIService
from app.config import get_settings

def test_ai():
    ai = AIService()
    narratives = [
        ("mi_imagen1.png", "Verifiqué que el usuario Decano de Salud pueda ingresar con sus credenciales."),
        ("mi_imagen2.png", "Verifiqué que el usuario Decano de Salud pueda crear un PDAa seleccionando dependencias.")
    ]
    metadata = {
        "report_date": "2026-02-26",
        "report_type": "functional_tests",
        "project_name": "Test",
        "environment": "QA",
        "prepared_by": "QA Engineer Sebax"
    }

    print("Requesting AI extraction...")
    daily_input = ai.extract_daily_input_from_images(narratives, metadata)
    print("----- RESULT -----")
    import json
    print(daily_input.model_dump_json(indent=2))

if __name__ == "__main__":
    test_ai()
