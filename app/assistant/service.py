"""Modular assistant orchestration service for Data Shopper platform.

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
from app.rag.chroma_rag import (
    query_faq_collection,
    generate_grounded_faq_answer,
    query_existing_customer_collection,
    generate_grounded_existing_customer_answer,
)
from app.services.address_service import qualify, _is_invalid_or_dummy_pincode, clean_street_address, extract_street_address_llm
from app.services.appointment_service import available_slots, select_slot
from app.services.customer_service import (
    find_or_validate,
    find_customer_by_phone,
    get_upgrade_downgrade_options,
    get_customer_region,
    apply_plan_change,
    normalize_phone,
    update_customer_details,
)
from app.services.order_service import create_order
from app.services.payment_service import create_purl, confirm_payment
from app.services.plan_service import recommend
from app.services.welcome_service import generate_dynamic_greeting, generate_contextual_followups
from app.utils.trace import trace, trace_async

logger = logging.getLogger(__name__)

EXISTING_MENU_CHIPS = ["Upgrade", "Downgrade", "Edit Customer Data", "Other Queries"]


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
    return "Thank you for choosing Data Shopper! To get started with your new connection, please share your complete street address (house/flat number, street name, locality, and 6-digit pincode) so we can verify exact serviceability."


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
    source: str = "DATA_SHOPPER",
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
    # Existing Customer: first turn is LLM-only phone collection. No RAG chips.
    followups = [] if is_existing else generate_contextual_followups(
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
    """Extract a 6-digit Indian PIN code from text, allowing optional spaces."""
    # Matches '500084', '500 084', etc.
    match = re.search(r"\b([1-9][0-9]{2}\s?[0-9]{3})\b", text)
    if match:
        return match.group(1).replace(" ", "")
    return None


@trace
def _is_escape_intent(text: str) -> bool:
    """Detect if user wants to reset, change address, or leave the current sub-flow."""
    low = text.lower().strip()
    words = set(re.findall(r"\b\w+\b", low))
    if "no" in words or "nope" in words:
        # Prevent false positives for "flat no", "house no", "plot no", "shop no", "door no"
        if re.search(r"\b(?:flat|house|plot|shop|door|room|street|road|ward)\s+no\b", low):
            pass # It's part of an address, not an escape intent
        elif len(words) <= 3:
            return True
        elif not any(w in words for w in {"flat", "house", "plot", "shop", "door", "room", "street", "road", "ward", "pincode", "pin"}):
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
        "choose the right plan", "help me choose", "cricket plan", "cricket", "gym plan", "gym", "workout"
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
def _extract_name(text: str) -> str | None:
    """Extract person's actual name from text, handling multi-intent sentences, corrections, and structured formats."""
    if not text:
        return None

    # 1. Structured format: 'Name: John Doe' or 'name - John Doe'
    struct_match = re.search(r'^\s*name\s*[:\-]\s*([A-Za-z\s]{2,40})', text, re.I | re.M)
    if struct_match:
        cand = struct_match.group(1).split('\n')[0].strip(' .,!')
        if cand and len(cand) >= 2:
            return ' '.join(cand.split())

    stop_words = {
        'how', 'are', 'you', 'and', 'what', 'is', 'why', 'when', 'where', 'which',
        'who', 'whom', 'can', 'could', 'would', 'will', 'should', 'i', 'im', 'i am',
        'asking', 'want', 'need', 'looking', 'tell', 'show', 'give', 'help', 'please',
        'thanks', 'thank', 'not', 'no', 'yes', 'fine', 'good', 'great', 'here',
        'today', 'now', 'sir', 'madam', 'bro', 'buddy', 'signal', 'selector', 'broadband',
        'fiber', 'fibre', 'plan', 'plans', 'wifi', 'internet', 'connection', 'speed', 'price'
    }

    pos_matches = []
    for m in re.finditer(r'(?:^|[.,!?\s])(?:my\s+name\s+is|name\s+is|call\s+me|\bi\s+am|\bi\'m)\s+(?:(not|isn\'t)\s+)?([A-Za-z]+(?:\s+[A-Za-z]+){0,2})', text, re.I):
        if m.group(1):  # negation 'not' or 'isn't'
            continue
        raw_val = m.group(2).strip()
        tokens = []
        for word in raw_val.split():
            if word.lower() in stop_words:
                break
            tokens.append(word.capitalize())
        if tokens:
            pos_matches.append(' '.join(tokens))

    if pos_matches:
        return pos_matches[-1]
    return None


