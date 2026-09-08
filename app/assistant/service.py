"""Modular assistant orchestration service for Signal Selector platform.

Architectural Workflow:
1. RAG FAQ Flow (Default): Answers general telecom FAQs, router specs, SLAs, and troubleshooting grounded strictly in data/faq_knowledge_base.md using pure LangChain RAG (no LangGraph).
2. Transition Guardrail: One-way state transition from RAG to ORDER_FLOW triggered by address/pincode input or explicit ordering intent. Once locked in ORDER_FLOW, session CANNOT revert to RAG.
3. Order Flow: Address qualification (Mapbox with Nominatim fallback) -> Regional plan cards -> LLM Plan Recommendation Assistant (Non-RAG) -> Customer Details -> Installation Appointment -> Payment & Order Creation.
"""
from __future__ import annotations

import logging
import re
from uuid import uuid4
from typing import Any

from sqlalchemy.orm import Session

from app.assistant.llm import generate, generate_json, classify_conversation_route
from app.assistant.plan_recommendation import recommend_plan_conversational
from app.assistant.prompts import get_prompt, set_current_language
from app.chat.session import session_store
from app.chat.state import state_for_response, state_from_session, ConversationState
from app.rag.chroma_rag import query_faq_collection, generate_grounded_faq_answer
from app.services.address_service import qualify, _is_invalid_or_dummy_pincode, clean_street_address, extract_street_address_llm
from app.services.appointment_service import available_slots, select_slot
from app.services.customer_service import (
    find_or_validate,
    find_customer_by_phone,
    get_upgrade_downgrade_options,
    apply_plan_change,
    normalize_phone,
)
from app.services.order_service import create_order
from app.services.payment_service import create_purl, confirm_payment
from app.services.plan_service import recommend
from app.services.welcome_service import generate_dynamic_greeting, generate_contextual_followups
from app.utils.trace import trace, trace_async

logger = logging.getLogger(__name__)


@trace
def _conversation_id(session: dict) -> str:
    conversation_id = session.get("conversation_id")
    if not conversation_id:
        conversation_id = f"CONV-{uuid4().hex[:12].upper()}"
        session["conversation_id"] = conversation_id
    return conversation_id


@trace
def _reset_address_state(session: dict) -> None:
    """Reset all address, qualification, and plan selection fields in session."""
    session["pincode"] = None
    session["street_address"] = None
    session["qualified_address"] = None
    session["address_qualified"] = False
    session["address_confirmed"] = False
    session["awaiting_address_confirmation"] = False
    session["awaiting_plan_permission"] = False
    session["plans_shown"] = False
    session["catalog_plans"] = []
    session["recommended_plans"] = []
    session["requires_full_address"] = False
    session["address_prompt_count"] = 0
    session["recommendation_stage"] = 0
    session["recommendation_answers"] = []


@trace
def _generate_address_confirmation_prompt(formatted_address: str) -> str:
    """Generate a dynamic 2-line LLM message: Line 1 asks to confirm address, Line 2 explains proceeding to plans."""
    prompt = get_prompt(
        "service.address_confirmation",
        formatted_address=formatted_address or "",
    )
    try:
        text = generate(prompt, temperature=0.7, timeout=5, max_tokens=70)
        if text and len(text.strip()) > 10:
            cleaned = text.strip()
            if "\n" not in cleaned:
                cleaned = re.sub(r"(\.|\!|\?)\s+(So |Confirming |Once |This will |Proceeding )", r"\1\n\2", cleaned)
            lines = cleaned.split("\n")
            if "?" not in lines[0]:
                lines[0] = lines[0].rstrip(".") + ". Is this your correct address?"
                cleaned = "\n".join(lines)
            return cleaned
    except Exception as exc:
        logger.warning("LLM address confirmation prompt error: %s", exc)
    return f"Your address at {formatted_address} is verified as serviceable. Is this your correct address?\nConfirming this allows us to proceed with showing the available fiber plans in your region."


@trace
def _generate_plan_permission_prompt(formatted_address: str) -> str:
    """Generate a dynamic 1-sentence LLM question asking permission to show fiber plans."""
    prompt = get_prompt(
        "service.plan_permission",
        formatted_address=formatted_address or "",
    )
    try:
        text = generate(prompt, temperature=0.7, timeout=5, max_tokens=50)
        if text and len(text.strip()) > 10:
            return text.strip()
    except Exception as exc:
        logger.warning("LLM plan permission prompt error: %s", exc)
    return "Great! Address confirmed. Shall I show the available high-speed fiber plans for your location?"


@trace
def classify_confirmation_intent(message: str) -> str:
    """Classify user confirmation response into CONFIRM, DENY, or OTHER using LLM JSON mode."""
    prompt = get_prompt("service.confirmation_intent", message=message)
    try:
        data = generate_json(prompt, system=get_prompt("service.confirmation_intent.system"), timeout=5)
        if data and data.get("intent") in {"CONFIRM", "DENY", "OTHER"}:
            return str(data.get("intent"))
    except Exception as exc:
        logger.warning("LLM confirmation intent classification error: %s", exc)

    low = message.lower().strip()
    words = set(re.findall(r"\b\w+\b", low))
    confirm_words = {"yes", "yeah", "yep", "sure", "ok", "okay", "correct", "confirm", "right", "show", "proceed", "agreed", "please"}
    deny_words = {"no", "nope", "wrong", "change", "incorrect", "different", "cancel"}

    if any(w in words for w in confirm_words):
        return "CONFIRM"
    if any(w in words for w in deny_words):
        return "DENY"
    return "OTHER"


@trace
def classify_plan_selection_intent(message: str) -> str:
    """Classify user intent during plan selection into RECOMMENDATION_REQUEST or FAQ_QUESTION using LLM JSON mode."""
    low = message.lower().strip()
    words = set(re.findall(r"\b\w+\b", low))
    reco_tokens = {
        "yes", "yeah", "yep", "sure", "ok", "okay", "please", "recommend", "recommendation",
        "best", "suggest", "suggestion", "guide", "help", "choose", "suitable", "gaming", "stream"
    }
    if any(w in words for w in reco_tokens) or "help me choose" in low or "yes please" in low:
        return "RECOMMENDATION_REQUEST"

    prompt = get_prompt("service.plan_selection_intent", message=message)
    try:
        data = generate_json(prompt, system=get_prompt("service.plan_selection_intent.system"), timeout=5)
        if data and data.get("intent") in {"RECOMMENDATION_REQUEST", "FAQ_QUESTION"}:
            return str(data.get("intent"))
    except Exception as exc:
        logger.warning("LLM plan selection intent classification error: %s", exc)

    return "FAQ_QUESTION"


