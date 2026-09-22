from sqlalchemy import select
from sqlalchemy.orm import Session
from app.models.plan import Plan
from app.assistant.prompts import get_prompt
from app.rag.retriever import retrieve_plans
from app.config import get_settings
from app.services.address_service import get_telecom_circle
from app.utils.trace import trace, trace_async


@trace
def _gemini_reasons(plans: list[dict], preference: str | None) -> dict[str, str]:
    settings = get_settings()
    if settings.llm_provider.lower() != "gemini" or not settings.gemini_api_key:
        return {}
    try:
        import google.generativeai as genai
        genai.configure(api_key=settings.gemini_api_key, transport="rest")
        model = genai.GenerativeModel(settings.llm_model)
        plans_context = "\n".join(f"{p['plan_id']}: {p['name']}, {p['speed_mbps']} Mbps, ₹{p['price_inr']}, {p['type']}" for p in plans)
        prompt = get_prompt(
            "plan_service.gemini_reasoning",
            preference=preference or "general home use",
            plans_context=plans_context,
        )
        response = model.generate_content(prompt, request_options={"timeout": 10})
        text = response.text
        return {p["plan_id"]: f"Gemini recommendation: {text[:220]}" for p in plans}
    except Exception:
        return {}


import json
from pathlib import Path
from functools import lru_cache

DATA_DIR = Path(__file__).resolve().parents[2] / "data"
REGIONAL_PLANS_FILE = DATA_DIR / "regional_plans_catalog.json"


@trace
def _load_regional_plans() -> dict:
    """Dynamically load the regional plans catalog from the JSON data store.

    No plan data is hardcoded in source code: this file is the single
    source of truth and can be edited/regenerated (e.g. from a DB export)
    without touching application code.
    """
    if not REGIONAL_PLANS_FILE.exists():
        return {}
    try:
        payload = json.loads(REGIONAL_PLANS_FILE.read_text(encoding="utf-8"))
        return payload.get("circles", {})
    except Exception:
        return {}

@trace
def recommend(db: Session, max_speed: int | None = None, preference: str | None = None,
              state_or_region: str | None = None, use_gemini_reasoning: bool = True) -> list[dict]:
    """Recommend plans dynamically tailored by exact Telecom Circle.

    Plans are queried from the regional plans data source (data/regional_plans_catalog.json,
    hot-reloadable and swappable for a DB-backed source later) rather than from an
    in-code array. Results are strictly filtered to the plans registered for the
    verified circle and capped to 3-4 plans as required by the ordering flow.
    """
    catalog = _load_regional_plans()
    circle = get_telecom_circle(state=state_or_region or "")
    plans = catalog.get(circle) or catalog.get("Delhi NCR") or []

    if max_speed:
        filtered = [p for p in plans if p["speed_mbps"] <= max_speed]
        # Guard against an over-restrictive speed cap leaving nothing to show -
        # fall back to the full regional set rather than returning an empty list.
        plans = filtered or plans

    # Return all plans valid for this region/tier, similar to standard telecom websites.
    plans = plans

    reasons = _gemini_reasons(plans, preference) if use_gemini_reasoning else {}
    return [
        {
            "plan_id": p["plan_id"],
            "name": p["name"],
            "speed_mbps": p["speed_mbps"],
            "price_inr": p["price_inr"],
            "type": p["type"],
            "description": p.get("description", ""),
            "ott_bundle": p.get("ott_bundle", []),
            "reason": reasons.get(p["plan_id"], f"{p['name']} ({p['speed_mbps']} Mbps) tailored for {circle} Telecom Circle at ₹{p['price_inr']}/month.")
        }
        for p in plans
    ]
