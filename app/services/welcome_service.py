import logging
import random
import re
from app.assistant.llm import generate, generate_json
from app.assistant.prompts import get_prompt, get_current_language
from app.utils.trace import trace, trace_async

logger = logging.getLogger(__name__)

_DYNAMIC_GREETINGS = {
    "existing": [
        "Welcome back to Signal Selector! How can I help with your current plan, connection troubleshooting, router specs, or plan upgrades today?",
        "Hello again! How can I help with your current plan, connection troubleshooting, router specs, or plan upgrades today?",
        "Welcome back to Signal Selector! I'm here to help with your current plan, connection troubleshooting, router specs, or plan upgrades.",
    ],
    "general": [
        "Welcome to Signal Selector! I am your AI broadband assistant. How can I help you today? You can explore our high-speed fiber plans, check installation timelines, or inquire about Wi-Fi 6 router features.",
        "Hello and welcome to Signal Selector! Looking for ultra-fast fiber internet? Ask me about our unlimited broadband plans (40 Mbps to 1 Gbps), bundled OTT streaming benefits, or check coverage in your area.",
        "Hi there! Welcome to Signal Selector broadband support. I'm here to help you compare high-speed internet plans, learn about our zero-fee installation offers, or find the ideal plan for your home or workspace.",
        "Welcome to Signal Selector! Ready to experience lightning-fast fiber broadband? Let me know what you need—whether it's plan recommendations, 4K streaming benefits, or checking service availability.",
        "Greetings! I am Signal Selector's broadband guide. How can I assist you today with fiber optic internet plans, router specifications, or installation details?",
    ],
}


@trace
def generate_dynamic_greeting(profile: str = "general") -> str:
    """Generate a concise, safe welcome greeting for visitors and existing customers."""
    profile_key = "existing" if profile == "existing" else "general"
    greetings_pool = _DYNAMIC_GREETINGS.get(profile_key, _DYNAMIC_GREETINGS["general"])
    fallback = random.choice(greetings_pool)

    if profile == "existing":
        return fallback

    styles = get_prompt("welcome.styles").splitlines()
    chosen_style = random.choice(styles) if styles else "Greet the user warmly as Signal Selector's broadband AI assistant."

    prompt = get_prompt(
        "welcome.general",
        chosen_style=chosen_style,
        profile=profile,
    )

    try:
        llm_text = generate(prompt, temperature=0.95, timeout=6, max_tokens=150)
        if llm_text and len(llm_text.strip()) > 10:
            cleaned = llm_text.strip().replace("**", "").replace("```", "").strip()
            if profile == "existing":
                forbidden_regex = r"\b(pin|pincode|payment|booking|appointment|address)\b"
            else:
                forbidden_regex = r"\b(pin|pincode|payment|booking|appointment)\b"
            if len(cleaned.split()) <= 35 and not re.search(forbidden_regex, cleaned.lower()):
                return cleaned
    except Exception as exc:
        logger.warning("Dynamic LLM greeting generation error: %s", exc)

    return fallback


def get_rag_faq_topics() -> list[str]:
    """Retrieve available FAQ topic headers dynamically from the knowledge base."""
    try:
        from app.rag.chroma_rag import load_and_chunk_faq_md
        chunks = load_and_chunk_faq_md()
        topics = [c["header"].strip() for c in chunks if c.get("header") and not c["header"].startswith("#")]
        if topics:
            return topics
    except Exception as exc:
        logger.warning("Could not dynamically load RAG FAQ topics: %s", exc)
    return [
        "Broadband Plan Recommendations, Pricing & Speeds",
        "Installation Timelines & Express Dispatch",
        "Router Specifications & Hardware",
        "Installation Charges & Security Deposit",
        "Refund Policy & Money-Back Guarantee",
        "Service Level Agreement (SLA) & Technical Support",
        "Troubleshooting Slow Internet, High Latency & Connection Drops",
        "OTT Entertainment Bundles & Streaming Benefits",
        "Plan Switching, Upgrades & Downgrades",
    ]