@trace
def _extract_customer_info(text: str) -> dict:
    """Extract Name, Phone, and Email from message."""
    email_match = re.search(r"[\w.+-]+@[\w.-]+\.[A-Za-z]{2,}", text)
    phone_match = re.search(r"(?<!\d)(?:\+91[- ]?)?([6-9]\d{9})(?!\d)", text)
    name = _extract_name(text)

    return {
        "name": name,
        "phone": phone_match.group(1) if phone_match else None,
        "email": email_match.group(0) if email_match else None,
    }


# ── Language Switch Detection ──────────────────────────────────────────
# Maps natural language names (in English, Hindi, Telugu, Tamil, etc.) to
# ISO language codes.  Covers the most common ways a user might request a
# switch, including transliterated Indic variants.

_LANG_NAME_TO_CODE: dict[str, str] = {
    # English names
    "english": "en", "hindi": "hi", "telugu": "te", "tamil": "ta",
    "bengali": "bn", "bangla": "bn", "marathi": "mr", "gujarati": "gu",
    "kannada": "kn", "malayalam": "ml", "punjabi": "pa", "odia": "or",
    "oriya": "or", "assamese": "as", "urdu": "ur", "nepali": "ne",
    "sanskrit": "sa", "sindhi": "sd", "kashmiri": "ks", "dogri": "doi",
    "konkani": "kok", "maithili": "mai", "santali": "sat", "manipuri": "mni",
    "bodo": "brx",
    # Hindi transliterations
    "angrezi": "en", "angreji": "en", "hindi": "hi",
    # Telugu transliterations
    "telugulo": "te", "telugu lo": "te",
    # Tamil transliterations
    "tamilil": "ta", "tamil la": "ta",
}

_LANG_CODE_TO_NAME: dict[str, str] = {
    "en": "English", "hi": "Hindi", "te": "Telugu", "ta": "Tamil",
    "bn": "Bengali", "mr": "Marathi", "gu": "Gujarati", "kn": "Kannada",
    "ml": "Malayalam", "pa": "Punjabi", "or": "Odia", "as": "Assamese",
    "ur": "Urdu", "ne": "Nepali", "sa": "Sanskrit", "sd": "Sindhi",
    "ks": "Kashmiri", "doi": "Dogri", "kok": "Konkani", "mai": "Maithili",
    "sat": "Santali", "mni": "Manipuri", "brx": "Bodo",
}


