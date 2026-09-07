from uuid import uuid4
from sqlalchemy import select
from sqlalchemy.orm import Session
from app.models.order import Order
from app.models.customer import Customer
from app.utils.trace import trace, trace_async


@trace
def _has_complete_service_address(address: dict) -> bool:
    return bool(
        address
        and address.get("address_qualified")
        and address.get("pincode")
        and (address.get("street_address") or address.get("formatted_address"))
    )


@trace
def create_order(db: Session, session_id: str, context: dict) -> dict:
    customer = context.get("customer", {})
    plan = context.get("selected_plan")
    payment = context.get("payment", {})
    address = context.get("service_address") or context.get("qualified_address") or {}
    appointment = context.get("appointment")
    if not plan or not _has_complete_service_address(address) or not appointment or payment.get("status") != "completed":
        raise ValueError("A selected plan, complete qualified service address with PIN code, appointment, and completed payment are required")

    # Ensure Customer record exists in customers DB table for lookup
    cust_id = customer.get("customer_id") or f"CUST-{uuid4().hex[:6].upper()}"
    existing_c = None
    if customer.get("email") or customer.get("phone"):
        existing_c = db.scalar(
            select(Customer).where(
                (Customer.email == customer.get("email")) | (Customer.phone == customer.get("phone"))
            )
        )
    if not existing_c and customer.get("name"):
        existing_c = Customer(
            customer_id=cust_id,
            name=customer.get("name"),
            phone=customer.get("phone") or "",
            email=customer.get("email") or "",
            existing_pincode=address.get("pincode") or ""
        )
        db.add(existing_c)

    order_id = f"QCOM-{uuid4().hex[:10].upper()}"
    order = Order(order_id=order_id, session_id=session_id, customer_id=cust_id,
                  plan_id=plan["plan_id"], service_pincode=address.get("pincode", "500084"),
                  payment_status=payment["status"], amount_inr=plan["price_inr"], details=context)
    db.add(order)
    db.commit()
    return {"order_id": order_id, "status": "confirmed", "amount_inr": plan["price_inr"],
            "plan": plan, "service_address": address, "appointment": appointment}

