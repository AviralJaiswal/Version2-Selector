from uuid import uuid4
from fastapi import APIRouter
from app.chat.session import session_store
from app.schemas.api import SessionRequest, SessionData
from app.schemas.envelope import ResponseEnvelope, success_response
from app.utils.trace import trace, trace_async

router = APIRouter(prefix="/api/v1", tags=["Signal Selector Session API"])
legacy_router = APIRouter(tags=["Legacy Session API"])


from app.services.welcome_service import generate_dynamic_greeting

@router.post("/chat/welcome")
@router.get("/chat/welcome")
@trace
def welcome_chat(request: SessionRequest = None):
    """Dynamic LLM Greeting Endpoint - Generates fresh Gemini greeting at temp 0.85."""
    session_id = (request.session_id if request else None) or uuid4().hex
    session_store.create(session_id)
    from app.services.activity_logger import log_activity
    log_activity("session_welcome", session_id, {"channel": "api"})
    greeting = generate_dynamic_greeting()
    return success_response({
        "session_id": session_id,
        "message": greeting,
        "welcome_message": greeting
    }, message="Dynamic LLM welcome greeting generated successfully")


@router.post("/session", response_model=ResponseEnvelope[SessionData])
@trace
def create_session(request: SessionRequest):
    """Step 1: Signal Selector Session API - Create or initialize a session."""
    session_id = request.session_id or uuid4().hex
    session_store.create(session_id)
    from app.services.activity_logger import log_activity
    log_activity("session_start", session_id, {"channel": "api"})
    greeting = generate_dynamic_greeting()
    data = SessionData(
        session_id=session_id,
        message=greeting,
        status="active"
    )
    return success_response(data.model_dump(), message="Session initialized successfully")


@legacy_router.post("/welcome")
@trace
def welcome_legacy(request: SessionRequest):
    session_id = request.session_id or uuid4().hex
    session_store.create(session_id)
    greeting = generate_dynamic_greeting()
    return success_response({
        "session_id": session_id,
        "message": greeting,
        "welcome_message": greeting
    })

