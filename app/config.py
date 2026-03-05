from functools import lru_cache
from pathlib import Path
from pydantic_settings import BaseSettings, SettingsConfigDict
from pydantic import Field


class Settings(BaseSettings):
    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        case_sensitive=False,
    )
    
    # Google Drive — context reports folder
    drive_context_reports_folder_id: str = Field(
        default="1W1H0C4mfrCJqmrBuhnHK2e-OhjT8cMc0",
        env="DRIVE_CONTEXT_REPORTS_FOLDER_ID",
    )

    # Local directory for context reports (.docx)
    context_reports_dir: str = Field(
        default="./context_reports",
        env="CONTEXT_REPORTS_DIR",
    )

    # ChromaDB collection name for project knowledge
    chroma_collection_knowledge: str = Field(
        default="project_knowledge",
        env="CHROMA_COLLECTION_KNOWLEDGE",
    )

    # ── LLM Provider ─────────────────────────────────────────────
    llm_provider: str = "openai"          # openai | ollama
    llm_base_url: str = ""                # override base URL (empty = provider default)
    embedding_provider: str = "openai"    # openai | ollama
    embedding_base_url: str = ""

    # ── OpenAI ───────────────────────────────────────────────────
    openai_api_key: str = "sk-placeholder"
    openai_embedding_model: str = "text-embedding-3-small"
    openai_model: str = "gpt-4o"
    openai_max_tokens: int = 4096

    # ── Ollama ───────────────────────────────────────────────────
    ollama_base_url: str = "http://localhost:11434"
    ollama_model: str = "llama3.2"
    ollama_embedding_model: str = "nomic-embed-text"

    # ── Google Drive ─────────────────────────────────────────────
    google_credentials_json: str = "./credentials.json"
    drive_raw_reports_folder_id: str = ""
    drive_daily_inputs_folder_id: str = ""
    drive_output_folder_id: str = ""
    drive_input_images_folder_id: str = ""
    drive_repository_images_folder_id: str = ""
    drive_context_reports_folder_id: str = ""  # folder: context_reports
    drive_knowledge_backup_folder_id: str = ""  # folder: vector_db backups
    drive_enabled: bool = False

    # ── ChromaDB ─────────────────────────────────────────────────
    chroma_persist_dir: str = "./vector_db"
    chroma_collection_style: str = "report_style_chunks"
    chroma_collection_knowledge: str = "project_knowledge"  # project context & notes

    # ── Rutas ────────────────────────────────────────────────────
    raw_reports_dir: str = "./data/raw_reports"
    processed_chunks_dir: str = "./data/processed_chunks"
    output_reports_dir: str = "./output_reports"
    context_reports_dir: str = "./context_reports"          # project knowledge docs
    daily_inputs_dir: str = "./data/daily_inputs"
    templates_dir: str = "./templates"
    input_images_dir: str = "./input_images"
    repository_images_dir: str = "./repository_images"

    # ── Scheduler ────────────────────────────────────────────────
    scheduler_hour: int = 7
    scheduler_minute: int = 0
    scheduler_days: str = "mon-fri"
    scheduler_timezone: str = "America/Bogota"

    # ── MCP / API ────────────────────────────────────────────────
    mcp_server_host: str = "0.0.0.0"
    mcp_server_port: int = 8080
    mcp_server_name: str = "auto-report-mcp"
    api_host: str = "0.0.0.0"
    api_port: int = 8000
    api_debug: bool = False
    api_log_level: str = "INFO"

    # ── RAG ──────────────────────────────────────────────────────
    rag_chunk_size: int = 800
    rag_chunk_overlap: int = 150
    rag_top_k: int = 8
    rag_n_results: int = 8   # alias kept for .env backwards-compat

    @property
    def raw_reports_path(self) -> Path:
        return Path(self.raw_reports_dir)

    @property
    def output_reports_path(self) -> Path:
        return Path(self.output_reports_dir)

    @property
    def context_reports_path(self) -> Path:
        return Path(self.context_reports_dir)

    @property
    def daily_inputs_path(self) -> Path:
        return Path(self.daily_inputs_dir)

    @property
    def templates_path(self) -> Path:
        return Path(self.templates_dir)

    @property
    def input_images_path(self) -> Path:
        return Path(self.input_images_dir)

    @property
    def repository_images_path(self) -> Path:
        return Path(self.repository_images_dir)


@lru_cache()
def get_settings() -> Settings:
    """Singleton de configuración — lru_cache garantiza una sola instancia."""
    return Settings()
