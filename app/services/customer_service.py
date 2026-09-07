import re

from sqlalchemy import select
from sqlalchemy.orm import Session
from app.models.customer import Customer
from app.models.plan import Plan
from app.utils.trace import trace, trace_async


@trace
def find_or_validate(db: Session, customer_id: str | None = None, name: str | None = None, phone: str | None = None,
                     email: str | None = None, existing_pincode: str | None = None) -> dict:
    customer = db.scalar(select(Customer).where(Customer.customer_id == customer_id)) if customer_id else None
    if customer:
        return {"customer_id": customer.customer_id, "name": customer.name, "phone": customer.phone,
                "email": customer.email, "existing_pincode": customer.existing_pincode}
    if not name or not phone or not email:
        raise ValueError("name, phone, and email are required")
    return {"customer_id": None, "name": name, "phone": phone, "email": email,
            "existing_pincode": existing_pincode}


@trace
def normalize_phone(phone: str) -> str:
    """Strip everything but digits, keeping the last 10 digits (drop country code if present)."""
    digits = re.sub(r"\D", "", phone or "")
    return digits[-10:] if len(digits) >= 10 else digits


def _customer_to_dict(customer: Customer) -> dict:
    return {
        "customer_id": customer.customer_id,
        "name": customer.name,
        "phone": customer.phone,
        "email": customer.email,
        "existing_pincode": customer.existing_pincode,
        "current_plan_id": customer.current_plan_id,
        "subscription_status": customer.subscription_status,
    }


@trace
def find_customer_by_phone(db: Session, phone: str) -> dict | None:
    """Look up an existing customer with an active subscription by phone number.

    Returns a plain dict (safe to drop into session state) or None if no
    active customer matches - the caller decides how to message that.
    """
    normalized = normalize_phone(phone)
    if len(normalized) != 10:
        return None
    customer = db.execute(
        select(Customer).where(Customer.phone == normalized)
    ).scalar_one_or_none()
    return _customer_to_dict(customer) if customer else None


@trace
def list_all_plans(db: Session) -> list[dict]:
    plans = db.execute(select(Plan).order_by(Plan.price_inr)).scalars().all()
    return [
        {
            "plan_id": p.plan_id,
            "name": p.name,
            "speed_mbps": p.speed_mbps,
            "price_inr": p.price_inr,
            "type": p.type,
            "min_speed_required": p.min_speed_required,
        }
        for p in plans
    ]


@trace
def get_upgrade_downgrade_options(db: Session, current_plan_id: str | None) -> dict:
    """Split the full plan catalog into upgrade/downgrade options relative to current_plan_id.

    Returns {"current": dict|None, "upgrades": [...], "downgrades": [...]},
    each list ordered closest-to-current-price first.
    """
    all_plans = list_all_plans(db)
    current = next((p for p in all_plans if p["plan_id"] == current_plan_id), None)

    if not current:
        return {"current": None, "upgrades": all_plans, "downgrades": []}

    upgrades = sorted(
        [p for p in all_plans if p["price_inr"] > current["price_inr"]],
        key=lambda p: p["price_inr"],
    )
    downgrades = sorted(
        [p for p in all_plans if p["price_inr"] < current["price_inr"]],
        key=lambda p: -p["price_inr"],
    )
    return {"current": current, "upgrades": upgrades, "downgrades": downgrades}


@trace
def apply_plan_change(db: Session, customer_id: str, new_plan_id: str) -> dict | None:
    """Commit a plan change for a customer. Returns the updated customer dict, or None if not found."""
    customer = db.execute(
        select(Customer).where(Customer.customer_id == customer_id)
    ).scalar_one_or_none()
    if not customer:
        return None
    customer.current_plan_id = new_plan_id
    db.commit()
    db.refresh(customer)
    return _customer_to_dict(customer)

