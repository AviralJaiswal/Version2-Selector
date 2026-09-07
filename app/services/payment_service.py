import secrets
import razorpay
from app.config import get_settings
from app.utils.trace import trace, trace_async

settings = get_settings()

@trace
def get_razorpay_client():
    if not settings.razorpay_key_id or not settings.razorpay_key_secret:
        return None
    return razorpay.Client(auth=(settings.razorpay_key_id, settings.razorpay_key_secret))

@trace
def create_purl(session_id: str, amount_inr: int) -> dict:
    client = get_razorpay_client()
    if client:
        order_amount = int(amount_inr * 100)  # amount in paise
        razorpay_order = client.order.create({
            'amount': order_amount,
            'currency': 'INR',
            'receipt': session_id[:40]
        })
        return {
            "razorpay_order_id": razorpay_order['id'],
            "razorpay_key_id": settings.razorpay_key_id,
            "session_id": session_id,
            "amount_inr": amount_inr,
            "status": "pending"
        }
    else:
        return {
            "purl": f"https://mock-pay.qcom.local/pay/{secrets.token_urlsafe(12)}",
            "session_id": session_id,
            "amount_inr": amount_inr,
            "status": "pending"
        }

@trace
def confirm_payment(payment: dict, confirmation_code: str | None = None) -> dict:
    payment = {**payment, "status": "completed", "confirmation_code": confirmation_code or "MOCK-PAID"}
    return payment