@trace
def _generate_plans_unlocked_message(formatted_address: str, state_or_region: str, plan_count: int) -> str:
    """Generate a dynamic LLM message announcing regional plan cards unlocked with an enthusiastic achievement tone + follow-up question on next line."""
    prompt = get_prompt(
        "service.plans_unlocked",
        formatted_address=formatted_address or "",
        state_or_region=state_or_region or "your region",
        plan_count=plan_count or 0,
    )
    try:
        text = generate(prompt, temperature=0.7, timeout=5, max_tokens=60)
        if text and len(text.strip()) > 10:
            cleaned = text.strip()
            cleaned = re.sub(r"(\.|\!|\?)\s+(Which|Would|Shall)", r"\1\n\2", cleaned)
            if "\n" not in cleaned:
                cleaned = re.sub(r"(\.|\!|\?)\s+", r"\1\n", cleaned, count=1)
            return cleaned
    except Exception as exc:
        logger.warning("LLM plans unlocked message error: %s", exc)
    return f"Great news! We found high-speed fiber plans available for {state_or_region} listed below.\nWhich plan suits you best, or would you like a recommendation?"


@trace
def _generate_pincode_only_prompt(pincode: str, city: str | None = None, state: str | None = None) -> str:
    """Generate a dynamic LLM message when customer provides only a pincode, explaining complete address is required."""
    location_info = f"in {city}, {state}" if city and state else (f"in {city}" if city else "")
    prompt = get_prompt(
        "service.pincode_only",
        pincode=pincode or "",
        city=city or "",
        state=state or "",
        location_info=location_info or "",
    )
    try:
        text = generate(prompt, temperature=0.7, timeout=5, max_tokens=70)
        if text and len(text.strip()) > 10:
            return text.strip()
    except Exception as exc:
        logger.warning("LLM pincode-only prompt error: %s", exc)
    return (
        f"PIN code {pincode} {location_info} is in our service area! However, a PIN code alone is not sufficient. "
        "Please share your complete street address (house/flat number, building name, street, and locality) so we can verify exact coverage and unlock fiber plans."
    )


@trace
def _generate_prompt_complete_address(pincode: str | None = None, user_message: str | None = None) -> str:
    """Generate a dynamic LLM message requesting the customer's complete street address."""
    pin_context = f" for PIN code {pincode}" if pincode else ""
    user_context = f"\nCustomer request: '{user_message}'" if user_message else ""
    prompt = get_prompt(
        "service.complete_address",
        pincode=pincode or "",
        pin_context=pin_context,
        user_context=user_context,
    )
    try:
        text = generate(prompt, temperature=0.7, timeout=5, max_tokens=70)
        if text and len(text.strip()) > 10:
            return text.strip()
    except Exception as exc:
        logger.warning("LLM complete address prompt error: %s", exc)
    return "Thank you for choosing Signal Selector! To get started with your new connection, please share your complete street address (house/flat number, street name, locality, and 6-digit pincode) so we can verify exact serviceability."


@trace
def _generate_invalid_pincode_message(pincode: str) -> str:
    """Generate a dynamic LLM response for invalid Indian postal PIN code input."""
    prompt = get_prompt("service.invalid_pincode", pincode=pincode or "")
    try:
        text = generate(prompt, temperature=0.7, timeout=5, max_tokens=65)
        if text and len(text.strip()) > 10:
            return text.strip()
    except Exception as exc:
        logger.warning("LLM invalid pincode message error: %s", exc)
    return f"Sorry, PIN code '{pincode}' is invalid. Indian postal PIN codes are 6 digits starting with numbers 1 through 8. Please share your valid complete street address including correct PIN code."


@trace
def _generate_unserviceable_message(pincode: str, fallback_message: str | None = None) -> str:
    """Generate a dynamic LLM response for unserviceable location."""
    prompt = get_prompt(
        "service.unserviceable",
        pincode=pincode or "",
        fallback_message=fallback_message or "",
    )
    try:
        text = generate(prompt, temperature=0.7, timeout=5, max_tokens=65)
        if text and len(text.strip()) > 10:
            return text.strip()
    except Exception as exc:
        logger.warning("LLM unserviceable message error: %s", exc)
    return fallback_message or f"Sorry, our fiber services are currently unavailable at PIN code {pincode}. We are expanding soon! Would you like to check a different complete street address?"


@trace
def _generate_escape_reset_message() -> str:
    """Generate a dynamic LLM response when user wants to reset or change address."""
    prompt = get_prompt("service.escape_reset")
    try:
        text = generate(prompt, temperature=0.7, timeout=5, max_tokens=60)
        if text and len(text.strip()) > 10:
            return text.strip()
    except Exception as exc:
        logger.warning("LLM escape reset message error: %s", exc)
    return "No problem! Let's start fresh. Please share your complete street address (house/flat number, street name, locality, and pincode)."


@trace
def initialize_session(
    session_id: str | None = None,
    *,
    channel: str = "WEB",
    locale: str = "en-US",
    source: str = "SIGNAL_SELECTOR",
    profile: str = "general",
    language: str = "en",
) -> dict:
    """Initialize a session and generate a fresh, dynamic welcome greeting."""
    session_id = session_id or f"SES-{uuid4().hex[:12].upper()}"
    session = session_store.create(session_id)
    conversation_id = _conversation_id(session)

    is_existing = profile == "existing"
    mode = "ORDER_FLOW" if is_existing else "RAG"
    workflow_state = "EXISTING_CUSTOMER" if is_existing else "RAG_FAQ"

    session.update({
        "mode": mode,
        "workflow_state": workflow_state,
        "channel": channel,
        "locale": locale,
        "source": source,
        "profile": profile,
        "is_existing_customer": is_existing,
        "language": language,
        "address_qualified": False,
        "plans_shown": False,
    })

    set_current_language(language)
    welcome = generate_dynamic_greeting(profile=profile)
    followups = generate_contextual_followups(
        message="",
        answer=welcome,
        profile=profile,
        conversation_history=[],
        previous_suggestions=[],
    )

    session["welcome"] = welcome
    session["recommended_followups"] = followups
    session["shown_suggestions"] = list(followups)
    session.setdefault("conversation_history", []).append({"role": "assistant", "content": welcome, "kind": "welcome"})

    logger.info("Session initialized: session_id=%s, conversation_id=%s", session_id, conversation_id)
    updated_state = state_for_response(state_from_session(session_id, session))

    return {
        "sessionId": session_id,
        "conversationId": conversation_id,
        "channel": channel,
        "locale": locale,
        "source": source,
        "status": "ACTIVE",
        "response": welcome,
        "recommended_followups": followups,
        "recommendedFollowups": followups,
        "mode": mode,
        "workflowState": workflow_state,
        "updatedState": updated_state,
    }


@trace
def _extract_pincode(text: str) -> str | None:
    """Extract a 6-digit Indian PIN code from text."""
    match = re.search(r"\b([1-9][0-9]{5})\b", text)
    if match:
        return match.group(1)
    return None


@trace
def _is_escape_intent(text: str) -> bool:
    """Detect if user wants to reset, change address, or leave the current sub-flow."""
    low = text.lower().strip()
    words = set(re.findall(r"\b\w+\b", low))
    if "no" in words or "nope" in words:
        return True
    escape_phrases = (
        "change address", "different address", "wrong address", "go back",
        "start over", "cancel", "reset", "new address", "change pincode",
        "different pincode", "other pincode", "change location",
    )
    return any(p in low for p in escape_phrases)


