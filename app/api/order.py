from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.orm import Session
from app.database import get_db
from app.schemas.api import OrderRequest, OrderData
from app.schemas.envelope import ResponseEnvelope, success_response
from app.services.order_service import create_order
from app.chat.session import session_store
from app.utils.trace import trace, trace_async

router = APIRouter(prefix="/api/v1", tags=["Order API"])
legacy_router = APIRouter(tags=["Legacy Order API"])


@router.post("/orders", response_model=ResponseEnvelope[OrderData])
@trace
def place_order(request: OrderRequest, db: Session = Depends(get_db)):
    """Step 7: Order API - Finalize customer broadband order."""
    try:
        data = create_order(db, request.session_id, session_store.get(request.session_id))
        from app.services.activity_logger import log_activity
        log_activity("order_confirmed", request.session_id, {
            "order_id": data.get("order_id"),
            "customer_id": data.get("customer_id")
        })
        return success_response(data, message="Order created and confirmed successfully")
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc


@legacy_router.post("/create-order")
@trace
def create_order_legacy(request: OrderRequest, db: Session = Depends(get_db)):
    try:
        data = create_order(db, request.session_id, session_store.get(request.session_id))
        return success_response(data)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
