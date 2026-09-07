"""LLM-Powered Plan Recommendation Assistant (Non-RAG) inside the Order Flow."""
from __future__ import annotations

import json
import logging
import re
from typing import Any

from app.assistant.llm import generate
from app.assistant.prompts import get_prompt
from app.utils.trace import trace

logger = logging.getLogger(__name__)


def calculate_target_speed(users_text: str = "", devices_text: str = "", purpose_text: str = "") -> int:
    """Calculate minimum speed (Mbps) required based on users, devices, and usage purpose."""
    combined = f"{users_text} {devices_text} {purpose_text}".lower()

    # Extract all numbers from text
    user_nums = [int(n) for n in re.findall(r"\b\d+\b", str(users_text))]
    dev_nums = [int(n) for n in re.findall(r"\b\d+\b", str(devices_text))]

    users_count = max(user_nums) if user_nums else (3 if any(k in combined for k in ["many", "family", "multiple"]) else 1)
    devices_count = max(dev_nums) if dev_nums else (4 if any(k in combined for k in ["multiple", "many", "lots"]) else 1)

    # 4K streaming / Gaming / Heavy upload & download demand higher tier
    is_heavy_purpose = any(
        k in combined for k in ["gaming", "4k", "8k", "heavy", "server", "wfh", "video call", "work from home"]
    )

    # Granular speed tier assignment:
    # Minimal tier: 1-2 users, <= 3 devices, basic browsing/light use -> 40 Mbps (₹499 plan)
    if users_count <= 2 and devices_count <= 3 and not is_heavy_purpose:
        return 40
    # Standard tier: 1-2 users, <= 5 devices, HD streaming -> 100 Mbps (₹799 plan)
    elif users_count <= 2 and devices_count <= 5 and not is_heavy_purpose:
        return 100
    # Family/Entertainment tier: 3-4 users, <= 7 devices -> 200 Mbps (₹999 plan)
    elif users_count <= 4 and devices_count <= 7 and not is_heavy_purpose:
        return 200
    # Professional tier: 4-5 users, <= 10 devices or WFH -> 300 Mbps (₹1499 plan)
    elif users_count <= 5 and devices_count <= 10 and not any(k in combined for k in ["4k", "gaming"]):
        return 300
    # Max Giga tier: 6-8 users, <= 15 devices or 4K/Gaming -> 500 Mbps (₹2499 plan)
    elif users_count <= 8 and devices_count <= 15:
        return 500
    # Infinity Ultra Giga tier: > 8 users or > 15 devices -> 1000 Mbps (₹3999 plan)
    else:
        return 1000


@trace
def recommend_plan_conversational(
    plans: list[dict[str, Any]],
    user_query: str,
    users_text: str = "",
    devices_text: str = "",
    purpose_text: str = ""
) -> tuple[str, dict[str, Any] | None]:
    """Evaluate user's use case against active plans and return (intro_message, recommended_plan_dict)."""
    if not plans:
        return "Please verify your street address and PIN code to view available plans in your area.", None

    target_speed = calculate_target_speed(users_text, devices_text, purpose_text)

    # Sort available plans by speed ascending
    sorted_plans = sorted(plans, key=lambda p: p.get("speed_mbps", 0))

    # Pick the plan that best satisfies target_speed
    matching_plans = [p for p in sorted_plans if p.get("speed_mbps", 0) >= target_speed]
    best_math_plan = matching_plans[0] if matching_plans else sorted_plans[-1]

    plans_context = []
    for idx, p in enumerate(plans, 1):
        plans_context.append(
            f"{idx}. Name: '{p.get('name')}' | Speed: {p.get('speed_mbps')} Mbps | Price: ₹{p.get('price_inr')}/month | ID: {p.get('plan_id')}"
        )

    context_str = "\n".join(plans_context)

    prompt = get_prompt(
        "plan_recommendation.conversational",
        context_str=context_str,
        users_or_query=users_text or user_query,
        devices_or_query=devices_text or user_query,
        purpose_or_query=purpose_text or user_query,
        target_speed=target_speed,
    )

    try:
        raw_res = generate(prompt, temperature=0.2, timeout=5, max_tokens=100)
        if raw_res:
            clean_res = raw_res.strip()
            if clean_res.startswith("```"):
                clean_res = clean_res.strip("`").removeprefix("json").strip()
            try:
                data = json.loads(clean_res)
                rec_name = (data.get("recommended_plan_name") or "").lower()
                intro = data.get("short_intro") or "Based on your requirements, here is the best recommended plan for your home:"
                matched_plan = next((p for p in plans if p.get("name", "").lower() == rec_name or rec_name in p.get("name", "").lower()), None)
                if matched_plan:
                    # Check if target_speed matches matched_plan speed tier closely
                    if abs(matched_plan.get("speed_mbps", 0) - target_speed) <= 100 or matched_plan.get("speed_mbps", 0) >= target_speed:
                        return intro, matched_plan
                    else:
                        return intro, best_math_plan
            except Exception:
                pass
            for p in plans:
                if p.get("name", "").lower() in clean_res.lower():
                    return "Based on your requirements, here is the perfect plan recommended for you:", p
    except Exception as exc:
        logger.warning("Conversational plan recommendation failed: %s", exc)

    return "Based on your requirements, here is the perfect plan recommended for you:", best_math_plan
