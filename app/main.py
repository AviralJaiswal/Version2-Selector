import logging
import sys
from pathlib import Path

# Ensure root directory is in sys.path
ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from fastapi import FastAPI, HTTPException, Request
from fastapi.exceptions import RequestValidationError
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse

from app.config import get_settings
from app.api import (
    session,
    qualification,
    recommendation,
    customer,
    appointment,
    payment,
    order,
    rag,
    assistant,
    voice
)

from contextlib import asynccontextmanager


logging.getLogger("uvicorn.access").disabled = False
logging.getLogger("uvicorn.access").propagate = True
logging.getLogger("uvicorn.access").setLevel(logging.INFO)
logging.getLogger("uvicorn").setLevel(logging.INFO)

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s | %(levelname)s | %(name)s | %(message)s",
    datefmt="%H:%M:%S",
    force=True,
)


@asynccontextmanager
async def lifespan(app_instance: FastAPI):
    """Auto-create tables and initialize ChromaDB RAG on server startup."""
    try:
        from app.database import Base, engine
        Base.metadata.create_all(bind=engine)
        from app.rag.chroma_rag import init_faq_chroma
        init_faq_chroma()
    except BaseException as exc:
        print("Startup initialization note:", exc)
    yield


settings = get_settings()

app = FastAPI(
    title=settings.app_name,
    version="1.0.0",
    description="Signal Selector Modular FastAPI Backend - Step-by-Step Execution Flow & RAG AI Assistant",
    lifespan=lifespan
)

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# Standardized Error Envelope Exception Handlers
@app.exception_handler(HTTPException)
async def http_exception_handler(request: Request, exc: HTTPException):
    return JSONResponse(
        status_code=exc.status_code,
        content={
            "success": False,
            "code": exc.status_code,
            "message": exc.detail if isinstance(exc.detail, str) else "HTTP Exception",
            "data": None,
            "error": str(exc.detail)
        }
    )

@app.exception_handler(RequestValidationError)
async def validation_exception_handler(request: Request, exc: RequestValidationError):
    return JSONResponse(
        status_code=422,
        content={
            "success": False,
            "code": 422,
            "message": "Validation Error",
            "data": None,
            "error": str(exc.errors())
        }
    )

# Register 8 Modular APIRouters in Strict Sequential Execution Flow
# 1. Welcome / Session (Signal Selector Session API) -> POST /api/v1/session
app.include_router(session.router)
app.include_router(session.legacy_router)

# 2. Address Qualification (Address Qualification API) -> POST /api/v1/qualification/address
app.include_router(qualification.router)
app.include_router(qualification.legacy_router)

# 3. Plan Recommendation (Recommendation API) -> GET /api/v1/plans/recommendations
app.include_router(recommendation.router)
app.include_router(recommendation.legacy_router)

# 4. Customer Details (Customer API) -> POST /api/v1/customers
app.include_router(customer.router)
app.include_router(customer.legacy_router)

# 5. Service Appointment (Appointment API) -> POST /api/v1/appointments
app.include_router(appointment.router)
app.include_router(appointment.legacy_router)

# 6. Payment (Payment API) -> POST /api/v1/payments
app.include_router(payment.router)
app.include_router(payment.legacy_router)

# 7. Order Creation (Order API) -> POST /api/v1/orders
app.include_router(order.router)
app.include_router(order.legacy_router)

# 8. RAG Assistance & Assistant Chat (API 01 & API 08) -> POST /api/v1/shopper/sessions & POST /api/v1/assistant/chat
app.include_router(assistant.router)
app.include_router(rag.router)
app.include_router(rag.legacy_router)
app.include_router(voice.router)


@app.get("/")
def root_status() -> dict:
    """Root GET endpoint indicating backend service status and available endpoints."""
    return {
        "status": "online",
        "message": "Signal Selector API is running"
    }


@app.get("/health")
def health() -> dict[str, str]:
    return {"status": "ok", "app": settings.app_name}