@trace
def _is_order_intent_trigger(text: str) -> bool:
    """Check if text expresses explicit intent to start an order or check serviceability."""
    low = text.lower().strip()

    if _extract_pincode(text):
        return True

    # 1. General info / plan inquiries stay in RAG flow unless explicit purchase/coverage intent is present
    info_inquiry_phrases = (
        "what are", "what is", "tell me", "show me", "how much", "which plan",
        "recommend", "compare", "options", "details", "explain", "plans available",
        "available plans", "list plans", "standard plans", "broadband plans", "what plans",
        "choose the right plan", "help me choose"
    )
    if any(q in low for q in info_inquiry_phrases) and not any(k in low for k in ["buy", "book", "purchase", "subscribe", "check coverage", "check serviceability", "new connection"]):
        return False

    # 2. Direct purchase action words or serviceability check keywords
    order_action_keywords = (
        "buy", "book", "purchase", "subscribe", "sign up", "get a new connection", "need a new connection",
        "i want a new connection", "want to buy", "want to book", "want to get a connection", "check coverage",
        "check serviceability", "my pincode", "my address", "pincode is", "pin code is", "located at"
    )
    if any(w in low for w in order_action_keywords):
        return True

    # 3. Connection order phrases
    order_phrases = (
        "new connection", "new fiber", "new fibre", "order plan", "order fiber",
        "get fiber", "get broadband", "get a connection", "get new connection", "book a connection",
        "i want a new fiber", "i want to book", "i want to get a new"
    )
    return any(p in low for p in order_phrases)


@trace
def _is_explicit_plan_search_intent(text: str) -> bool:
    """Check if the user is explicitly searching or asking to view standard broadband plans."""
    low = text.lower().strip()
    plan_keywords = (
        "what plans", "which plan", "show plans", "list plans", "available plans",
        "standard plans", "broadband plans", "fiber plans", "what are the plans",
        "tell me the plans", "plan details", "pricing plans", "tariffs", "plans available"
    )
    order_keywords = ("buy", "book", "purchase", "subscribe", "get a new", "want to book", "i want a new", "need a new", "get connection")
    if any(p in low for p in plan_keywords) and not any(k in low for k in order_keywords):
        return True
    return False


@trace
def _is_explicit_order_booking_intent(text: str) -> bool:
    """Check if the user is expressing intent to book, get, or order a new connection."""
    low = text.lower().strip()
    order_keywords = (
        "buy", "book", "purchase", "subscribe", "sign up", "get a new", "need a new",
        "i want a new", "want to buy", "want to book", "want to get", "check coverage",
        "check serviceability", "new connection", "new fiber", "new fibre", "order plan",
        "order fiber", "get fiber", "get broadband", "get a connection", "get new connection"
    )
    return any(k in low for k in order_keywords)


@trace
def _extract_customer_info(text: str) -> dict:
    """Extract Name, Phone, and Email from message."""
    email_match = re.search(r"[\w.+-]+@[\w.-]+\.[A-Za-z]{2,}", text)
    phone_match = re.search(r"(?<!\d)(?:\+91[- ]?)?([6-9]\d{9})(?!\d)", text)
    name_match = re.search(r"(?:name\s*[:\-]|name is|my name is|i am|i'm|^)\s*([A-Za-z][A-Za-z ]{1,50}?)(?=\s*[,;]|email|\b[a-zA-Z0-9._%+-]+@[a-zA-Z0-9.-]+\.[a-zA-Z]{2,}\b|$)", text, re.I)

    non_names = {
        "hi", "hello", "hey", "yes", "no", "order", "plan", "select", "speed", "price",
        "refund", "policy", "installation", "timeline", "router", "wifi", "wi-fi", "ethernet",
        "broadband", "fiber", "fibre", "connection", "signal", "selector", "help", "details",
        "what", "how", "when", "where", "why", "which", "tell", "show", "give", "book", "buy"
    }

    name = name_match.group(1).strip(" .,!") if name_match else None
    if name and any(w.lower() in non_names for w in name.lower().split()):
        if not re.search(r"(?:name\s*[:\-]|name is|my name is|i am|i'm)", text, re.I):
            name = None
        else:
            cleaned_words = [w for w in name.split() if w.lower() not in non_names]
            name = " ".join(cleaned_words) if cleaned_words else None

    return {
        "name": name if (name and len(name) >= 2) else None,
        "phone": phone_match.group(1) if phone_match else None,
        "email": email_match.group(0) if email_match else None,
    }


@trace
def handle_message(
    session_id: str,
    message: str,
    db: Session,
    *,
    language: str = "en",
    structured_fields: dict | None = None,
) -> dict:
    session = session_store.get(session_id)
    # Language can come from this call's explicit param, from a structured_fields
    # override (user switched language mid-conversation), or from what was
    # already set on the session (so it persists across turns by default).
    resolved_language = (
        (structured_fields or {}).get("language")
        or session.get("language")
        or language
    )
    session["language"] = resolved_language
    set_current_language(resolved_language)

    res = _handle_message_internal(
        session_id=session_id,
        message=message,
        db=db,
        language=language,
        structured_fields=structured_fields,
    )
    profile = session.get("profile", "general")
    ans = res.get("response", "")

    # Limit LLM response suggestions ONLY before entering order flow
    in_order_flow = bool(
        session.get("pincode") or
        session.get("address_qualified") or
        session.get("address_confirmed") or
        session.get("selected_plan") or
        session.get("customer") or
        session.get("appointment") or
        res.get("workflowState") in ["ADDRESS_QUALIFICATION", "ADDRESS_CONFIRMATION", "PLAN_SELECTION", "CUSTOMER_DETAILS", "APPOINTMENT", "PAYMENT", "ORDER_CONFIRMED"]
    )

    if not in_order_flow:
        shown = session.get("shown_suggestions", [])
        followups = generate_contextual_followups(
            message=message,
            answer=ans,
            profile=profile,
            conversation_history=session.get("conversation_history"),
            previous_suggestions=shown,
        )
        updated_shown = list(shown) + [f for f in followups if f not in shown]
        session["shown_suggestions"] = updated_shown[-30:]
    else:
        followups = []

    res["recommended_followups"] = followups
    res["recommendedFollowups"] = followups
    session["recommended_followups"] = followups
    return res


@trace
def _extract_phone(text: str) -> str | None:
    """Extract a 10-digit Indian mobile number from free text."""
    digits_only = re.sub(r"[\s\-()]", "", text or "")
    match = re.search(r"(?:\+?91)?([6-9]\d{9})\b", digits_only)
    return match.group(1) if match else None


@trace
def _plan_change_intent(text: str) -> str | None:
    """Classify an existing customer's message as UPGRADE, DOWNGRADE, or None."""
    low = (text or "").lower()
    if any(w in low for w in ("upgrade", "higher speed", "faster", "increase my plan", "boost")):
        return "UPGRADE"
    if any(w in low for w in ("downgrade", "lower speed", "cheaper", "reduce my plan", "save money")):
        return "DOWNGRADE"
    return None


