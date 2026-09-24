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
def _ensure_plan_record(db: Session, plan: dict) -> str | None:
    """Ensure the Plan record exists in the plans DB table. Returns plan_id."""
    plan_id = plan.get("plan_id") if plan else None
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
    return plan_id


@trace
def _upsert_customer_record(db: Session, customer: dict, address: dict, plan_id: str | None) -> Customer:
    """Create or update the Customer record for the given customer/address/plan info.

    Shared by full order creation and the lightweight pending-order persistence
    that runs right after appointment selection (see persist_pending_order).
    """
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
        incoming_cid = customer.get("customer_id")
        if incoming_cid and incoming_cid != existing_c.customer_id:
            raise ValueError(f"This phone number ({norm_phone}) is already registered. Please try a different new number.")
        existing_name = (existing_c.name or "").strip().lower()
        incoming_name = (customer.get("name") or "").strip().lower()
        if existing_name and incoming_name and existing_name != incoming_name and not incoming_cid:
            raise ValueError(f"This phone number ({norm_phone}) is already registered to an existing account. Please try a different new number.")

        if customer.get("name"):
            existing_c.name = customer.get("name")
        if raw_email:
            existing_c.email = raw_email
        if norm_phone:
            existing_c.phone = norm_phone
        if address.get("pincode"):
            existing_c.existing_pincode = address.get("pincode")
        if plan_id:
            existing_c.current_plan_id = plan_id
        existing_c.subscription_status = "ACTIVE"
        if not existing_c.joined_on:
            existing_c.joined_on = date.today()
        return existing_c

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
    return existing_c


@trace
def persist_pending_order(db: Session, session_id: str, context: dict) -> dict | None:
    """Persist the customer + an order snapshot right after appointment selection,
    independent of payment status.

    The real /create-order flow is gated on a completed payment, and payment is
    presently blocked by an unrelated payment-gateway registration issue. Without
    this, a customer who completes New Connection but never reaches a successful
    payment would never be saved anywhere, so the Existing Customer section could
    never recognize them.

    This creates (or, if the session already has a pending order, updates) an
    Order row with whatever payment status is currently known ("pending" if
    payment hasn't happened yet) so the customer immediately becomes a
    recognizable existing customer, while the normal create_order flow still
    runs later for the authoritative "completed" order once/if payment succeeds
    (and will reuse the same order_id rather than duplicating it).

    Returns None (instead of raising) when required info isn't present yet, so
    callers can treat this as a best-effort side effect.
    """
    customer = context.get("customer") or {}
    plan = context.get("selected_plan")
    address = context.get("service_address") or context.get("qualified_address") or {}
    appointment = context.get("appointment")

    if not plan or not _has_complete_service_address(address) or not appointment:
        return None
    if not (customer.get("phone") or customer.get("email")):
        return None

    plan_id = _ensure_plan_record(db, plan)
    existing_c = _upsert_customer_record(db, customer, address, plan_id)

    payment = context.get("payment") or {}
    payment_status = payment.get("status") or "pending"

    existing_order_id = context.get("order_id")
    order = db.scalar(select(Order).where(Order.order_id == existing_order_id)) if existing_order_id else None

    if order:
        order.plan_id = plan_id
        order.service_pincode = address.get("pincode") or order.service_pincode
        order.payment_status = payment_status
        order.amount_inr = plan.get("price_inr", order.amount_inr)
        order.details = context
        order.customer_id = existing_c.customer_id
    else:
        order_id = f"QCOM-{uuid4().hex[:10].upper()}"
        order = Order(
            order_id=order_id,
            session_id=session_id,
            customer_id=existing_c.customer_id,
            plan_id=plan_id,
            service_pincode=address.get("pincode", "500084"),
            payment_status=payment_status,
            amount_inr=plan.get("price_inr", 0),
            details=context,
        )
        db.add(order)

    db.commit()
    db.refresh(existing_c)
    db.refresh(order)

    return {
        "order_id": order.order_id,
        "customer_id": existing_c.customer_id,
        "payment_status": order.payment_status,
    }


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
    plan_id = _ensure_plan_record(db, plan)

    # Normalize phone and ensure Customer record exists and is active in DB
    existing_c = _upsert_customer_record(db, customer, address, plan_id)
    cust_id = existing_c.customer_id

    # Reuse the pending order created at appointment-selection time (if any) so
    # we don't create a duplicate Order row once payment actually completes.
    existing_order_id = context.get("order_id")
    order = db.scalar(select(Order).where(Order.order_id == existing_order_id)) if existing_order_id else None

    if order:
        order_id = order.order_id
        order.customer_id = cust_id
        order.plan_id = plan_id
        order.service_pincode = address.get("pincode", order.service_pincode or "500084")
        order.payment_status = payment.get("status", "completed")
        order.amount_inr = plan["price_inr"]
        order.details = context
    else:
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