@trace
def _detect_language_switch(message: str) -> tuple[bool, str | None, str | None]:
    """Detect if the user is requesting a language switch.

    Catches phrases like:
      - "speak telugu", "speak in hindi", "can you speak tamil"
      - "switch to hindi", "respond in telugu", "talk in tamil"
      - "use hindi", "reply in telugu", "answer in tamil"
      - "telugu lo cheppu", "hindi mein baat karo"
      - "speak english", "go back to english"

    Returns (detected, language_code, language_name).
    """
    if not message or len(message.strip()) < 3:
        return False, None, None

    low = message.lower().strip()
    # Remove punctuation for matching
    low_clean = re.sub(r"[^a-z0-9\s]", "", low).strip()

    # Pattern 1: "speak <language>", "speak in <language>", "talk in <language>",
    #            "switch to <language>", "respond in <language>", "reply in <language>",
    #            "use <language>", "answer in <language>", "converse in <language>",
    #            "continue in <language>"
    switch_patterns = [
        r"(?:can you |could you |please )?(?:speak|talk|converse|chat|communicate|respond|reply|answer|continue|switch)(?: to| in)? (\w+)",
        r"(?:use|change to|switch to|go back to) (\w+)",
        r"(\w+) (?:lo |mein |la |l |me |madhye |alli |il |tay )(?:cheppu|baat karo|matlaadu|paesu|bolo|bol|sanga|talk|speak|reply)",
        r"(?:in |)(\w+) (?:please|pls)",
    ]

    for pattern in switch_patterns:
        match = re.search(pattern, low_clean)
        if match:
            lang_word = match.group(1).strip()
            if lang_word in _LANG_NAME_TO_CODE:
                code = _LANG_NAME_TO_CODE[lang_word]
                name = _LANG_CODE_TO_NAME.get(code, lang_word.capitalize())
                return True, code, name

    # Pattern 2: Check if the entire message is just a language name (e.g. user typed "telugu")
    # Only match if the message is very short (1-2 words) to avoid false positives
    words = low_clean.split()
    if len(words) <= 2:
        for word in words:
            if word in _LANG_NAME_TO_CODE and word not in {"or", "as", "is", "in", "to"}:
                # Avoid matching common English words that happen to be language codes
                code = _LANG_NAME_TO_CODE[word]
                name = _LANG_CODE_TO_NAME.get(code, word.capitalize())
                return True, code, name

    return False, None, None


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

    # ── Language Switch Interception ──────────────────────────────────
    # Detect and handle language switch requests ("speak telugu", "switch
    # to hindi", etc.) BEFORE normal message routing.  This preserves the
    # entire workflow state — only session["language"] changes.
    lang_detected, lang_code, lang_name = _detect_language_switch(message)
    if lang_detected and lang_code:
        # Only act if it's actually a different language
        if lang_code != resolved_language:
            session["language"] = lang_code
            set_current_language(lang_code)

            # Generate acknowledgment in the new language
            conversation_id = _conversation_id(session)
            workflow_state = session.get("workflow_state", "RAG_FAQ")
            last_response = ""
            history = session.get("conversation_history", [])
            if history:
                for entry in reversed(history):
                    if entry.get("role") == "assistant" and entry.get("content"):
                        last_response = entry["content"][:200]
                        break

            try:
                ack_prompt = get_prompt(
                    "service.language_switch_ack",
                    target_language=lang_name,
                    workflow_state=workflow_state,
                    last_response=last_response or "(conversation just started)",
                )
                ack_text = generate(ack_prompt, temperature=0.7, timeout=5, max_tokens=60)
                if not ack_text or len(ack_text.strip()) < 5:
                    raise ValueError("Empty LLM response")
                ack_text = ack_text.strip()
            except Exception as exc:
                logger.warning("Language switch ack LLM failed: %s", exc)
                # Hardcoded fallbacks per language
                fallbacks = {
                    "hi": "Sure! I can understand Hindi now, but I will reply in English.",
                    "te": "Sure! I can understand Telugu now, but I will reply in English.",
                    "ta": "Sure! I can understand Tamil now, but I will reply in English.",
                    "en": "Sure! I'll continue in English from now on. How can I help you?",
                    "bn": "Sure! I can understand Bengali now, but I will reply in English.",
                    "mr": "Sure! I can understand Marathi now, but I will reply in English.",
                    "kn": "Sure! I can understand Kannada now, but I will reply in English.",
                    "ml": "Sure! I can understand Malayalam now, but I will reply in English.",
                    "gu": "Sure! I can understand Gujarati now, but I will reply in English.",
                }
                ack_text = fallbacks.get(lang_code, f"Sure! I can understand {lang_name} now, but I will reply in English.")

            # Record in conversation history
            session.setdefault("conversation_history", []).extend([
                {"role": "user", "content": message},
                {"role": "assistant", "content": ack_text},
            ])

            updated_state = state_for_response(state_from_session(session_id, session))
            return {
                "sessionId": session_id,
                "conversationId": conversation_id,
                "mode": session.get("mode", "RAG"),
                "intent": "LANGUAGE_SWITCH",
                "workflowState": workflow_state,
                "response": ack_text,
                "sources": [],
                "canStartNewConnection": True,
                "updatedState": updated_state,
                "recommended_followups": [],
                "recommendedFollowups": [],
            }
        # Same language requested — just continue normally

    res = _handle_message_internal(
        session_id=session_id,
        message=message,
        db=db,
        language=language,
        structured_fields=structured_fields,
    )
    profile = session.get("profile", "general")
    ans = res.get("response", "")

    if session.get("is_existing_customer") or session.get("profile") == "existing":
        followups = res.get("recommended_followups") or res.get("recommendedFollowups") or []
    else:
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


