from datetime import date
from uuid import uuid4
from sqlalchemy import select
from sqlalchemy.orm import Session
from app.models.order import Order
from app.models.customer import Customer
from app.models.plan import Plan
from app.services.customer_service import normalize_phone
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

    # Ensure Plan record exists in plans DB table
    plan_id = plan.get("plan_id")
    if plan_id:
        db_plan = db.scalar(select(Plan).where(Plan.plan_id == plan_id))
        if not db_plan:
            db_plan = Plan(
                plan_id=plan_id,
                name=plan.get("name", "Broadband Plan"),
                speed_mbps=int(plan.get("speed_mbps", 100)),
                price_inr=int(plan.get("price_inr", 799)),
                type=plan.get("type", "broadband"),
                min_speed_required=int(plan.get("min_speed_required", 0)),
            )
            db.add(db_plan)

    # Normalize phone and ensure Customer record exists and is active in DB
    raw_phone = customer.get("phone", "")
    norm_phone = normalize_phone(raw_phone)
    raw_email = (customer.get("email") or "").strip()
    cust_id = customer.get("customer_id") or f"CUST-{uuid4().hex[:6].upper()}"

    existing_c = None
    if norm_phone or raw_email:
        existing_c = db.scalar(
            select(Customer).where(
                (Customer.phone == norm_phone) | ((Customer.email == raw_email) & (Customer.email != ""))
            )
        )

    if existing_c:
        cust_id = existing_c.customer_id
        if customer.get("name"):
            existing_c.name = customer.get("name")
        if raw_email:
            existing_c.email = raw_email
        if norm_phone:
            existing_c.phone = norm_phone
        if address.get("pincode"):
            existing_c.existing_pincode = address.get("pincode")
        existing_c.current_plan_id = plan_id
        existing_c.subscription_status = "ACTIVE"
        if not existing_c.joined_on:
            existing_c.joined_on = date.today()
    else:
        existing_c = Customer(
            customer_id=cust_id,
            name=customer.get("name") or "Valued Customer",
            phone=norm_phone,
            email=raw_email,
            existing_pincode=address.get("pincode") or "",
            current_plan_id=plan_id,
            subscription_status="ACTIVE",
            joined_on=date.today(),
        )
        db.add(existing_c)

    order_id = f"QCOM-{uuid4().hex[:10].upper()}"
    order = Order(
        order_id=order_id,
        session_id=session_id,
        customer_id=cust_id,
        plan_id=plan_id,
        service_pincode=address.get("pincode", "500084"),
        payment_status=payment.get("status", "completed"),
        amount_inr=plan["price_inr"],
        details=context,
    )
    db.add(order)
    db.commit()
    db.refresh(existing_c)
    db.refresh(order)

    return {
        "order_id": order_id,
        "customer_id": cust_id,
        "status": "confirmed",
        "amount_inr": plan["price_inr"],
        "plan": plan,
        "service_address": address,
        "appointment": appointment,
        "customer": {
            "customer_id": existing_c.customer_id,
            "name": existing_c.name,
            "phone": existing_c.phone,
            "email": existing_c.email,
            "current_plan_id": existing_c.current_plan_id,
        },
    }

