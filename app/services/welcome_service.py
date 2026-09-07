import logging
import random
from app.assistant.llm import generate, generate_json
from app.assistant.prompts import get_prompt, get_current_language
from app.utils.trace import trace, trace_async

logger = logging.getLogger(__name__)

_FALLBACK_GREETINGS = {
    "existing": {
        "en": "Welcome back! I am your Signal Selector assistant. How can I help with your account, plan upgrades, or technical support today?",
        "hi": "\u0906\u092a\u0915\u093e \u0938\u094d\u0935\u093e\u0917\u0924 \u0939\u0948! \u092e\u0948\u0902 \u0906\u092a\u0915\u093e Signal Selector \u0938\u0939\u093e\u092f\u0915 \u0939\u0942\u0902\u0964 \u092e\u0948\u0902 \u0906\u092a\u0915\u0947 \u0916\u093e\u0924\u0947, \u092a\u094d\u0932\u093e\u0928 \u0905\u092a\u0917\u094d\u0930\u0947\u0921, \u092f\u093e \u0924\u0915\u0928\u0940\u0915\u0940 \u0938\u0939\u093e\u092f\u0924\u093e \u092e\u0947\u0902 \u0915\u0948\u0938\u0947 \u092e\u0926\u0926 \u0915\u0930 \u0938\u0915\u0924\u093e \u0939\u0942\u0902?",
        "te": "\u0c2e\u0c40\u0c30\u0c41 \u0c24\u0c3f\u0c30\u0c3f\u0c17\u0c3f \u0c38\u0c4d\u0c35\u0c3e\u0c17\u0c24\u0c02! \u0c28\u0c47\u0c28\u0c41 \u0c2e\u0c40 Signal Selector \u0c38\u0c39\u0c3e\u0c2f\u0c15\u0c41\u0c21\u0c3f\u0c28\u0c3f. \u0c2e\u0c40 \u0c16\u0c3e\u0c24\u0c3e, \u0c2a\u0c4d\u0c32\u0c3e\u0c28\u0c4d \u0c05\u0c2a\u0c4d\u0c17\u0c4d\u0c30\u0c47\u0c21\u0c4d, \u0c32\u0c47\u0c26\u0c3e \u0c38\u0c3e\u0c02\u0c15\u0c47\u0c24\u0c3f\u0c15 \u0c2e\u0c26\u0c4d\u0c26\u0c24\u0c41\u0c32\u0c4b \u0c07\u0c35\u0c3e\u0c33 \u0c28\u0c47\u0c28\u0c41 \u0c0e\u0c32\u0c3e \u0c38\u0c39\u0c3e\u0c2f\u0c02 \u0c1a\u0c47\u0c2f\u0c17\u0c32\u0c28\u0c41?",
        "ta": "\u0bae\u0bc0\u0ba3\u0bcd\u0b9f\u0bc1\u0bae\u0bcd \u0bb5\u0bb0\u0bb5\u0bc7\u0bb1\u0bcd\u0b95\u0bbf\u0bb1\u0bcb\u0bae\u0bcd! \u0ba8\u0bbe\u0ba9\u0bcd \u0b89\u0b99\u0bcd\u0b95\u0bb3\u0bcd Signal Selector \u0b89\u0ba4\u0bb5\u0bbf\u0baf\u0bbe\u0bb3\u0bb0\u0bcd. \u0b89\u0b99\u0bcd\u0b95\u0bb3\u0bcd \u0b95\u0ba3\u0b95\u0bcd\u0b95\u0bc1, \u0ba4\u0bbf\u0b9f\u0bcd\u0b9f \u0bae\u0bc7\u0bae\u0bcd\u0baa\u0bbe\u0b9f\u0bc1, \u0b85\u0bb2\u0bcd\u0bb2\u0ba4\u0bc1 \u0ba4\u0bca\u0bb4\u0bbf\u0bb2\u0bcd\u0ba8\u0bc1\u0b9f\u0bcd\u0baa \u0b89\u0ba4\u0bb5\u0bbf\u0b95\u0bcd\u0b95\u0bc1 \u0ba8\u0bbe\u0ba9\u0bcd \u0b8e\u0baa\u0bcd\u0baa\u0b9f\u0bbf \u0b89\u0ba4\u0bb5 \u0bae\u0bc1\u0b9f\u0bbf\u0baf\u0bc1\u0bae\u0bcd?",
    },
    "general": {
        "en": "Welcome to Signal Selector! How can I help you today? Please share your complete street address (including building/flat number, street name, area, and pincode) so we can check exact fiber availability and fetch local plans.",
        "hi": "Signal Selector \u092e\u0947\u0902 \u0906\u092a\u0915\u093e \u0938\u094d\u0935\u093e\u0917\u0924 \u0939\u0948! \u0906\u091c \u092e\u0948\u0902 \u0906\u092a\u0915\u0940 \u0915\u094d\u092f\u093e \u092e\u0926\u0926 \u0915\u0930 \u0938\u0915\u0924\u093e \u0939\u0942\u0902? \u0915\u0943\u092a\u092f\u093e \u0905\u092a\u0928\u093e \u092a\u0942\u0930\u093e \u092a\u0924\u093e (\u092d\u0935\u0928/\u092b\u094d\u0932\u0948\u091f \u0928\u0902\u092c\u0930, \u0938\u0921\u093c\u0915 \u0915\u093e \u0928\u093e\u092e, \u0907\u0932\u093e\u0915\u093e, \u0914\u0930 \u092a\u093f\u0928\u0915\u094b\u0921 \u0938\u0939\u093f\u0924) \u0938\u093e\u091d\u093e \u0915\u0930\u0947\u0902 \u0924\u093e\u0915\u093f \u0939\u092e \u0909\u092a\u0932\u092c\u094d\u0927\u0924\u093e \u091c\u093e\u0902\u091a \u0938\u0915\u0947\u0902\u0964",
        "te": "Signal Selector \u0c15\u0c3f \u0c38\u0c4d\u0c35\u0c3e\u0c17\u0c24\u0c02! \u0c08\u0c30\u0c4b\u0c1c\u0c41 \u0c28\u0c47\u0c28\u0c41 \u0c2e\u0c40\u0c15\u0c41 \u0c0e\u0c32\u0c3e \u0c38\u0c39\u0c3e\u0c2f\u0c02 \u0c1a\u0c47\u0c2f\u0c17\u0c32\u0c28\u0c41? \u0c26\u0c2f\u0c1a\u0c47\u0c38\u0c3f \u0c2e\u0c40 \u0c2a\u0c42\u0c30\u0c4d\u0c24\u0c3f \u0c1a\u0c3f\u0c30\u0c41\u0c28\u0c3e\u0c2e\u0c3e (\u0c2c\u0c3f\u0c32\u0c4d\u0c21\u0c3f\u0c02\u0c17\u0c4d/\u0c2b\u0c4d\u0c32\u0c3e\u0c1f\u0c4d \u0c28\u0c02\u0c2c\u0c30\u0c4d, \u0c35\u0c40\u0c27\u0c3f \u0c2a\u0c47\u0c30\u0c41, \u0c2a\u0c4d\u0c30\u0c3e\u0c02\u0c24\u0c02, \u0c2e\u0c30\u0c3f\u0c2f\u0c41 \u0c2a\u0c3f\u0c28\u0c4d\u200c\u0c15\u0c4b\u0c21\u0c4d\u0c24\u0c4b \u0c38\u0c39\u0c3e) \u0c07\u0c35\u0c4d\u0c35\u0c02\u0c21\u0c3f, \u0c07\u0c26\u0c3f \u0c2e\u0c3e\u0c15\u0c41 \u0c38\u0c30\u0c3f\u0c15\u0c4c\u0c28 \u0c2b\u0c48\u0c2c\u0c30\u0c4d \u0c05\u0c02\u0c26\u0c41\u0c2c\u0c3e\u0c1f\u0c41\u0c28\u0c41 \u0c24\u0c28\u0c3f\u0c16\u0c40 \u0c1a\u0c47\u0c2f\u0c21\u0c3e\u0c28\u0c3f\u0c15\u0c3f \u0c38\u0c39\u0c3e\u0c2f\u0c2a\u0c21\u0c41\u0c24\u0c41\u0c02\u0c26\u0c3f.",
        "ta": "Signal Selector \u0b95\u0bcd\u0b95\u0bc1 \u0bb5\u0bb0\u0bb5\u0bc7\u0bb1\u0bcd\u0b95\u0bbf\u0bb1\u0bcb\u0bae\u0bcd! \u0b87\u0b9f\u0bcd\u0bb1\u0bc1 \u0ba8\u0bbe\u0ba9\u0bcd \u0b89\u0b99\u0bcd\u0b95\u0bb3\u0bc1\u0b95\u0bcd\u0b95\u0bc1 \u0b8e\u0bb5\u0bcd\u0bb5\u0bbe\u0bb1\u0bc1 \u0b89\u0ba4\u0bb5 \u0bae\u0bc1\u0b9f\u0bbf\u0baf\u0bc1\u0bae\u0bcd? \u0b89\u0b99\u0bcd\u0b95\u0bb3\u0bcd \u0bae\u0bc1\u0bb4\u0bc1 \u0bae\u0bc1\u0b95\u0bb5\u0bb0\u0bbf\u0baf\u0bc8\u0baa\u0bcd (\u0b95\u0b9f\u0bcd\u0b9f\u0bbf\u0b9f/\u0baa\u0bcd\u0bb3\u0bbe\u0b9f\u0bcd \u0b8e\u0ba3\u0bcd, \u0ba4\u0bc6\u0bb0\u0bc1 \u0baa\u0bc6\u0baf\u0bb0\u0bcd, \u0baa\u0b95\u0bc1\u0ba4\u0bbf, \u0bae\u0bb1\u0bcd\u0bb1\u0bc1\u0bae\u0bcd \u0baa\u0bbf\u0ba9\u0bcd\u0b95\u0bcb\u0b9f\u0bcd \u0b89\u0bb3\u0bcd\u0baa\u0b9f) \u0baa\u0b95\u0bbf\u0bb0\u0bb5\u0bc1\u0bae\u0bcd, \u0b9a\u0bb0\u0bbf\u0baf\u0bbe\u0ba9 \u0bb5\u0bb8\u0ba4\u0bbf \u0b95\u0b3f\u0b9f\u0bc8\u0baa\u0bcd\u0baa\u0bc8\u0baa\u0bcd \u0baa\u0bb0\u0bbf\u0b9a\u0bc0\u0bb2\u0bbf\u0b95\u0bcd\u0b95 \u0b87\u0ba4\u0bc1 \u0b89\u0ba4\u0bb5\u0bc1\u0bae\u0bcd.",
    },
}