@trace
def generate_contextual_followups(
    message: str = "",
    answer: str = "",
    profile: str = "general",
    conversation_history: list[dict[str, str]] | None = None,
    previous_suggestions: list[str] | None = None,
) -> list[str]:
    """Generate 2-3 dynamic contextual follow-up response options (questions or actions) strictly grounded in RAG FAQ and valid application actions."""
    msg_str = (message or "").strip()
    ans_str = (answer or "").strip()
    prev_suggs = previous_suggestions or []

    # Format multi-turn context summary if history is present
    history_context = ""
    if conversation_history:
        recent = conversation_history[-4:]
        turns = [f"{t.get('role', 'user')}: {t.get('content', '')}" for t in recent if t.get('content')]
        if turns:
            history_context = "\n".join(turns)

    combined_msg = f"{history_context}\nuser: {msg_str}" if history_context and msg_str else (msg_str or "Chatbot opened / Welcome")
    prev_str = ", ".join(f"'{s}'" for s in prev_suggs) if prev_suggs else "None"

    # Dynamically extract RAG FAQ topics and valid application actions
    rag_topics = get_rag_faq_topics()
    rag_topics_str = "\n".join(f"- {t}" for t in rag_topics)

    if profile == "existing":
        valid_actions = [
            "I want to upgrade my plan",
            "Report a connection issue",
            "Check my current plan details",
            "Run automated line test",
        ]
    else:
        valid_actions = [
            "I want a new connection",
            "I want to order a connection",
            "Check plan availability for my area",
            "Help me choose the right plan",
        ]
    valid_actions_str = "\n".join(f"- {a}" for a in valid_actions)

    prompt = get_prompt(
        "welcome.followups",
        profile=profile,
        message=combined_msg,
        answer=ans_str or "Welcome greeting",
        rag_topics=rag_topics_str,
        valid_actions=valid_actions_str,
        previous_suggestions=prev_str,
    )
    try:
        data = generate_json(prompt, system=get_prompt("welcome.followups.system"), timeout=5)
        if data and isinstance(data.get("suggestions"), list) and len(data["suggestions"]) > 0:
            raw_suggs = [str(s).strip() for s in data["suggestions"] if s and len(str(s).strip()) > 3]
            # Filter out any that repeat previous suggestions
            filtered = [s for s in raw_suggs if not any(s.lower() == p.lower() for p in prev_suggs)]
            if len(filtered) >= 2:
                return filtered[:3]
            elif len(raw_suggs) >= 2:
                return raw_suggs[:3]
    except Exception as exc:
        logger.warning("LLM follow-up suggestions generation error: %s", exc)

    # Grounded dynamic fallback synthesis derived directly from RAG FAQ topics and valid actions
    prev_low = {p.lower() for p in prev_suggs}
    context_low = (msg_str + " " + ans_str).lower()

    # Build grounded topic candidate options from RAG FAQ knowledge base topics
    topic_candidates = []
    for topic in rag_topics:
        t_low = topic.lower()
        if "pricing" in t_low or "speeds" in t_low or "recommendation" in t_low:
            topic_candidates.extend([
                "What broadband plans and speeds do you offer?",
                "Which plan is best for gaming & WFH?",
                "What is the price of the 300 Mbps plan?",
            ])
        elif "timeline" in t_low or "dispatch" in t_low or "installation timelines" in t_low:
            topic_candidates.extend([
                "What is the installation timeline?",
                "Is express same-day installation available?",
                "How do I book an express 6-hour slot?",
            ])
        elif "router" in t_low or "hardware" in t_low:
            topic_candidates.extend([
                "What Wi-Fi router is provided?",
                "Does the router support Wi-Fi 6?",
                "Do you provide whole-home mesh extenders?",
            ])
        elif "charges" in t_low or "security deposit" in t_low or "fee" in t_low:
            topic_candidates.extend([
                "Are there any installation fees?",
                "Is there a security deposit for the router?",
                "Are there any annual advance plan discounts?",
            ])
        elif "refund" in t_low or "money-back" in t_low:
            topic_candidates.extend([
                "What is your refund policy?",
                "When is the refund credited?",
                "How does the 14-day guarantee work?",
            ])
        elif "ott" in t_low or "streaming" in t_low:
            topic_candidates.extend([
                "Which plan includes Netflix and Hotstar?",
                "Do you have sports & cricket streaming plans?",
                "What OTT subscriptions are included?",
            ])
        elif "sla" in t_low or "support" in t_low or "static ip" in t_low:
            topic_candidates.extend([
                "What is your uptime SLA guarantee?",
                "How do I get a static IP address?",
                "How do I contact customer support?",
            ])
        elif "troubleshoot" in t_low or "slow" in t_low or "drop" in t_low:
            topic_candidates.extend([
                "How do I troubleshoot slow internet speeds?",
                "What do the ONT router LED lights mean?",
                "How to switch to 5GHz Wi-Fi?",
            ])
        elif "upgrades" in t_low or "switch" in t_low:
            topic_candidates.extend([
                "How do I upgrade my current plan?",
                "Can I switch between monthly and annual plans?",
            ])

    # Add valid application actions into candidates
    candidate_pool = []

    # Score and rank candidates by context keyword relevance
    def score_candidate(cand: str) -> int:
        c_words = set(cand.lower().split())
        return sum(1 for w in c_words if len(w) > 3 and w in context_low)

    sorted_topic_cands = sorted(topic_candidates, key=score_candidate, reverse=True)

    # Pick top relevant topic questions that haven't been shown yet
    for cand in sorted_topic_cands:
        if cand.lower() not in prev_low and cand not in candidate_pool:
            candidate_pool.append(cand)
        if len(candidate_pool) >= 2:
            break

    # Add a valid application action (e.g. "I want a new connection" or "I want to order a connection")
    for action in valid_actions:
        if action.lower() not in prev_low and action not in candidate_pool:
            candidate_pool.append(action)
            break

    # If still fewer than 2 items, backfill from remaining fresh topic candidates
    if len(candidate_pool) < 2:
        for cand in topic_candidates + valid_actions:
            if cand.lower() not in prev_low and cand not in candidate_pool:
                candidate_pool.append(cand)
            if len(candidate_pool) >= 3:
                break

    # Final fallback if all fresh candidates were exhausted
    if len(candidate_pool) < 2:
        candidate_pool = [
            "What broadband plans do you offer?",
            "What is your refund policy?",
            "I want a new connection",
        ]

    return candidate_pool[:3]




