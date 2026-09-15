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


def _base_plans_list(db: Session) -> list[dict]:
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
def list_all_plans(db: Session) -> list[dict]:
    """All plans across every region, merged. Used when a customer's region is
    unknown; prefer list_region_plans(db, region) when the region is known so
    customers only see plans available in their own region."""
    plans_list = _base_plans_list(db)
    seen_ids = {p["plan_id"] for p in plans_list}

    # Merge full regional plans catalog (every circle)
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
def list_region_plans(db: Session, region: str | None) -> list[dict]:
    """Plans for one telecom circle from the regional catalog only.

    Does not merge the nationwide SQLite catalog or other circles — existing
    customers should only see plans for their stored region.
    """
    if not region:
        return list_all_plans(db)

    try:
        from app.services.plan_service import _load_regional_plans
        regional_dict = _load_regional_plans()
        circle_plans = regional_dict.get(region) or []
        plans_list = [
            {
                "plan_id": p.get("plan_id"),
                "name": p.get("name", "Broadband Plan"),
                "speed_mbps": int(p.get("speed_mbps", 100)),
                "price_inr": int(p.get("price_inr", 799)),
                "type": p.get("type", "broadband"),
                "min_speed_required": int(p.get("min_speed_required", 0)),
                "description": p.get("description", ""),
                "ott_bundle": p.get("ott_bundle", []),
            }
            for p in circle_plans
            if p.get("plan_id")
        ]
        if plans_list:
            return sorted(plans_list, key=lambda p: p.get("speed_mbps") or 0)
    except Exception:
        pass

    return list_all_plans(db)


@trace
def get_customer_region(customer: dict | None) -> str | None:
    """Determine a customer's telecom circle/region from their own order/profile
    data: prefers the address captured on their most recent order (the region
    selected during the General -> New Connection -> Order flow), falling back
    to their stored existing_pincode for customers with no order on file
    (e.g. the static customers.csv seed data)."""
    if not customer:
        return None

    from app.services.address_service import get_telecom_circle

    latest_order = customer.get("latest_order") or {}
    order_details = latest_order.get("details") or {}
    addr = order_details.get("service_address") or order_details.get("qualified_address") or {}

    state = addr.get("state", "")
    city = addr.get("city", "")
    pincode = addr.get("pincode") or latest_order.get("service_pincode") or customer.get("existing_pincode") or ""

    if not (state or city or pincode):
        return None
    return get_telecom_circle(state=state, city=city, pincode=pincode)


@trace
def get_upgrade_downgrade_options(db: Session, current_plan_id: str | None, region: str | None = None) -> dict:
    """Split the plan catalog into upgrade/downgrade options relative to current_plan_id.

    When region is given, only that region's plans (plus the shared base
    catalog) are considered, so a customer never sees another region's plans.
    Returns {"current": dict|None, "upgrades": [...], "downgrades": [...]},
    with both candidate lists ordered by speed ascending.
    """
    all_plans = list_region_plans(db, region)
    current = next((p for p in all_plans if p["plan_id"] == current_plan_id), None)

    if not current and current_plan_id:
        # Current plan wasn't in this region's catalog (e.g. legacy data) -
        # still show it for reference, but keep upgrade/downgrade options
        # scoped to the customer's own region only.
        current = next((p for p in list_all_plans(db) if p["plan_id"] == current_plan_id), None)

    def _by_speed(plan: dict) -> int:
        return int(plan.get("speed_mbps") or 0)

    if not current:
        return {"current": None, "upgrades": sorted(all_plans, key=_by_speed), "downgrades": []}

    current_speed = _by_speed(current)
    upgrades = sorted(
        [p for p in all_plans if _by_speed(p) > current_speed],
        key=_by_speed,
    )
    downgrades = sorted(
        [p for p in all_plans if _by_speed(p) < current_speed],
        key=_by_speed,
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

