import logging
import random
from app.assistant.llm import generate, generate_json
from app.assistant.prompts import get_prompt, get_current_language
from app.utils.trace import trace, trace_async

logger = logging.getLogger(__name__)

_DYNAMIC_GREETINGS = {
    "existing": [
        "Welcome back to Signal Selector. Please share your registered 10-digit mobile number so I can verify your connection.",
        "Hello again! To pull up your Signal Selector connection, could you share the registered contact number on the account?",
        "Welcome back. Share your registered mobile number and I will verify your existing fiber connection.",
        "Glad you are back. Please provide the 10-digit registered contact number for this connection so I can verify it.",
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
    """Generate dynamic welcome greeting strictly using AI model prompt instructions with dynamic variation."""
    styles = get_prompt("welcome.styles").splitlines()
    chosen_style = random.choice(styles) if styles else "Greet the user warmly as Signal Selector's broadband AI assistant."

    if profile == "existing":
        prompt = get_prompt(
            "welcome.existing",
            chosen_style=chosen_style,
            profile=profile,
        )
    else:
        prompt = get_prompt(
            "welcome.general",
            chosen_style=chosen_style,
            profile=profile,
        )

    try:
        llm_text = generate(prompt, temperature=0.95, timeout=6, max_tokens=150)
        if llm_text and len(llm_text.strip()) > 10:
            return llm_text.strip()
    except Exception as exc:
        logger.warning("Dynamic LLM greeting generation error: %s", exc)

    profile_key = "existing" if profile == "existing" else "general"
    greetings_pool = _DYNAMIC_GREETINGS.get(profile_key, _DYNAMIC_GREETINGS["general"])
    return random.choice(greetings_pool)


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
    """Generate 2-3 dynamic contextual follow-up response options grounded in the active RAG topic and request context."""
    msg_str = (message or "").strip()
    ans_str = (answer or "").strip()
    prev_suggs = previous_suggestions or []

    history_context = ""
    if conversation_history:
        recent = conversation_history[-4:]
        turns = [f"{t.get('role', 'user')}: {t.get('content', '')}" for t in recent if t.get('content')]
        if turns:
            history_context = "\n".join(turns)

    combined_msg = f"{history_context}\nuser: {msg_str}" if history_context and msg_str else (msg_str or "Chatbot opened / Welcome")
    prev_str = ", ".join(f"'{s}'" for s in prev_suggs) if prev_suggs else "None"

    rag_topics = get_rag_faq_topics()
    rag_topics_str = "\n".join(f"- {t}" for t in rag_topics)

    if profile == "existing":
        valid_actions = []
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
            filtered = [s for s in raw_suggs if not any(s.lower() == p.lower() for p in prev_suggs)]
            if len(filtered) >= 2:
                return filtered[:3]
            elif len(raw_suggs) >= 2:
                return raw_suggs[:3]
    except Exception as exc:
        logger.warning("LLM follow-up suggestions generation error: %s", exc)

    context_low = (msg_str + " " + ans_str).lower()
    topic_candidates: list[str] = []
    topic_rules = [
        ("refund", ["What is your refund policy?", "How does the 14-day guarantee work?", "When is the refund credited?"]),
        ("installation", ["What is the installation timeline?", "Is express same-day installation available?", "How do I book an express slot?"]),
        ("router", ["What Wi-Fi router is provided?", "Does the router support Wi-Fi 6?", "Do you provide mesh extenders?"]),
        ("plan", ["What broadband plans and speeds do you offer?", "Which plan is best for gaming & WFH?", "What is the price of the 300 Mbps plan?"]),
        ("ott", ["Which plan includes Netflix and Hotstar?", "What OTT subscriptions are included?", "Do you have sports streaming bundles?"]),
        ("support", ["How do I contact customer support?", "How do I troubleshoot slow internet?", "What is your uptime SLA guarantee?"]),
    ]

    for keyword, candidates in topic_rules:
        if keyword in context_low:
            topic_candidates.extend(candidates)

    if not topic_candidates:
        for topic in rag_topics:
            t_low = topic.lower()
            if any(key in t_low for key in ("plan", "pricing", "installation", "router", "refund", "ott", "support", "troubleshoot")):
                topic_candidates.append(f"What do you offer in {topic}?")

    candidate_pool: list[str] = []
    for cand in topic_candidates + list(valid_actions):
        norm = cand.strip()
        if not norm or any(norm.lower() == p.lower() for p in prev_suggs):
            continue
        if norm not in candidate_pool:
            candidate_pool.append(norm)
        if len(candidate_pool) >= 3:
            break

    if len(candidate_pool) < 2:
        candidate_pool = [
            "What broadband plans do you offer?",
            "What is your installation timeline?",
            "I want a new connection",
        ]

    return [s for s in candidate_pool[:3] if s and not any(s.lower() == p.lower() for p in prev_suggs)]




