import re

from sqlalchemy import select
from sqlalchemy.orm import Session
from app.models.customer import Customer
from app.models.plan import Plan
from app.models.order import Order
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
    norm_phone = normalize_phone(phone)
    return {"customer_id": None, "name": name, "phone": norm_phone, "email": email,
            "existing_pincode": existing_pincode}


@trace
def normalize_phone(phone: str) -> str:
    """Strip everything but digits, keeping the last 10 digits (drop country code if present)."""
    digits = re.sub(r"\D", "", str(phone or ""))
    return digits[-10:] if len(digits) >= 10 else digits


def _customer_to_dict(customer: Customer, db: Session | None = None) -> dict:
    data = {
        "customer_id": customer.customer_id,
        "name": customer.name,
        "phone": customer.phone,
        "email": customer.email,
        "existing_pincode": customer.existing_pincode,
        "current_plan_id": customer.current_plan_id,
        "subscription_status": customer.subscription_status,
        "joined_on": customer.joined_on.isoformat() if customer.joined_on else None,
    }
    if db:
        try:
            latest_order = db.execute(
                select(Order)
                .where((Order.customer_id == customer.customer_id) | (Order.session_id == customer.customer_id))
                .order_by(Order.created_at.desc())
            ).scalars().first()
            if latest_order:
                data["latest_order"] = {
                    "order_id": latest_order.order_id,
                    "plan_id": latest_order.plan_id,
                    "service_pincode": latest_order.service_pincode,
                    "amount_inr": latest_order.amount_inr,
                    "payment_status": latest_order.payment_status,
                    "details": latest_order.details or {},
                    "created_at": latest_order.created_at.isoformat() if latest_order.created_at else None,
                }
        except Exception:
            pass
    return data


@trace
def find_customer_by_phone(db: Session, phone: str) -> dict | None:
    """Look up an existing customer with an active subscription by phone number.

    Returns a plain dict (safe to drop into session state) or None if no
    customer matches.
    """
    normalized = normalize_phone(phone)
    if len(normalized) != 10:
        return None
    customer = db.execute(
        select(Customer).where(Customer.phone == normalized)
    ).scalar_one_or_none()
    return _customer_to_dict(customer, db=db) if customer else None


@trace
def list_all_plans(db: Session) -> list[dict]:
    plans = db.execute(select(Plan).order_by(Plan.price_inr)).scalars().all()
    plans_list = [
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
    seen_ids = {p["plan_id"] for p in plans_list}

    # Merge regional plans catalog so regional plans are recognized for upgrades/downgrades
    try:
        from app.services.plan_service import _load_regional_plans
        regional_dict = _load_regional_plans()
        for circle, circle_plans in regional_dict.items():
            for p in circle_plans:
                p_id = p.get("plan_id")
                if p_id and p_id not in seen_ids:
                    plans_list.append({
                        "plan_id": p_id,
                        "name": p.get("name", "Broadband Plan"),
                        "speed_mbps": int(p.get("speed_mbps", 100)),
                        "price_inr": int(p.get("price_inr", 799)),
                        "type": p.get("type", "broadband"),
                        "min_speed_required": int(p.get("min_speed_required", 0)),
                        "description": p.get("description", ""),
                        "ott_bundle": p.get("ott_bundle", []),
                    })
                    seen_ids.add(p_id)
    except Exception:
        pass

    return sorted(plans_list, key=lambda p: p["price_inr"])


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
    return _customer_to_dict(customer, db=db)


@trace
def update_customer_details(
    db: Session,
    customer_id: str,
    name: str | None = None,
    email: str | None = None,
    phone: str | None = None,
    pincode: str | None = None,
) -> dict | None:
    """Update profile details for an existing customer in SQLite database."""
    customer = db.execute(
        select(Customer).where(Customer.customer_id == customer_id)
    ).scalar_one_or_none()
    if not customer:
        return None
    if name:
        customer.name = name.strip()
    if email:
        customer.email = email.strip()
    if phone:
        customer.phone = normalize_phone(phone)
    if pincode:
        customer.existing_pincode = str(pincode).strip()
    db.commit()
    db.refresh(customer)
    return _customer_to_dict(customer, db=db)