def _plan_change_intent_keyword_fallback(text: str) -> str | None:
    """Regex/keyword fallback used only when the LLM classifier is unavailable.

    Kept intentionally narrow - real classification happens in
    `_plan_change_intent` via `existing.plan_change_intent`. This fallback
    exists purely so the flow degrades gracefully, not for keyword-triggered
    plan cards.
    """
    low = (text or "").lower().strip()
    if low in {"upgrade plan", "upgrade"} or any(
        w in low for w in ("upgrade", "higher speed", "faster plan", "faster internet", "increase my plan", "boost my plan", "more speed")
    ):
        if "downgrade" not in low:
            return "UPGRADE"
    if low in {"downgrade plan", "downgrade"} or any(
        w in low for w in ("downgrade", "lower speed", "cheaper plan", "reduce my plan", "save money", "lower my bill")
    ):
        return "DOWNGRADE"
    return None


@trace
def _plan_change_intent(text: str, current_plan: dict | None = None) -> str | None:
    """Classify a verified existing customer's message as UPGRADE, DOWNGRADE, or None
    using the LLM (semantic intent), falling back to a narrow keyword heuristic only
    if the LLM call fails. This intentionally avoids triggering plan cards purely
    because an upgrade/downgrade-sounding word appears in an unrelated sentence
    (e.g. "do I need to upgrade my router firmware")."""
    prompt = get_prompt(
        "existing.plan_change_intent",
        message=text or "",
        current_plan_name=(current_plan or {}).get("name") or "unknown",
        current_plan_speed=(current_plan or {}).get("speed_mbps") or "unknown",
        current_plan_price=f"\u20b9{(current_plan or {}).get('price_inr')}/month" if current_plan and current_plan.get("price_inr") else "unknown",
    )
    try:
        data = generate_json(prompt, system=get_prompt("existing.plan_change_intent.system"), timeout=5)
        if data and data.get("intent") in {"UPGRADE", "DOWNGRADE", "NONE"}:
            intent = str(data.get("intent"))
            return intent if intent != "NONE" else None
    except Exception as exc:
        logger.warning("Existing-customer plan-change intent classification error: %s", exc)

    return _plan_change_intent_keyword_fallback(text)


def _normalize_action_label(text: str) -> str:
    return re.sub(r"[^a-z0-9]+", " ", (text or "").lower()).strip()


def _is_existing_menu_chip(text: str, *labels: str) -> bool:
    norm = _normalize_action_label(text)
    return bool(norm) and norm in {_normalize_action_label(label) for label in labels}


@trace
def _is_existing_query_relevant(text: str) -> bool:
    """Guardrail classifier: is this verified customer's message inside the
    existing-customer support domain (add-ons, billing, troubleshooting,
    support, account/order, plan change) or unrelated (gym, furniture, pillow,
    etc.)? Defaults to RELEVANT (fail-open) on classifier failure so the RAG
    path stays available if the LLM is briefly unavailable."""
    prompt = get_prompt("existing.query_relevance", message=text or "")
    try:
        data = generate_json(prompt, system=get_prompt("existing.query_relevance.system"), timeout=5)
        if data and data.get("relevance") in {"RELEVANT", "UNRELATED"}:
            return data.get("relevance") == "RELEVANT"
    except Exception as exc:
        logger.warning("Existing-customer query relevance classification error: %s", exc)

    low = (text or "").lower().strip()
    off_topic_words = (
        "gym", "workout", "fitness", "furniture", "sofa", "pillow", "mattress",
        "recipe", "cooking", "diet", "weather", "movie", "cricket score",
        "homework", "math problem", "car insurance", "flight ticket",
    )
    if any(w in low for w in off_topic_words):
        return False
    return True


