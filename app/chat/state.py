from typing import Literal, TypedDict
from app.utils.trace import trace, trace_async


ResponseMode = Literal["deterministic", "gemini"]


class ConversationState(TypedDict):
    session_id: str
    messages: list[dict]
    intent: str | None
    pincode: str | None
    street_address: str | None
    requires_full_address: bool
    address_qualified: bool
    address_confirmed: bool
    qualified_address: dict | None
    serviceable: bool | None
    customer: dict | None
    recommended_plans: list[dict] | None
    plans_shown: bool
    selected_plan: dict | None
    service_address: dict | None
    appointment: dict | None
    payment_status: str | None
    order_id: str | None
    missing_fields: list[str]
    awaiting_confirmation: bool
    response_mode: ResponseMode
    last_response: dict | None
    structured_customer: dict | None
    is_existing_customer: bool
    catalog_plans: list[dict] | None
    available_addons: list[dict] | None
    execution_path: list[str]
    gemini_called: bool
    invalid_pincode_error: bool
    pincode_unserviceable: bool
    existing_customer_verified: bool
    current_plan: dict | None
    plan_change_target: dict | None
    plan_change_confirmed: bool


@trace
def empty_state(session_id: str) -> ConversationState:
    return {
        "session_id": session_id,
        "messages": [],
        "intent": None,
        "pincode": None,
        "street_address": None,
        "requires_full_address": False,
        "address_qualified": False,
        "address_confirmed": False,
        "qualified_address": None,
        "serviceable": None,
        "customer": None,
        "recommended_plans": None,
        "plans_shown": False,
        "selected_plan": None,
        "service_address": None,
        "appointment": None,
        "payment_status": None,
        "order_id": None,
        "missing_fields": [],
        "awaiting_confirmation": False,
        "response_mode": "deterministic",
        "last_response": None,
        "structured_customer": None,
        "is_existing_customer": False,
        "catalog_plans": None,
        "available_addons": None,
        "execution_path": [],
        "gemini_called": False,
        "invalid_pincode_error": False,
        "pincode_unserviceable": False,
        "existing_customer_verified": False,
        "current_plan": None,
        "plan_change_target": None,
        "plan_change_confirmed": False,
    }


@trace
def state_from_session(session_id: str, stored: dict | None) -> ConversationState:
    state = empty_state(session_id)
    if not stored:
        return state
    for field in state:
        if field in stored:
            state[field] = stored[field]
    # Preserve data written by the legacy direct endpoints.
    qualified = stored.get("qualified_address", {})
    if qualified:
        state["pincode"] = state["pincode"] or qualified.get("pincode")
        if qualified.get("serviceable") is not None:
            state["serviceable"] = qualified.get("serviceable")
        state["street_address"] = state["street_address"] or qualified.get("street_address")
        state["address_qualified"] = bool(state["address_qualified"] or qualified.get("address_qualified"))
        state["requires_full_address"] = bool(state["requires_full_address"] or qualified.get("requires_full_address"))
        state["qualified_address"] = qualified
    state["recommended_plans"] = state["recommended_plans"] or stored.get("recommended_plans")
    state["address_confirmed"] = bool(stored.get("address_confirmed", False))
    state["plans_shown"] = bool(stored.get("plans_shown", False))
    state["selected_plan"] = state["selected_plan"] or stored.get("selected_plan")
    state["service_address"] = state["service_address"] or stored.get("service_address")
    state["appointment"] = state["appointment"] or stored.get("appointment")
    customer = state["customer"] or stored.get("customer")
    state["customer"] = customer
    payment = stored.get("payment", {})
    state["payment_status"] = state["payment_status"] or payment.get("status")
    return state


def state_for_response(state: ConversationState) -> dict:
    return {key: value for key, value in state.items() if key not in {"last_response", "execution_path", "gemini_called", "structured_customer"}}
