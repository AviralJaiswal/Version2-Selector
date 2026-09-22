import logging
from time import perf_counter
from fastapi import APIRouter, Depends
from sqlalchemy.orm import Session
from app.assistant.service import handle_message
from app.database import get_db
from app.schemas.api import RAGQueryRequest, RAGQueryData
from app.schemas.envelope import ResponseEnvelope, success_response
from app.utils.trace import trace, trace_async

logger = logging.getLogger(__name__)
router = APIRouter(prefix="/api/v1", tags=["AI Assistant API"])
legacy_router = APIRouter(tags=["Legacy AI Assistant API"])


@router.post("/ai/rag/query", response_model=ResponseEnvelope[RAGQueryData])
@trace
def query_rag_assistant(request: RAGQueryRequest, db: Session = Depends(get_db)):
    """AI Assistant API - Modular orchestration powered by Gemini & ChromaDB RAG."""
    started = perf_counter()
    structured = request.structured_fields.model_dump(exclude_none=True) if request.structured_fields else None

    result = handle_message(
        session_id=request.session_id,
        message=request.message,
        db=db,
        language=request.language or "en",
        structured_fields=structured,
    )

    response_data = {
        "answer": result.get("response", ""),
        "mode": result.get("mode", "RAG"),
        "evidence": result.get("sources", []),
        "sources": result.get("sources", []),
        "intent": result.get("intent", ""),
        "workflow_state": result.get("workflowState", ""),
        "recommended_plan": result.get("recommendedPlan") or result.get("recommended_plan"),
        "recommended_followups": result.get("recommended_followups") or result.get("recommendedFollowups") or [],
        "updated_state": {**result.get("updatedState", {}), "language": result.get("updatedState", {}).get("language") or (result.get("sessionId") and __import__('app.chat.session', fromlist=['session_store']).session_store.get(request.session_id).get("language")) or request.language or "en"},
        # Existing-customer flow passthrough
        "current_plan": result.get("current_plan"),
        "upgrade_options": result.get("upgrade_options"),
        "downgrade_options": result.get("downgrade_options"),
        "proposed_plan": result.get("proposed_plan"),
        "catalog_plans": result.get("catalog_plans"),
        "plan_change_mode": result.get("plan_change_mode"),
        "customer": result.get("customer"),
        "show_customer_editor": result.get("show_customer_editor", False),
    }

    duration_ms = round((perf_counter() - started) * 1000)
    logger.info("RAG query processed in %dms mode=%s", duration_ms, result.get("mode"))
    return success_response(response_data, message="Assistant response generated successfully")


@legacy_router.post("/chat")
def chat_legacy(request: RAGQueryRequest, db: Session = Depends(get_db)):
    return query_rag_assistant(request, db)