@trace
def _generate_existing_followups(session: dict, message: str, answer: str) -> list[str]:
    """Generate 2-3 contextual, in-domain suggestions grounded in recent chat and
    the existing customer FAQ knowledge base. This keeps suggestions aligned with
    what the verified customer flow can actually answer without introducing any
    static chip list or General flow behavior.
    """
    current_plan = session.get("current_plan") or {}
    plan_summary = (
        f"{current_plan.get('name')} ({current_plan.get('speed_mbps')} Mbps, \u20b9{current_plan.get('price_inr')}/month)"
        if current_plan else "No active plan on file"
    )
    shown = session.get("shown_existing_suggestions", [])

    recent_history = session.get("conversation_history") or []
    recent_context = "\n".join(
        f"{t.get('role', 'user')}: {t.get('content', '')}"
        for t in recent_history[-6:]
        if isinstance(t, dict) and (t.get("content") or "").strip()
    )
    recent_context = recent_context or "No recent conversation yet."

    rag_query = message or answer or ""
    if _is_existing_menu_chip(message, "Other Queries", "Something else"):
        rag_query = "add-on billing invoice troubleshooting technician support relocation mesh wifi slow speed"
    relevant_chunks = query_existing_customer_collection(rag_query, top_k=3)
    rag_context = "\n---\n".join(relevant_chunks) if relevant_chunks else "No relevant existing-customer FAQ passage matched this context."

    prompt = get_prompt(
        "existing.followup_suggestions",
        message=(message or "").strip() or "(none)",
        answer=(answer or "").strip() or "(none)",
        current_plan_summary=plan_summary,
        recent_context=recent_context,
        retrieved_context=rag_context,
        previous_suggestions=", ".join(f"'{s}'" for s in shown) if shown else "None",
    )
    try:
        data = generate_json(prompt, system=get_prompt("existing.followup_suggestions.system"), timeout=5)
        if data and isinstance(data.get("suggestions"), list):
            raw = [str(s).strip() for s in data["suggestions"] if s and len(str(s).strip()) > 1]
            normalized: list[str] = []
            for s in raw:
                if s.lower() in {p.lower() for p in shown}:
                    continue
                if len(s) < 6:
                    continue
                if not re.search(
                    r"\b(can|could|what|when|where|why|how|show|check|help|tell|need|want|is|do|does|upgrade|downgrade|add|bill|invoice|troubleshoot|support|wifi|slow|mesh|addon|add-on|problem|issue)\b",
                    s.lower(),
                ):
                    continue
                normalized.append(s)
            picked = normalized[:3]
            if picked:
                session["shown_existing_suggestions"] = (shown + [s for s in picked if s not in shown])[-30:]
                return picked
    except Exception as exc:
        logger.warning("Existing-customer follow-up suggestion generation error: %s", exc)

    # Keep suggestions useful during a temporary model outage by deriving them
    # from retrieved knowledge-base sections rather than a static menu.
    fallback_questions = []
    shown_lower = {item.lower() for item in shown}
    for chunk in relevant_chunks:
        heading = re.search(r"^##\s+(.+)$", chunk, flags=re.MULTILINE)
        if not heading:
            continue
        topic = heading.group(1).splitlines()[0].strip().rstrip(".")
        topic_words = re.findall(r"[A-Za-z]+", topic.lower())
        topic_words = [word for word in topic_words if word not in {"and", "the", "for"}]
        topic_words = topic_words[:3]
        if not topic_words:
            continue
        question = f"Help with {' '.join(topic_words)}?"
        if question.lower() not in shown_lower:
            fallback_questions.append(question)
    picked = fallback_questions[:3]
    if picked:
        session["shown_existing_suggestions"] = (shown + picked)[-30:]
    return picked


@trace
def _existing_llm_reply(prompt_key: str, fallback: str = "", **kwargs) -> str:
    prompt = get_prompt(prompt_key, **kwargs)
    for temperature in (0.7, 0.95, 1.0):
        try:
            text = generate(prompt, temperature=temperature, timeout=6, max_tokens=90)
            if text and len(text.strip()) > 8:
                return text.strip()
        except Exception as exc:
            logger.warning("Existing-customer LLM prompt %s failed: %s", prompt_key, exc)
    return (fallback or "").strip()


@trace
def _format_existing_account_summary(customer: dict, current_plan: dict | None) -> str:
    """Existing UI account/plan details block (unchanged layout)."""
    order_info_lines = []
    latest_order = customer.get("latest_order") or {}
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
        greeting = f"Welcome back, {customer.get('name')}! I found your account registered with {customer.get('phone')}."
        if order_info_text:
            greeting += f"\n\n**Account & Order Summary:**{order_info_text}"
        return greeting

    greeting = (
        f"**Your Account Summary:**\n"
        f"• **Registered Phone:** {customer.get('phone')}\n"
        f"• **Email:** {customer.get('email') or 'Not provided'}\n"
        f"• **Active Plan:** {current_plan['name']} ({current_plan['speed_mbps']} Mbps) at ₹{current_plan['price_inr']}/month"
    )
    if order_info_text:
        greeting += order_info_text
    return greeting


