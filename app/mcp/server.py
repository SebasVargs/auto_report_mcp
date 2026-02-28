from __future__ import annotations

from datetime import date

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel

from app.mcp.tools.generate_report_tool import GenerateReportTool
from app.mcp.tools.fetch_daily_data_tool import FetchDailyDataTool
from app.mcp.tools.retrieve_style_tool import RetrieveStyleTool
from app.mcp.tools.save_report_tool import SaveReportTool
from app.models.report_model import (
    GenerateReportRequest,
    GenerateReportResponse,
    ReportType,
    DailyInput,
)
from app.utils.logger import get_logger

logger = get_logger(__name__)
mcp_router = APIRouter(tags=["MCP Tools"])


# ── Tool Discovery ──────────────────────────────────────────────

class ToolManifest(BaseModel):
    """MCP tool discovery — lista todas las herramientas disponibles."""
    tools: list[dict]


@mcp_router.get("/tools", summary="List all available MCP tools")
async def list_tools() -> ToolManifest:
    return ToolManifest(
        tools=[
            {
                "name": "generate_report",
                "description": "Orchestrates full report generation: fetch_data → RAG → AI → Word",
                "endpoint": "/mcp/tools/generate_report",
                "method": "POST",
                "input_schema": GenerateReportRequest.model_json_schema(),
            },
            {
                "name": "fetch_daily_data",
                "description": "Loads structured daily input JSON for a given date and report type",
                "endpoint": "/mcp/tools/fetch_daily_data",
                "method": "POST",
            },
            {
                "name": "retrieve_style",
                "description": "Queries ChromaDB for style context chunks via RAG",
                "endpoint": "/mcp/tools/retrieve_style",
                "method": "POST",
            },
            {
                "name": "trigger_daily",
                "description": "Manual trigger for today's scheduled generation",
                "endpoint": "/mcp/tools/trigger_daily",
                "method": "POST",
            },
            {
                "name": "list_reports",
                "description": "List all previously generated report manifests",
                "endpoint": "/mcp/tools/list_reports",
                "method": "GET",
            },
        ]
    )


# ── Core Tool Endpoints ─────────────────────────────────────────

@mcp_router.post(
    "/tools/generate_report",
    response_model=GenerateReportResponse,
    summary="Generate a full Word report (main pipeline)",
)
async def generate_report(request: GenerateReportRequest) -> GenerateReportResponse:
    """
    Orchestration endpoint.
    Pipeline: structured_input → RAG context → AI narrative → Word document → saved file.
    """
    try:
        tool = GenerateReportTool()
        return await tool.execute(request)
    except FileNotFoundError as e:
        logger.warning(f"Daily input not found: {e}")
        raise HTTPException(status_code=404, detail=str(e))
    except Exception as e:
        logger.error(f"generate_report failed: {e}", exc_info=True)
        raise HTTPException(status_code=500, detail=f"Report generation failed: {str(e)}")


@mcp_router.post(
    "/tools/trigger_daily",
    response_model=GenerateReportResponse,
    summary="Manual trigger for today's report (same as scheduler job)",
)
async def trigger_daily_generation():
    """Manual trigger — same logic as the daily cron job."""
    request = GenerateReportRequest(
        report_date=date.today(),
        report_type=ReportType.FUNCTIONAL_TESTS,
    )
    return await generate_report(request)


class FetchDailyDataRequest(BaseModel):
    report_date: date
    report_type: ReportType


@mcp_router.post(
    "/tools/fetch_daily_data",
    summary="Load daily structured input for a given date",
)
async def fetch_daily_data(request: FetchDailyDataRequest) -> DailyInput:
    try:
        tool = FetchDailyDataTool()
        return tool.execute(request.report_date, request.report_type)
    except FileNotFoundError as e:
        raise HTTPException(status_code=404, detail=str(e))


class RetrieveStyleRequest(BaseModel):
    query: str
    top_k: int = 8


@mcp_router.post(
    "/tools/retrieve_style",
    summary="Query RAG for style context from historical reports",
)
async def retrieve_style(request: RetrieveStyleRequest):
    """Debug/inspection endpoint — returns raw style chunks."""
    from app.rag.embedding_service import EmbeddingService
    from app.rag.vector_store import VectorStore
    from app.config import get_settings

    settings = get_settings()
    embedding = EmbeddingService().embed(request.query)
    results = VectorStore().query(
        collection_name=settings.chroma_collection_style,
        query_embedding=embedding,
        top_k=request.top_k,
    )
    return {"chunks": results, "total": len(results)}


@mcp_router.get(
    "/tools/list_reports",
    summary="List all previously generated report manifests",
)
async def list_reports():
    tool = SaveReportTool()
    return {"reports": tool.list_manifests()}