@trace
def generate_dynamic_greeting(profile: str = "general") -> str:
    """Generate dynamic welcome greeting strictly using AI model prompt instructions."""
    styles = get_prompt("welcome.styles").splitlines()
    chosen_style = random.choice(styles)

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
        llm_text = generate(prompt, temperature=0.95, timeout=6, max_tokens=80)
        if llm_text and len(llm_text.strip()) > 10:
            return llm_text.strip()
    except Exception as exc:
        logger.warning("Dynamic LLM greeting generation error: %s", exc)

    profile_key = "existing" if profile == "existing" else "general"
    lang = get_current_language()
    fallback_set = _FALLBACK_GREETINGS[profile_key]
    return fallback_set.get(lang, fallback_set["en"])


@trace
def generate_contextual_followups(
    message: str = "",
    answer: str = "",
    profile: str = "general"
) -> list[str]:
    """Generate 3 dynamic contextual follow-up response options for the user strictly via LLM."""
    prompt = get_prompt(
        "welcome.followups",
        profile=profile,
        message=message or "Chatbot opened / Initial Welcome",
        answer=answer or "Welcome greeting",
    )
    try:
        data = generate_json(prompt, system=get_prompt("welcome.followups.system"), timeout=5)
        if data and isinstance(data.get("suggestions"), list) and len(data["suggestions"]) > 0:
            valid_suggestions = [str(s).strip() for s in data["suggestions"] if s and len(str(s).strip()) > 3]
            if len(valid_suggestions) >= 2:
                return valid_suggestions[:3]
    except Exception as exc:
        logger.warning("LLM follow-up suggestions generation error: %s", exc)

    if profile == "existing":
        return ["I want to upgrade my fiber plan", "Report a slow connection issue", "Show available add-on packs"]
    return ["I want to get a new connection", "I want to book a fiber plan", "Which plan is best for gaming & WFH?"]