@trace
def _handle_existing_customer_message(
    session_id: str,
    message: str,
    db: Session,
    session: dict,
    structured_fields: dict | None,
    conversation_id: str,
) -> dict:
    """Dedicated flow for the Existing Customer section: phone verification,
    current-plan lookup, and plan upgrade/downgrade - entirely separate from
    the new-connection RAG/ORDER_FLOW routing above.
    """

    def _respond(answer: str, workflow_state: str, **extra) -> dict:
        updated_state = state_for_response(state_from_session(session_id, session))
        return {
            "sessionId": session_id,
            "conversationId": conversation_id,
            "mode": "EXISTING_CUSTOMER",
            "intent": extra.pop("intent", "EXISTING_CUSTOMER"),
            "workflowState": workflow_state,
            "response": answer,
            "sources": [],
            "canStartNewConnection": True,
            "updatedState": updated_state,
            **extra,
        }

    # ---- Step 1: not yet verified - need a phone number ----
    if not session.get("existing_customer_verified"):
        phone_candidate = (
            (structured_fields or {}).get("phone")
            or _extract_phone(message)
        )
        if not phone_candidate:
            return _respond(
                "Welcome back! Please share the phone number registered on your account so I can pull up your details.",
                "AWAITING_PHONE_VERIFICATION",
            )

        customer = find_customer_by_phone(db, phone_candidate)
        if not customer:
            return _respond(
                f"I couldn't find an account registered with {normalize_phone(phone_candidate)}. "
                "Please double-check the number, or say 'new connection' if you'd like to sign up instead.",
                "PHONE_NOT_FOUND",
            )

        session["existing_customer_verified"] = True
        session["customer"] = customer

        options = get_upgrade_downgrade_options(db, customer.get("current_plan_id"))
        current_plan = options["current"]
        session["current_plan"] = current_plan

        order_info_lines = []
        latest_order = customer.get("latest_order")
        if latest_order:
            order_id = latest_order.get("order_id")
            order_details = latest_order.get("details") or {}
            appt = order_details.get("appointment") or {}
            addr = order_details.get("service_address") or order_details.get("qualified_address") or {}
            addr_str = addr.get("formatted_address") or addr.get("street_address") or customer.get("existing_pincode")
            appt_str = f"{appt.get('date', 'Upcoming')} ({appt.get('time_window', 'Standard Slot')})" if appt else "Active"
            order_info_lines.append(f"\n• **Latest Order ID:** {order_id}")
            if addr_str:
                order_info_lines.append(f"• **Installation Address:** {addr_str}")
            if appt_str:
                order_info_lines.append(f"• **Installation Slot:** {appt_str}")

        order_info_text = "\n".join(order_info_lines)

        if not current_plan:
            greeting = f"Welcome back, {customer['name']}! I found your account registered with {customer['phone']}."
            if order_info_text:
                greeting += f"\n\n**Account & Order Summary:**{order_info_text}"
            greeting += "\n\nWould you like to browse our high-speed fiber plans to get started?"
            return _respond(
                greeting,
                "NO_ACTIVE_PLAN",
                catalog_plans=options["upgrades"],
            )

        greeting = (
            f"Welcome back, **{customer['name']}**!\n\n"
            f"**Your Account Summary:**\n"
            f"• **Registered Phone:** {customer['phone']}\n"
            f"• **Email:** {customer['email'] or 'Not provided'}\n"
            f"• **Active Plan:** {current_plan['name']} ({current_plan['speed_mbps']} Mbps) at ₹{current_plan['price_inr']}/month"
        )
        if order_info_text:
            greeting += order_info_text

        greeting += (
            "\n\nWould you like to **upgrade** for more speed, **downgrade** to save, "
            "check order status, update account details, or ask any service questions?"
        )

        return _respond(
            greeting,
            "PLAN_OVERVIEW",
            current_plan=current_plan,
            upgrade_options=options["upgrades"],
            downgrade_options=options["downgrades"],
        )

    # ---- Step 2: verified - handle plan change target selection / confirmation ----
    customer = session.get("customer") or {}
    current_plan = session.get("current_plan")

    selected_plan = (structured_fields or {}).get("selected_plan")
    if selected_plan and selected_plan.get("plan_id"):
        session["plan_change_target"] = selected_plan
        return _respond(
            f"Just to confirm - switch your plan from **{current_plan['name'] if current_plan else 'your current plan'}** "
            f"to **{selected_plan['name']}** ({selected_plan['speed_mbps']} Mbps) at \u20b9{selected_plan['price_inr']}/month? "
            "Reply 'yes' to confirm.",
            "PLAN_CHANGE_CONFIRMATION",
            proposed_plan=selected_plan,
        )

    pending_target = session.get("plan_change_target")
    if pending_target:
        low = message.lower().strip()
        if any(w in low for w in ("yes", "confirm", "sure", "ok", "okay", "yeah", "proceed")):
            updated_customer = apply_plan_change(db, customer.get("customer_id"), pending_target["plan_id"])
            if not updated_customer:
                return _respond("Something went wrong applying that change - please try again.", "PLAN_CHANGE_FAILED")
            session["customer"] = updated_customer
            session["current_plan"] = pending_target
            session["plan_change_target"] = None
            session["plan_change_confirmed"] = True
            return _respond(
                f"Done! You're now on **{pending_target['name']}** ({pending_target['speed_mbps']} Mbps) "
                f"at \u20b9{pending_target['price_inr']}/month. The change has been committed to your account and will reflect on your billing cycle.",
                "PLAN_CHANGE_CONFIRMED",
                current_plan=pending_target,
            )
        elif _is_escape_intent(message):
            session["plan_change_target"] = None
            return _respond("No problem, keeping your current plan. Anything else I can help with?", "PLAN_CHANGE_CANCELLED")
        else:
            return _respond(
                f"Reply 'yes' to confirm switching to **{pending_target['name']}**, or 'no' to keep your current plan.",
                "PLAN_CHANGE_CONFIRMATION",
                proposed_plan=pending_target,
            )

    # ---- Step 3: account inquiry and modification intents ----
    low_msg = message.lower()
    
    # Check if user asks for order or appointment details
    if any(w in low_msg for w in ("my order", "order details", "installation", "appointment", "order status", "when will", "technician")):
        latest_order = customer.get("latest_order")
        if latest_order:
            order_details = latest_order.get("details") or {}
            appt = order_details.get("appointment") or {}
            addr = order_details.get("service_address") or order_details.get("qualified_address") or {}
            ans = (
                f"📋 **Order & Installation Details:**\n\n"
                f"• **Order ID:** {latest_order.get('order_id')}\n"
                f"• **Plan:** {current_plan['name'] if current_plan else latest_order.get('plan_id')} (₹{latest_order.get('amount_inr', 799)}/month)\n"
                f"• **Installation Address:** {addr.get('formatted_address') or addr.get('street_address') or customer.get('existing_pincode')}\n"
                f"• **Scheduled Date:** {appt.get('date', 'Tomorrow')}\n"
                f"• **Time Slot:** {appt.get('time_window', 'Morning')}\n"
                f"• **Payment Status:** {latest_order.get('payment_status', 'Completed').capitalize()}\n\n"
                "Our field engineer will call you before arrival."
            )
            return _respond(ans, "ORDER_DETAILS", latest_order=latest_order)

    # Check if user asks for account details
    if any(w in low_msg for w in ("my details", "account details", "my profile", "my account", "my info")):
        ans = (
            f"👤 **Your Account Profile:**\n\n"
            f"• **Name:** {customer.get('name')}\n"
            f"• **Phone:** {customer.get('phone')}\n"
            f"• **Email:** {customer.get('email') or 'Not provided'}\n"
            f"• **PIN Code:** {customer.get('existing_pincode') or 'On file'}\n"
            f"• **Active Plan:** {current_plan['name'] if current_plan else 'None'} ({current_plan['speed_mbps'] if current_plan else 0} Mbps at ₹{current_plan['price_inr'] if current_plan else 0}/month)\n"
            f"• **Status:** {customer.get('subscription_status', 'ACTIVE')}"
        )
        return _respond(ans, "ACCOUNT_DETAILS")

    # Check if user asks to update email or name
    new_email_match = re.search(r"[\w.+-]+@[\w.-]+\.[A-Za-z]{2,}", message)
    if ("update email" in low_msg or "change email" in low_msg) and new_email_match:
        from app.services.customer_service import update_customer_details
        new_email = new_email_match.group(0)
        updated = update_customer_details(db, customer.get("customer_id"), email=new_email)
        if updated:
            session["customer"] = updated
            return _respond(f"✅ Your email address has been updated to **{new_email}** in your account profile.", "PROFILE_UPDATED")

    # ---- Step 4: general plan change intent detection while verified ----
    intent = _plan_change_intent(message)
    if intent in ("UPGRADE", "DOWNGRADE"):
        options = get_upgrade_downgrade_options(db, current_plan.get("plan_id") if current_plan else None)
        candidates = options["upgrades"] if intent == "UPGRADE" else options["downgrades"]
        if not candidates:
            direction = "an upgrade" if intent == "UPGRADE" else "a downgrade"
            return _respond(f"You're already on our {'top' if intent == 'UPGRADE' else 'entry-level'} plan, so there isn't {direction} available.", "NO_CHANGE_AVAILABLE")
        return _respond(
            f"Here are your {'upgrade' if intent == 'UPGRADE' else 'downgrade'} options:",
            "PLAN_SELECTION",
            catalog_plans=candidates,
        )

    # ---- Fallback: route to RAG for general questions while staying in existing-customer mode ----
    try:
        retrieved_chunks = query_faq_collection(message, top_k=3)
        answer = generate_grounded_faq_answer(message, retrieved_chunks)
    except Exception as exc:
        logger.warning("Existing-customer RAG fallback failed: %s", exc)
        answer = (
            f"I can help with your current plan (**{current_plan['name']}**), upgrades, downgrades, "
            "or general questions about billing and service." if current_plan else
            "I can help with plan questions, upgrades, or general billing/service queries."
        )
    return _respond(answer, "EXISTING_CUSTOMER_FAQ")


