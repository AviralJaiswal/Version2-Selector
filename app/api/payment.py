from fastapi import APIRouter, HTTPException
from app.schemas.api import PaymentConfirmRequest, PaymentRequest, PaymentData
from app.schemas.envelope import ResponseEnvelope, success_response
from app.services.payment_service import confirm_payment, create_purl
from app.chat.session import session_store
from app.utils.trace import trace, trace_async

router = APIRouter(prefix="/api/v1", tags=["Payment API"])
legacy_router = APIRouter(tags=["Legacy Payment API"])


@router.post("/payments", response_model=ResponseEnvelope[PaymentData])
@trace
def process_payment(request: PaymentRequest, confirmation_code: str | None = None):
    """Step 6: Payment API - Generate payment URL and confirm transaction."""
    context = session_store.get(request.session_id)
    plan = context.get("selected_plan") or next(
        (p for p in (context.get("recommended_plans") or context.get("catalog_plans") or []) if p["plan_id"] == request.plan_id), None
    )
    if not plan:
        raise HTTPException(status_code=404, detail="Plan not found in session recommendations")
    
    payment_obj = create_purl(request.session_id, plan["price_inr"])
    if confirmation_code:
        payment_obj = confirm_payment(payment_obj, confirmation_code)
    
    session_store.update(request.session_id, {"selected_plan": plan, "payment": payment_obj})
    return success_response(payment_obj, message=f"Payment status: {payment_obj['status']}")


@router.get("/payments/{payment_id}")
@trace
def get_payment_status(payment_id: str):
    """API 06: GET /api/v1/payments/{paymentId} - Query payment transaction status."""
    return success_response({
        "paymentId": payment_id,
        "status": "SUCCESS",
        "transactionId": f"TXN-{payment_id.replace('PAY-', '')}"
    }, message="Payment status retrieved")


@legacy_router.post("/payment")
@trace
def payment_legacy(request: PaymentRequest):
    context = session_store.get(request.session_id)
    plan = context.get("selected_plan") or next((p for p in (context.get("recommended_plans") or context.get("catalog_plans") or []) if p["plan_id"] == request.plan_id), None)
    if not plan:
        raise HTTPException(status_code=404, detail="Plan not found in session recommendations")
    payment_obj = create_purl(request.session_id, plan["price_inr"])
    session_store.update(request.session_id, {"selected_plan": plan, "payment": payment_obj})
    return success_response(payment_obj)


@legacy_router.post("/payment/confirm")
@trace
def payment_confirm_legacy(request: PaymentConfirmRequest):
    context = session_store.get(request.session_id)
    if not context.get("payment"):
        raise HTTPException(status_code=400, detail="Generate a payment URL first")
    payment_obj = confirm_payment(context["payment"], request.confirmation_code)
    session_store.update(request.session_id, {"payment": payment_obj})
    return success_response(payment_obj)
