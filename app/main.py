import asyncio
from contextlib import asynccontextmanager
from pathlib import Path

import uvicorn
from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from app.mcp.server import mcp_router
from app.services.scheduler_service import SchedulerService
from app.utils.logger import get_logger
from app.config import get_settings

logger = get_logger(__name__)
settings = get_settings()


def ensure_directories() -> None:
    """Crea directorios necesarios si no existen."""
    dirs = [
        settings.raw_reports_dir,
        settings.processed_chunks_dir,
        settings.output_reports_dir,
        settings.daily_inputs_dir,
        settings.chroma_persist_dir,
    ]
    for d in dirs:
        Path(d).mkdir(parents=True, exist_ok=True)


@asynccontextmanager
async def lifespan(app: FastAPI):
    """Startup / shutdown lifecycle hook."""
    logger.info("🚀 Starting auto-report-mcp")
    ensure_directories()

    scheduler = SchedulerService()
    scheduler.start()

    yield  # ← aplicación corre aquí

    scheduler.shutdown()
    logger.info("🛑 auto-report-mcp stopped")


app = FastAPI(
    title="auto-report-mcp",
    description=(
        "Generación automática de informes profesionales Word "
        "via arquitectura MCP + RAG + OpenAI."
    ),
    version="1.0.0",
    lifespan=lifespan,
    docs_url="/docs",
    redoc_url="/redoc",
)

# CORS — ajustar origins en producción
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# Montar MCP router
app.include_router(mcp_router, prefix="/mcp")


@app.get("/health", tags=["Monitoring"])
async def health():
    """Liveness probe — usado por Docker/k8s."""
    from app.rag.vector_store import VectorStore
    try:
        vs = VectorStore()
        chunk_count = vs.collection_count(settings.chroma_collection_style)
        return {
            "status": "ok",
            "service": "auto-report-mcp",
            "vector_store": {"chunks": chunk_count},
        }
    except Exception as e:
        return {"status": "degraded", "error": str(e)}


@app.get("/", tags=["Info"])
async def root():
    return {
        "service": "auto-report-mcp",
        "version": "1.0.0",
        "docs": "/docs",
        "tools": "/mcp/tools",
    }


if __name__ == "__main__":
    uvicorn.run(
        "app.main:app",
        host=settings.api_host,
        port=settings.api_port,
        reload=settings.api_debug,
        log_level=settings.api_log_level.lower(),
    )