@trace
def _handle_message_internal(
    session_id: str,
    message: str,
    db: Session,
    *,
    language: str = "en",
    structured_fields: dict | None = None,
) -> dict:
    """Canonical handler for user chat messages."""
    session = session_store.get(session_id)
    conversation_id = _conversation_id(session)
    current_mode = session.get("mode", "RAG")
    msg_strip = message.strip()
    msg_low = msg_strip.lower()

    # Extract customer info early if present
    cust_info = _extract_customer_info(msg_strip)
    if cust_info.get("name"):
        session["customer_name"] = cust_info["name"]
        if "customer" in session and isinstance(session["customer"], dict):
            session["customer"]["name"] = cust_info["name"]

    # Apply structured field overrides if present
    if structured_fields:
        session.update({k: v for k, v in structured_fields.items() if v is not None})

    # EXISTING CUSTOMER GATE: takes priority over RAG/ORDER_FLOW routing entirely.
    # Previously is_existing_customer was accepted but never actually branched
    # anything - this is what makes "Existing Customer" mode real: phone lookup,
    # current-plan resolution, and upgrade/downgrade as its own flow.
    if session.get("is_existing_customer") or session.get("profile") == "existing":
        return _handle_existing_customer_message(
            session_id=session_id,
            message=msg_strip,
            db=db,
            session=session,
            structured_fields=structured_fields,
            conversation_id=conversation_id,
        )

    # ONE-WAY STATE MACHINE GUARDRAIL:
    # If user asks to reset/change location or start over. A bare "no"/"nope"
    # while a confirmation is pending is a local denial, not a global reset -
    # that's handled by the dedicated confirmation handler below.
    if _is_escape_intent(message) and not session.get("awaiting_address_confirmation"):
        _reset_address_state(session)
        session["mode"] = "RAG"
    elif current_mode == "ORDER_FLOW" or current_mode == "ORDER_COMPLETED":
        session["mode"] = "ORDER_FLOW"
    else:
        # 1. LLM-driven Intent Classifier (Primary route selection)
        try:
            llm_route = classify_conversation_route(message, session)
        except Exception as exc:
            logger.warning("Conversation route classification failed, using safety-net: %s", exc)
            llm_route = None
        if llm_route == "TRANSACTION":
            session["mode"] = "ORDER_FLOW"
            logger.info("LLM State transition: session=%s RAG -> ORDER_FLOW", session_id)
        elif llm_route == "KNOWLEDGE":
            session["mode"] = "RAG"
        elif _is_order_intent_trigger(message) or structured_fields or session.get("pincode") or session.get("requires_full_address"):
            # 2. Safety-net fallback if LLM route is inconclusive or API is offline
            session["mode"] = "ORDER_FLOW"
            logger.info("Safety-net State transition: session=%s RAG -> ORDER_FLOW", session_id)
        else:
            session["mode"] = "RAG"

    active_mode = session["mode"]

    # =========================================================================
    # FLOW 1: RAG FAQ FLOW (When mode is "RAG")
    # =========================================================================
    if active_mode == "RAG":
        try:
            retrieved_chunks = query_faq_collection(message, top_k=3)
        except Exception as exc:
            logger.warning("RAG retrieval failed: %s", exc)
            retrieved_chunks = []
        try:
            answer = generate_grounded_faq_answer(
                message,
                retrieved_chunks,
                conversation_history=session.get("conversation_history"),
            )
        except Exception as exc:
            logger.warning("RAG synthesis failed: %s", exc)
            answer = "I can help with broadband plans, routers, installation, and coverage. Please ask a question, or share a complete street address with PIN code when you want to check serviceability."
        evidence = [{"type": "faq_chunk", "chunk": c} for c in retrieved_chunks]

        session.setdefault("conversation_history", []).extend([
            {"role": "user", "content": message},
            {"role": "assistant", "content": answer},
        ])

        updated_state = state_for_response(state_from_session(session_id, session))
        return {
            "sessionId": session_id,
            "conversationId": conversation_id,
            "mode": "RAG",
            "intent": "FAQ_KNOWLEDGE",
            "workflowState": "RAG_FAQ",
            "response": answer,
            "sources": evidence,
            "canStartNewConnection": True,
            "updatedState": updated_state,
        }

    # =========================================================================
    # FLOW 2: ORDERING WORKFLOW (When mode is "ORDER_FLOW")
    # =========================================================================

    # Priority: If user is mid-recommendation-survey, process answer FIRST
    reco_stage = session.get("recommendation_stage", 0)
    if reco_stage > 0:
        plans = session.get("recommended_plans") or session.get("catalog_plans") or []
        answers = session.get("recommendation_answers", [])
        answers.append(msg_strip)
        session["recommendation_answers"] = answers
        reco_stage += 1
        session["recommendation_stage"] = reco_stage

        rec_plan = None
        if reco_stage == 2:
            answer = "Got it! Second, how many total devices will be connected to the network?"
        elif reco_stage == 3:
            answer = "Understood! Finally, what is your primary purpose for using the network (e.g., 4K streaming, online gaming, working from home, or smart home usage)?"
        else:
            user_query = f"Network Users: {answers[0]}. Connected Devices: {answers[1]}. Primary Purpose: {answers[2]}."
            answer, rec_plan = recommend_plan_conversational(plans, user_query)
            session["recommendation_stage"] = 0
            session["recommendation_answers"] = []

        updated_state = state_for_response(state_from_session(session_id, session))
        return {
            "sessionId": session_id,
            "conversationId": conversation_id,
            "mode": "ORDER_FLOW",
            "intent": "PLAN_RECOMMENDATION",
            "workflowState": "PLAN_SELECTION",
            "response": answer,
            "recommendedPlan": rec_plan,
            "sources": [rec_plan] if rec_plan else plans,
            "canStartNewConnection": True,
            "updatedState": updated_state,
        }

    # Sub-step 1: Check for invalid PIN code input (only when input is a 6-digit number)
    if len(msg_strip) == 6 and msg_strip.isdigit() and _is_invalid_or_dummy_pincode(msg_strip):
        answer = _generate_invalid_pincode_message(msg_strip)
        updated_state = state_for_response(state_from_session(session_id, session))
        return {
            "sessionId": session_id,
            "conversationId": conversation_id,
            "mode": "ORDER_FLOW",
            "intent": "INVALID_PINCODE",
            "workflowState": "ADDRESS_QUALIFICATION",
            "response": answer,
            "sources": [],
            "canStartNewConnection": True,
            "updatedState": updated_state,
        }

    # Sub-step 1.5: Handle Address Confirmation Response
    if session.get("awaiting_address_confirmation"):
        confirm_intent = classify_confirmation_intent(message)
        if confirm_intent == "DENY":
            _reset_address_state(session)
            answer = _generate_escape_reset_message()
            updated_state = state_for_response(state_from_session(session_id, session))
            return {
                "sessionId": session_id,
                "conversationId": conversation_id,
                "mode": "ORDER_FLOW",
                "intent": "PROMPT_STREET_ADDRESS",
                "workflowState": "ADDRESS_QUALIFICATION",
                "response": answer,
                "sources": [],
                "canStartNewConnection": True,
                "updatedState": updated_state,
            }
        elif confirm_intent == "CONFIRM":
            session["awaiting_address_confirmation"] = False
            session["address_confirmed"] = True
            session["awaiting_plan_permission"] = False
            session["plans_shown"] = True
            plans = session.get("recommended_plans") or session.get("catalog_plans") or []
            qual = session.get("qualified_address") or {}
            formatted_addr = qual.get("formatted_address") or session.get("pincode", "")
            state_or_region = qual.get("state") or qual.get("region") or qual.get("city") or "your region"
            answer = _generate_plans_unlocked_message(formatted_addr, state_or_region, len(plans))
            updated_state = state_for_response(state_from_session(session_id, session))
            return {
                "sessionId": session_id,
                "conversationId": conversation_id,
                "mode": "ORDER_FLOW",
                "intent": "PLANS_DISCOVERED",
                "workflowState": "PLAN_SELECTION",
                "response": answer,
                "sources": plans,
                "canStartNewConnection": True,
                "updatedState": updated_state,
            }

    # Sub-step 2: Address Verification & Geocoding via Mapbox with Nominatim fallback
    pincode = _extract_pincode(message) or session.get("pincode")
    street_address = session.get("street_address")

    if not re.fullmatch(r"\d{6}", msg_strip):
        if not re.search(r"\b(?:hi|hello|book|order|select|gaming|work|speed|price|plan)\b", msg_low):
            extracted = extract_street_address_llm(msg_strip, pincode)
            if extracted:
                street_address = extracted
                session["street_address"] = street_address

    # If street address is provided but PIN code is missing
    if street_address and not pincode and not session.get("address_qualified"):
        answer = f"Thank you! We received your street address at '{street_address}'. Please share the 6-digit PIN code for this location so we can check exact serviceability and fetch your regional fiber plans."
        updated_state = state_for_response(state_from_session(session_id, session))
        return {
            "sessionId": session_id,
            "conversationId": conversation_id,
            "mode": "ORDER_FLOW",
            "intent": "PROMPT_PINCODE",
            "workflowState": "ADDRESS_QUALIFICATION",
            "response": answer,
            "sources": [],
            "canStartNewConnection": True,
            "updatedState": updated_state,
        }

    if pincode and not session.get("address_qualified"):
        qualification_result = qualify(db, pincode, street_address)
        session["qualified_address"] = qualification_result
        session["pincode"] = pincode
        session["serviceable"] = qualification_result.get("serviceable", False)

        if not qualification_result.get("serviceable"):
            answer = _generate_unserviceable_message(pincode, qualification_result.get("message"))
            updated_state = state_for_response(state_from_session(session_id, session))
            return {
                "sessionId": session_id,
                "conversationId": conversation_id,
                "mode": "ORDER_FLOW",
                "intent": "UNSERVICEABLE_LOCATION",
                "workflowState": "ADDRESS_QUALIFICATION",
                "response": answer,
                "sources": [],
                "canStartNewConnection": True,
                "updatedState": updated_state,
            }

        if qualification_result.get("requires_full_address") and not qualification_result.get("address_qualified"):
            session["requires_full_address"] = True
            session["address_qualified"] = False
            session["plans_shown"] = False
            session["catalog_plans"] = []
            session["recommended_plans"] = []
            addr_prompt_count = session.get("address_prompt_count", 0) + 1
            session["address_prompt_count"] = addr_prompt_count
            city = qualification_result.get("city")
            state_val = qualification_result.get("state")
            answer = _generate_pincode_only_prompt(pincode, city, state_val)
            updated_state = state_for_response(state_from_session(session_id, session))
            return {
                "sessionId": session_id,
                "conversationId": conversation_id,
                "mode": "ORDER_FLOW",
                "intent": "PROMPT_STREET_ADDRESS",
                "workflowState": "ADDRESS_QUALIFICATION",
                "response": answer,
                "sources": [],
                "canStartNewConnection": True,
                "updatedState": updated_state,
            }

        if qualification_result.get("address_qualified"):
            session["address_qualified"] = True
            session["requires_full_address"] = False
            state_or_region = qualification_result.get("state") or qualification_result.get("region") or qualification_result.get("city")
            plans = recommend(db, qualification_result.get("max_speed_available_mbps", 1000), state_or_region=state_or_region)
            session["recommended_plans"] = plans
            session["catalog_plans"] = plans

            if not session.get("address_confirmed"):
                session["awaiting_address_confirmation"] = True
                session["address_confirmed"] = False
                session["plans_shown"] = False
                formatted_addr = qualification_result.get("formatted_address") or f"{street_address}, {pincode}"
                answer = _generate_address_confirmation_prompt(formatted_addr)
                updated_state = state_for_response(state_from_session(session_id, session))
                return {
                    "sessionId": session_id,
                    "conversationId": conversation_id,
                    "mode": "ORDER_FLOW",
                    "intent": "CONFIRM_ADDRESS_PROMPT",
                    "workflowState": "ADDRESS_CONFIRMATION",
                    "response": answer,
                    "sources": [],
                    "canStartNewConnection": True,
                    "updatedState": updated_state,
                }
            else:
                session["plans_shown"] = True
                plan_count = len(plans)
                answer = f"Your address at {qualification_result.get('formatted_address', pincode)} has been verified! Here are the {plan_count} active high-speed regional fiber plans available for {state_or_region}:"
                updated_state = state_for_response(state_from_session(session_id, session))
                return {
                    "sessionId": session_id,
                    "conversationId": conversation_id,
                    "mode": "ORDER_FLOW",
                    "intent": "PLANS_DISCOVERED",
                    "workflowState": "PLAN_SELECTION",
                    "response": answer,
                    "sources": plans,
                    "canStartNewConnection": True,
                    "updatedState": updated_state,
                }

    # Prompt for complete address if not provided yet in Order Flow
    if not pincode or not session.get("address_qualified"):
        is_order_booking = _is_explicit_order_booking_intent(msg_strip)
        is_plan_search = _is_explicit_plan_search_intent(msg_strip)

        # Check if user message is a general FAQ question (NOT a booking request, NOT a plan dump if user didn't ask for plans)
        if not is_order_booking and not re.search(r"\d{6}", msg_strip) and not clean_street_address(msg_strip, pincode):
            try:
                chunks = query_faq_collection(message, top_k=3)
            except Exception as exc:
                logger.warning("Order-flow FAQ retrieval failed: %s", exc)
                chunks = []
            if chunks:
                try:
                    faq_answer = generate_grounded_faq_answer(message, chunks)
                except Exception as exc:
                    logger.warning("Order-flow FAQ synthesis failed: %s", exc)
                    faq_answer = ""

                # Guardrail: If user did NOT explicitly search for plans, suppress plan dumps from FAQ RAG
                contains_plan_dump = any(term in faq_answer.lower() for term in ["40 mbps", "100 mbps", "200 mbps", "300 mbps", "500 mbps", "1 gbps", "entertainment plan"])
                if not is_plan_search and contains_plan_dump:
                    faq_answer = ""

                if faq_answer:
                    if "whenever you're ready" not in faq_answer.lower() and "whenever you are ready" not in faq_answer.lower():
                        faq_answer = faq_answer.rstrip() + " You can share your complete street address whenever you're ready."
                    answer = faq_answer
                    updated_state = state_for_response(state_from_session(session_id, session))
                    return {
                        "sessionId": session_id,
                        "conversationId": conversation_id,
                        "mode": "ORDER_FLOW",
                        "intent": "FAQ_KNOWLEDGE",
                        "workflowState": "ADDRESS_QUALIFICATION",
                        "response": answer,
                        "sources": [{"type": "faq_chunk", "chunk": c} for c in chunks],
                        "canStartNewConnection": True,
                        "updatedState": updated_state,
                    }

        # For order/booking intent OR when prompting for complete address:
        answer = _generate_prompt_complete_address(pincode=pincode if session.get("requires_full_address") else None, user_message=msg_strip)
        updated_state = state_for_response(state_from_session(session_id, session))
        return {
            "sessionId": session_id,
            "conversationId": conversation_id,
            "mode": "ORDER_FLOW",
            "intent": "PROMPT_LOCATION",
            "workflowState": "ADDRESS_QUALIFICATION",
            "response": answer,
            "sources": [],
            "canStartNewConnection": True,
            "updatedState": updated_state,
        }

    # Sub-step 3: Plan Selection & LLM-Powered Plan Recommendation Assistant (Non-RAG)
    plans = session.get("recommended_plans") or session.get("catalog_plans") or []
    selected_plan = session.get("selected_plan")

    if structured_fields and structured_fields.get("selected_plan"):
        selected_plan = structured_fields["selected_plan"]
        session["selected_plan"] = selected_plan

    # Handle escape intent: user wants to change address or start over
    if not selected_plan and plans and _is_escape_intent(message):
        session["address_qualified"] = False
        session["address_confirmed"] = False
        session["street_address"] = None
        session["plans_shown"] = False
        session["requires_full_address"] = False
        session["pincode"] = None
        session["recommended_plans"] = []
        session["catalog_plans"] = []
        session["qualified_address"] = None
        session["address_prompt_count"] = 0
        session["recommendation_stage"] = 0
        session["recommendation_answers"] = []
        answer = _generate_escape_reset_message()
        updated_state = state_for_response(state_from_session(session_id, session))
        return {
            "sessionId": session_id,
            "conversationId": conversation_id,
            "mode": "ORDER_FLOW",
            "intent": "PROMPT_LOCATION",
            "workflowState": "ADDRESS_QUALIFICATION",
            "response": answer,
            "sources": [],
            "canStartNewConnection": True,
            "updatedState": updated_state,
        }

    if not selected_plan and plans:
        # Check if user message selects a plan by name or ID
        for p in plans:
            p_name = (p.get("name") or "").lower()
            p_id = (p.get("plan_id") or "").lower()
            if p_name in msg_low or p_id in msg_low:
                selected_plan = p
                session["selected_plan"] = selected_plan
                break

    if not selected_plan and plans:
        reco_stage = session.get("recommendation_stage", 0)

        if reco_stage == 1:
            session["reco_users"] = message
            session["recommendation_stage"] = 2
            answer = "Got it! **Question 2 of 3:** How many devices (smartphones, laptops, smart TVs, gaming consoles) will be connected simultaneously?"
            updated_state = state_for_response(state_from_session(session_id, session))
            return {
                "sessionId": session_id,
                "conversationId": conversation_id,
                "mode": "ORDER_FLOW",
                "intent": "PLAN_SELECTION",
                "workflowState": "PLAN_SELECTION",
                "response": answer,
                "sources": plans,
                "canStartNewConnection": True,
                "updatedState": updated_state,
            }

        elif reco_stage == 2:
            session["reco_devices"] = message
            session["recommendation_stage"] = 3
            answer = "Great! **Question 3 of 3:** What is your primary usage requirement? (e.g., 4K Streaming & Gaming, Work From Home, or General Browsing)"
            updated_state = state_for_response(state_from_session(session_id, session))
            return {
                "sessionId": session_id,
                "conversationId": conversation_id,
                "mode": "ORDER_FLOW",
                "intent": "PLAN_SELECTION",
                "workflowState": "PLAN_SELECTION",
                "response": answer,
                "sources": plans,
                "canStartNewConnection": True,
                "updatedState": updated_state,
            }

        elif reco_stage == 3:
            session["reco_purpose"] = message
            session["recommendation_stage"] = 0
            u_text = session.get("reco_users", "")
            d_text = session.get("reco_devices", "")
            p_text = session.get("reco_purpose", "")

            intro, reco_plan = recommend_plan_conversational(
                plans, message, users_text=u_text, devices_text=d_text, purpose_text=p_text
            )
            session["recommended_plan"] = reco_plan

            answer = f"{intro}\n\nWe recommend **{reco_plan.get('name')}** ({reco_plan.get('speed_mbps')} Mbps speed at ₹{reco_plan.get('price_inr')}/month), perfect for {u_text} users and {d_text} devices."

            updated_state = state_for_response(state_from_session(session_id, session))
            return {
                "sessionId": session_id,
                "conversationId": conversation_id,
                "mode": "ORDER_FLOW",
                "intent": "PLAN_RECOMMENDED",
                "workflowState": "PLAN_SELECTION",
                "response": answer,
                "sources": plans,
                "recommended_plan": reco_plan,
                "canStartNewConnection": True,
                "updatedState": updated_state,
            }

        reco_intent = classify_plan_selection_intent(message)
        if reco_intent == "RECOMMENDATION_REQUEST":
            session["recommendation_stage"] = 1
            answer = "I would be happy to recommend the perfect plan for you! Let's answer 3 quick questions.\n\n**Question 1 of 3:** How many people will be using this connection?"
        else:
            try:
                chunks = query_faq_collection(message, top_k=3)
                answer = generate_grounded_faq_answer(message, chunks)
            except Exception as exc:
                logger.warning("Plan-selection FAQ synthesis failed: %s", exc)
                answer = "Please tell me which plan you want, or ask me to recommend one."

        updated_state = state_for_response(state_from_session(session_id, session))
        return {
            "sessionId": session_id,
            "conversationId": conversation_id,
            "mode": "ORDER_FLOW",
            "intent": "PLAN_SELECTION",
            "workflowState": "PLAN_SELECTION",
            "response": answer,
            "sources": plans,
            "canStartNewConnection": True,
            "updatedState": updated_state,
        }

    # Sub-step 4: Customer Details Capture
    customer = session.get("customer") or {}
    if session.get("customer_name") and not customer.get("name"):
        customer["name"] = session["customer_name"]
    extracted = _extract_customer_info(message)
    for k, v in extracted.items():
        if v and not customer.get(k):
            customer[k] = v

    if extracted.get("name") or extracted.get("email") or extracted.get("phone"):
        session["customer"] = customer

    missing_customer_fields = [f for f in ("name", "phone", "email") if not customer.get(f)]
    if missing_customer_fields:
        missing_str = ", ".join(f.capitalize() for f in missing_customer_fields)
        answer = f"You selected the **{selected_plan.get('name')}** plan (₹{selected_plan.get('price_inr')}/month). Please provide your {missing_str} to set up your account."
        updated_state = state_for_response(state_from_session(session_id, session))
        return {
            "sessionId": session_id,
            "conversationId": conversation_id,
            "mode": "ORDER_FLOW",
            "intent": "CAPTURE_CUSTOMER_DETAILS",
            "workflowState": "CUSTOMER_DETAILS",
            "response": answer,
            "sources": [],
            "canStartNewConnection": True,
            "updatedState": updated_state,
        }

    # Save validated customer profile
    try:
        validated_customer = find_or_validate(db, **customer)
        session["customer"] = validated_customer
    except Exception as exc:
        logger.warning("Customer validation warning: %s", exc)

    # Sub-step 5: Installation Appointment Selection
    appointment = session.get("appointment")
    slot_match = re.search(r"SLOT-[A-Z0-9:-]+", message.upper())
    fdh_id = (session.get("qualified_address") or {}).get("fdh_id") or "FDH-CHENNAI-01"

    if slot_match and not appointment:
        try:
            appointment = select_slot(db, slot_match.group(0), fdh_id)
            session["appointment"] = appointment
        except Exception as exc:
            logger.warning("Slot selection failed: %s", exc)

    if not appointment:
        slots = available_slots(db, fdh_id)
        answer = f"Thank you, {customer.get('name')}! Contact details saved. Please choose an installation appointment slot from the options below:"
        updated_state = state_for_response(state_from_session(session_id, session))
        return {
            "sessionId": session_id,
            "conversationId": conversation_id,
            "mode": "ORDER_FLOW",
            "intent": "SELECT_APPOINTMENT",
            "workflowState": "APPOINTMENT",
            "response": answer,
            "sources": slots,
            "canStartNewConnection": True,
            "updatedState": updated_state,
        }

    # Sub-step 6: Payment Confirmation & Order Creation
    payment = session.get("payment")
    if not payment:
        payment = create_purl(session_id, selected_plan.get("price_inr", 799))
        payment = confirm_payment(payment, "TXN-AUTO-CONFIRM")
        session["payment"] = payment
        session["payment_status"] = payment.get("status")

    if not session.get("order_id"):
        order_data = create_order(db, session_id, session)
        session["order_id"] = order_data.get("order_id")
        session["mode"] = "ORDER_COMPLETED"
        session["workflow_state"] = "COMPLETED"

        order_id = order_data.get("order_id")
        inst_date = (appointment or {}).get("date", "Tomorrow")
        inst_slot = (appointment or {}).get("time_window", "Morning")

        answer = (
            f"🎉 **Booking Confirmed!**\n\n"
            f"Congratulations {customer.get('name')}! Your order **{order_id}** has been confirmed successfully.\n\n"
            f"**Plan Details:**\n"
            f"• Plan: {selected_plan.get('name')} ({selected_plan.get('speed_mbps')} Mbps)\n"
            f"• Price: ₹{selected_plan.get('price_inr')}/month\n\n"
            f"**Customer Details:**\n"
            f"• Name: {customer.get('name')}\n"
            f"• Contact: {customer.get('phone')} | {customer.get('email')}\n\n"
            f"**Installation Details:**\n"
            f"• Date: {inst_date}\n"
            f"• Time: {inst_slot}\n\n"
            "Our technician will contact you prior to arrival."
        )
    else:
        answer = f"Your order **{session.get('order_id')}** is active and confirmed! If you have any further questions, feel free to reach out."

    updated_state = state_for_response(state_from_session(session_id, session))
    return {
        "sessionId": session_id,
        "conversationId": conversation_id,
        "mode": session["mode"],
        "intent": "ORDER_CONFIRMED",
        "workflowState": session.get("workflow_state", "COMPLETED"),
        "response": answer,
        "sources": [],
        "canStartNewConnection": True,
        "updatedState": updated_state,
    }

