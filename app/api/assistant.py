import logging

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, Field
from sqlalchemy.orm import Session

from app.assistant.llm import LLMError
from app.assistant.service import handle_message, initialize_session
from app.chat.session import session_store
from app.database import get_db
from app.schemas.envelope import success_response
from app.utils.trace import trace, trace_async

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/api/v1", tags=["Assistant API"])


class ShopperSessionRequest(BaseModel):
    sessionId: str | None = None
    channel: str = "WEB"
    locale: str = "en-US"
    source: str = "QCOM_SHOPPER"
    profile: str = "general"
    language: str = "en"


class AssistantChatRequest(BaseModel):
    sessionId: str = Field(..., min_length=1)
    message: str = Field(..., min_length=0, max_length=1000)
    language: str = "en"
    structuredFields: dict | None = None


@router.post("/shopper/sessions")
@trace
def create_shopper_session(request: ShopperSessionRequest):
    return success_response(
        initialize_session(
            request.sessionId,
            channel=request.channel,
            locale=request.locale,
            source=request.source,
            profile=request.profile,
            language=request.language,
        ),
        "Shopper session initialized",
    )


@router.post("/assistant/welcome")
@trace
def assistant_welcome(request: ShopperSessionRequest):
    return success_response(
        initialize_session(
            request.sessionId,
            channel=request.channel,
            locale=request.locale,
            source=request.source,
            profile=request.profile,
            language=request.language,
        ),
        "Assistant welcome generated",
    )


@router.post("/assistant/chat")
@trace
def assistant_chat(request: AssistantChatRequest, db: Session = Depends(get_db)):
    if not session_store.exists(request.sessionId):
        raise HTTPException(status_code=404, detail="Unknown session. Initialize a shopper session first.")
    if not request.message.strip() and not request.structuredFields:
        raise HTTPException(status_code=422, detail="Message or structuredFields is required.")
    try:
        return success_response(
            handle_message(
                request.sessionId,
                request.message,
                db,
                language=request.language,
                structured_fields=request.structuredFields,
            ),
            "Assistant response generated",
        )
    except LLMError as exc:
        logger.exception("assistant_llm_error session=%s status=%s", request.sessionId, exc.status_code)
        status = 503 if exc.status_code in {402, 429, 500, 502, 503} else 502
        raise HTTPException(status_code=status, detail=exc.user_message()) from exc
    except Exception as exc:
        logger.exception("assistant_chat_failed session=%s error=%s", request.sessionId, exc)
        raise HTTPException(status_code=500, detail="Assistant could not process this message") from exc