@trace
def _existing_pre_verify_history(session: dict) -> str:
    history = session.get("conversation_history") or []
    recent = history[-6:]
    lines = []
    for t in recent:
        role = "Customer" if t.get("role") == "user" else "Assistant"
        content = (t.get("content") or "").strip()
        if content:
            lines.append(f"{role}: {content}")
    return "\n".join(lines) if lines else "(none)"


@trace
def _verified_existing_rag_answer(message: str, session: dict) -> str:
    try:
        retrieved_chunks = query_existing_customer_collection(message, top_k=2)
        return generate_grounded_existing_customer_answer(
            message,
            retrieved_chunks,
            conversation_history=session.get("conversation_history"),
        )
    except Exception as exc:
        logger.warning("Existing-customer RAG failed: %s", exc)
        return _existing_llm_reply("existing.rag_retry", "", user_query=message or "")


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

    # Workflow states where we deliberately show no suggestion chips because the
    # UI already presents a specific structured input (plan cards, a yes/no
    # confirmation, the profile editor, or the initial phone-verification prompt).
    _NO_SUGGESTION_STATES = {
        "AWAITING_PHONE_VERIFICATION",
        "PHONE_NOT_FOUND",
        "PLAN_SELECTION",
        "PLAN_CHANGE_CONFIRMATION",
        "EDIT_CUSTOMER_DATA",
    }
    _DYNAMIC_FAQ_STATES = {"OTHER_QUERIES"}

    def _respond(answer: str, workflow_state: str, **extra) -> dict:
        followups = extra.pop("recommended_followups", extra.pop("recommendedFollowups", None))
        if followups is None:
            if workflow_state in _NO_SUGGESTION_STATES:
                followups = []
            elif workflow_state in _DYNAMIC_FAQ_STATES:
                followups = _generate_existing_followups(session, message, answer)
            elif session.get("existing_customer_verified"):
                followups = list(EXISTING_MENU_CHIPS)
            else:
                followups = []
        session.setdefault("conversation_history", []).extend([
            {"role": "user", "content": message},
            {"role": "assistant", "content": answer},
        ])
        session["workflow_state"] = workflow_state
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
            "recommended_followups": followups,
            "recommendedFollowups": followups,
            **extra,
        }

    # ---- Step 1: not yet verified — LLM only, no customer RAG ----
    if not session.get("existing_customer_verified"):
        phone_candidate = (
            (structured_fields or {}).get("phone")
            or _extract_phone(message)
        )

        if not phone_candidate:
            answer = _existing_llm_reply(
                "existing.pre_verify",
                "Please share your registered 10-digit mobile number so I can verify your Data Shopper connection.",
                history=_existing_pre_verify_history(session),
                message=message or "",
            )
            return _respond(answer, "AWAITING_PHONE_VERIFICATION")

        normalized = normalize_phone(phone_candidate)
        if len(normalized) != 10:
            answer = _existing_llm_reply(
                "existing.pre_verify",
                "That number doesn't look like a valid 10-digit registered mobile. Please check and share it again.",
                history=_existing_pre_verify_history(session),
                message=message or "",
            )
            return _respond(answer, "AWAITING_PHONE_VERIFICATION")

        customer = find_customer_by_phone(db, normalized)
        if not customer:
            answer = _existing_llm_reply(
                "existing.phone_not_found",
                "I couldn't find a connection on that number. Please re-check your registered 10-digit mobile and share it again.",
                phone=normalized,
                message=message or "",
            )
            return _respond(answer, "PHONE_NOT_FOUND")

        session["existing_customer_verified"] = True
        session["customer"] = customer
        session["customer_region"] = get_customer_region(customer)
        session["catalog_plans"] = []
        session["plans_shown"] = False

        options = get_upgrade_downgrade_options(
            db, customer.get("current_plan_id"), region=session["customer_region"]
        )
        current_plan = options["current"]
        session["current_plan"] = current_plan

        customer_name = (customer.get("name") or "there").strip() or "there"
        confirm = _existing_llm_reply(
            "existing.verified_ok",
            f"Great news, {customer_name}! I found your connection details.",
            name=customer_name,
        )
        details = _format_existing_account_summary(customer, current_plan)
        answer = f"{confirm}\n\n{details}"
        return _respond(
            answer,
            "PLAN_OVERVIEW" if current_plan else "NO_ACTIVE_PLAN",
            current_plan=current_plan,
            recommended_followups=list(EXISTING_MENU_CHIPS),
        )

    # ---- Step 2: verified - handle plan change target selection / confirmation ----
    customer = session.get("customer") or {}
    current_plan = session.get("current_plan")

    incoming_profile = (structured_fields or {}).get("customer") or {}
    if incoming_profile and (
        session.get("workflow_state") == "EDIT_CUSTOMER_DATA"
        or (structured_fields or {}).get("action") == "UPDATE_CUSTOMER_PROFILE"
    ):
        updated = update_customer_details(
            db,
            customer.get("customer_id"),
            name=incoming_profile.get("name"),
            email=incoming_profile.get("email"),
            phone=incoming_profile.get("phone"),
        )
        if updated:
            session["customer"] = updated
            session["existing_faq_mode"] = False
            first_name = (updated.get("name") or "there").split()[0]
            confirm = _existing_llm_reply("existing.verified_ok", "", name=first_name)
            summary = _format_existing_account_summary(updated, current_plan)
            return _respond(
                f"{confirm}\n\n{summary}" if confirm else summary,
                "PROFILE_UPDATED",
                current_plan=current_plan,
                customer=updated,
                recommended_followups=list(EXISTING_MENU_CHIPS),
            )
        return _respond(
            _existing_llm_reply(
                "existing.edit_customer",
                "",
                name=customer.get("name") or "there",
                phone=customer.get("phone") or "",
                email=customer.get("email") or "not on file",
            ),
            "EDIT_CUSTOMER_DATA",
            show_customer_editor=True,
            customer=customer,
            recommended_followups=[],
        )

    selected_plan = (structured_fields or {}).get("selected_plan")
    if selected_plan and selected_plan.get("plan_id"):
        if current_plan and selected_plan.get("plan_id") == current_plan.get("plan_id"):
            return _respond(
                "That's your current plan. Choose a different speed if you want to change it.",
                "PLAN_SELECTION",
                current_plan=current_plan,
            )
        session["plan_change_target"] = selected_plan
        return _respond(
            f"Just to confirm - switch your plan from **{current_plan['name'] if current_plan else 'your current plan'}** "
            f"to **{selected_plan['name']}** ({selected_plan['speed_mbps']} Mbps) at \u20b9{selected_plan['price_inr']}/month? "
            "Reply 'yes' to confirm.",
            "PLAN_CHANGE_CONFIRMATION",
            proposed_plan=selected_plan,
            current_plan=current_plan,
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
            session["catalog_plans"] = []
            return _respond(
                f"Done! You're now on **{pending_target['name']}** ({pending_target['speed_mbps']} Mbps) "
                f"at \u20b9{pending_target['price_inr']}/month. The change has been committed to your account and will reflect on your billing cycle.",
                "PLAN_CHANGE_CONFIRMED",
                current_plan=pending_target,
            )
        elif _is_escape_intent(message):
            session["plan_change_target"] = None
            return _respond(
                "No problem, keeping your current plan. Anything else I can help with?",
                "PLAN_CHANGE_CANCELLED",
            )
        else:
            return _respond(
                f"Reply 'yes' to confirm switching to **{pending_target['name']}**, or 'no' to keep your current plan.",
                "PLAN_CHANGE_CONFIRMATION",
                proposed_plan=pending_target,
            )

    # ---- Step 3: post-verify menu chips and account intents ----
    low_msg = message.lower().strip()

    if _is_existing_menu_chip(message, "Edit Customer Data", "Edit Customer Details"):
        session["existing_faq_mode"] = False
        answer = _existing_llm_reply(
            "existing.edit_customer",
            "",
            name=customer.get("name") or "there",
            phone=customer.get("phone") or "",
            email=customer.get("email") or "not on file",
        )
        return _respond(
            answer,
            "EDIT_CUSTOMER_DATA",
            show_customer_editor=True,
            customer=customer,
            recommended_followups=[],
        )

    if _is_existing_menu_chip(message, "Other Queries", "Something else"):
        session["existing_faq_mode"] = True
        plan_summary = (
            f"{current_plan.get('name')} ({current_plan.get('speed_mbps')} Mbps)"
            if current_plan else "no active plan on file"
        )
        relevant_chunks = query_existing_customer_collection(
            "add-on billing invoice troubleshooting technician support relocation mesh wifi slow speed",
            top_k=3,
        )
        rag_context = "\n---\n".join(relevant_chunks) if relevant_chunks else "No matching support passage was retrieved."
        answer = _existing_llm_reply(
            "existing.other_queries",
            "",
            name=customer.get("name") or "there",
            current_plan_summary=plan_summary,
            retrieved_context=rag_context,
        )
        if not answer:
            answer = _verified_existing_rag_answer(
                "Invite the verified customer to describe their broadband connection or account issue.",
                session,
            )
        return _respond(answer, "OTHER_QUERIES")

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
        new_email = new_email_match.group(0)
        updated = update_customer_details(db, customer.get("customer_id"), email=new_email)
        if updated:
            session["customer"] = updated
            return _respond(
                f"✅ Your email address has been updated to **{new_email}** in your account profile.",
                "PROFILE_UPDATED",
            )

    # ---- Step 4: upgrade / downgrade cards only after explicit intent ----
    intent = _plan_change_intent(message, current_plan=current_plan)
    if intent in ("UPGRADE", "DOWNGRADE"):
        session["existing_faq_mode"] = False
        options = get_upgrade_downgrade_options(
            db,
            current_plan.get("plan_id") if current_plan else None,
            region=session.get("customer_region"),
        )
        current = options.get("current") or current_plan
        candidates = options["upgrades"] if intent == "UPGRADE" else options["downgrades"]
        if not candidates:
            direction = "an upgrade" if intent == "UPGRADE" else "a downgrade"
            return _respond(
                f"You're already on our {'top' if intent == 'UPGRADE' else 'entry-level'} plan, so there isn't {direction} available.",
                "NO_CHANGE_AVAILABLE",
                current_plan=current,
            )
        display_plans = []
        if current:
            display_plans.append(current)
        seen = {current.get("plan_id")} if current else set()
        for p in candidates:
            if p.get("plan_id") not in seen:
                display_plans.append(p)
                seen.add(p.get("plan_id"))
        session["catalog_plans"] = display_plans
        session["plans_shown"] = True
        return _respond(
            f"Here are your {'upgrade' if intent == 'UPGRADE' else 'downgrade'} options for your region:",
            "PLAN_SELECTION",
            catalog_plans=display_plans,
            current_plan=current,
            plan_change_mode=intent,
        )

    # ---- Step 5: guardrail - only hit RAG for in-domain add-on/support/
    # troubleshooting queries. Unrelated topics (gym, furniture, pillow, etc.)
    # never reach the RAG collection and get a short, dynamically-worded
    # decline instead (never a hardcoded, repeated string). ----
    if not _is_existing_query_relevant(message):
        answer = _existing_llm_reply(
            "existing.guardrail",
            "",
            message=message or "",
            previous_decline=session.get("last_ood_reply") or "none",
        )
        if answer:
            session["last_ood_reply"] = answer
        return _respond(answer, "OUT_OF_DOMAIN")

    # ---- Verified fallback: existing-customer RAG + LLM (short) ----
    answer = _verified_existing_rag_answer(message, session)
    return _respond(
        answer,
        "EXISTING_CUSTOMER_FAQ",
    )



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

    # Apply structured field overrides if present. Do not overwrite a verified
    # existing-customer record with a partial profile payload from the editor.
    if structured_fields:
        session.update({
            k: v for k, v in structured_fields.items()
            if v is not None and k != "customer"
        })

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
        
        # Guardrail: If user did NOT explicitly search for plans, suppress plan dumps from FAQ RAG
        is_plan_search = _is_explicit_plan_search_intent(msg_strip)
        contains_plan_dump = any(term in answer.lower() for term in ["40 mbps", "100 mbps", "200 mbps", "300 mbps", "500 mbps", "1 gbps", "entertainment plan"])
        if not is_plan_search and contains_plan_dump:
            answer = "I can help with broadband plans, routers, installation, and coverage. Please ask a specific question, or share a complete street address with PIN code to check serviceability."

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

    if not re.fullmatch(r"[1-9][0-9]{2}\s?[0-9]{3}", msg_strip):
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
        if not is_order_booking and not re.search(r"[1-9][0-9]{2}\s?[0-9]{3}", msg_strip) and not clean_street_address(msg_strip, pincode):
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

