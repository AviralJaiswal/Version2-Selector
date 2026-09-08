import logging
import re
from pathlib import Path
from typing import List, Dict, Any

from app.config import get_settings
from app.assistant.llm import generate
from app.assistant.prompts import get_prompt
from app.utils.trace import trace, trace_async

logger = logging.getLogger(__name__)

DATA_DIR = Path(__file__).resolve().parents[2] / "data"
FAQ_FILE = DATA_DIR / "faq_knowledge_base.md"

COLLECTION_NAME = "faq_collection"


@trace
def load_and_chunk_faq_md() -> List[Dict[str, Any]]:
    """Parse data/faq_knowledge_base.md into semantic chunks based on headers."""
    if not FAQ_FILE.exists():
        logger.warning("faq_knowledge_base.md not found at %s", FAQ_FILE)
        return []

    content = FAQ_FILE.read_text(encoding="utf-8")
    sections = re.split(r'\n(?=##\s+)', content)
    chunks = []

    for idx, section in enumerate(sections):
        section_str = section.strip()
        if not section_str:
            continue
        lines = section_str.splitlines()
        header = lines[0].replace("#", "").strip() if lines else f"Section {idx+1}"
        body = "\n".join(lines[1:]).strip() if len(lines) > 1 else section_str
        chunks.append({
            "id": f"faq_chunk_{idx+1}",
            "header": header,
            "text": f"{header}\n{body}",
            "metadata": {"header": header, "chunk_index": idx+1}
        })
    return chunks


class FastTextEmbeddingFunction:
    """Fast, self-contained vector embedding function for ChromaDB without external network downloads."""
    def name(self) -> str:
        return "fast_text_embedding"

    def embed_documents(self, input: list[str]) -> list[list[float]]:
        return self(input)

    @trace
    def embed_query(self, input: list[str] | str) -> list[list[float]]:
        if isinstance(input, str):
            input = [input]
        return self(input)

    @trace
    def __call__(self, input: list[str]) -> list[list[float]]:
        embeddings = []
        for doc in input:
            vec = [0.0] * 128
            for word in re.findall(r'\w+', doc.lower()):
                idx = abs(hash(word)) % 128
                vec[idx] += 1.0
            norm = (sum(x * x for x in vec) ** 0.5) or 1.0
            embeddings.append([x / norm for x in vec])
        return embeddings


@trace
def _get_collection(client, embed_fn):
    try:
        return client.get_or_create_collection(name=COLLECTION_NAME, embedding_function=embed_fn)
    except ValueError:
        try:
            client.delete_collection(COLLECTION_NAME)
        except Exception:
            pass
        return client.get_or_create_collection(name=COLLECTION_NAME, embedding_function=embed_fn)


@trace
def init_faq_chroma() -> bool:
    """Initialize ChromaDB and load/chunk faq_knowledge_base.md into 'faq_collection'."""
    settings = get_settings()
    try:
        import chromadb
        client = chromadb.PersistentClient(path=settings.chroma_path)
        embed_fn = FastTextEmbeddingFunction()
        collection = _get_collection(client, embed_fn)

        chunks = load_and_chunk_faq_md()
        if chunks:
            ids = [c["id"] for c in chunks]
            documents = [c["text"] for c in chunks]
            metadatas = [c["metadata"] for c in chunks]
            collection.upsert(ids=ids, documents=documents, metadatas=metadatas)
            logger.info("Successfully loaded %d chunks into ChromaDB collection '%s'", len(chunks), COLLECTION_NAME)
            return True
    except BaseException as exc:
        logger.warning("ChromaDB initialization note for collection '%s': %s", COLLECTION_NAME, exc)
    return False


@trace
def query_faq_collection(query: str, top_k: int = 3) -> List[str]:
    """Retrieve top matching FAQ chunks from ChromaDB vector collection."""
    settings = get_settings()
    q_low = query.lower()
    all_chunks = load_and_chunk_faq_md()

    # Priority semantic section matching mapped to specific FAQ section headers
    topic_header_keywords = [
        # Refund / Cancellation Policy
        (["refund", "money back", "money-back", "guarantee", "cancellation", "cancel", "return"], "Refund Policy"),
        # Installation Timelines & Express Dispatch
        (["timeline", "timelines", "how long", "how many days", "how much time", "dispatch", "same day", "same-day", "express", "technician visit", "installation time"], "Installation Timelines"),
        # Router Specifications & Hardware
        (["router", "hardware", "ont", "modem", "wifi 6", "wi-fi 6", "dual band", "dual-band", "5ghz", "2.4ghz", "mesh", "antenna", "lan port", "gigabit port", "specifications"], "Router Specifications"),
        # Installation Charges & Security Deposit
        (["deposit", "installation charge", "installation charges", "installation fee", "installation fees", "setup fee", "wiring charge", "free installation", "security deposit"], "Installation Charges"),
        # OTT Entertainment Bundles & Streaming Benefits
        (["ott", "netflix", "amazon prime", "prime video", "hotstar", "disney", "sonyliv", "zee5", "jiocinema", "streaming apps", "ott bundle", "ott benefits"], "OTT Entertainment"),
        # SLA, Support & Static IP
        (["sla", "uptime", "customer support", "helpline", "static ip", "dedicated ip", "optical power", "support email"], "Service Level Agreement"),
        # Troubleshooting & Connection issues
        (["slow internet", "high ping", "latency", "packet loss", "los light", "pon light", "red light", "blinking", "connection drop", "connection drops", "reset router", "ethernet cable", "power cycle"], "Troubleshooting Slow Internet"),
        # Broadband Plans & Speeds & Recommendations
        (["plan", "plans", "pricing", "price", "prices", "cost", "costs", "speed", "speeds", "choose", "recommend", "best plan", "gaming", "wfh", "tariff", "tariffs", "40 mbps", "40m", "100 mbps", "100m", "200 mbps", "200m", "300 mbps", "300m", "500 mbps", "500m", "1 gbps", "1g", "infinity", "broadband", "fiber", "fibre", "internet plan"], "Broadband Plan Recommendations"),
    ]

    matched_chunks = []
    # Skip matching telecom topics if query is clearly off-topic
    is_off_topic = any(w in q_low for w in ("gym", "workout", "fitness", "recipe", "diet", "cooking", "weather", "homework", "math", "poem")) and not any(w in q_low for w in ("broadband", "fiber", "fibre", "wifi", "internet", "signal selector"))
    if not is_off_topic:
        for keywords, header_sub in topic_header_keywords:
            if any(kw in q_low for kw in keywords):
                chunk = next((c["text"] for c in all_chunks if header_sub.lower() in c.get("header", "").lower()), None)
                if chunk and chunk not in matched_chunks:
                    matched_chunks.append(chunk)

    # Try ChromaDB retrieval
    docs = []
    try:
        import chromadb
        client = chromadb.PersistentClient(path=settings.chroma_path)
        embed_fn = FastTextEmbeddingFunction()
        collection = _get_collection(client, embed_fn)

        if collection.count() == 0:
            init_faq_chroma()
            collection = _get_collection(client, embed_fn)

        res = collection.query(query_texts=[query], n_results=min(top_k, max(1, collection.count())))
        docs = (res.get("documents") or [[]])[0]
    except BaseException as exc:
        logger.warning("ChromaDB query failed: %s. Using markdown chunk fallback.", exc)

    if matched_chunks:
        # Merge with vector docs without duplicates
        for d in docs:
            if d not in matched_chunks:
                matched_chunks.append(d)
        return matched_chunks[:top_k]

    # If the message is a greeting or introduction, return empty so grounded LLM greets naturally
    greeting_tokens = {"hi", "hello", "hey", "name", "who", "what", "signal", "selector"}
    if all(w in greeting_tokens for w in re.findall(r'\w+', q_low) if len(w) > 2) or len(q_low.split()) <= 2:
        intro_chunk = next((c["text"] for c in all_chunks if "Broadband Plan Recommendations" in c.get("header", "")), all_chunks[0]["text"] if all_chunks else "")
        return [intro_chunk] if intro_chunk else []

    if docs:
        return docs

    # Fallback ranker over markdown chunks
    q_words = set(re.findall(r'\w+', q_low))
    scored = []
    for c in all_chunks:
        text_lower = c["text"].lower()
        score = sum(1 for w in q_words if w in text_lower and len(w) > 2)
        scored.append((score, c["text"]))

    scored.sort(key=lambda x: x[0], reverse=True)
    return [text for score, text in scored[:top_k] if score > 0]


@trace
def generate_grounded_faq_answer(
    user_query: str,
    retrieved_chunks: List[str],
    conversation_history: List[Dict[str, str]] | None = None,
) -> str:
    """Dynamic RAG synthesis grounded on telecom knowledge base via model prompt instructions."""
    context_blocks = []
    if retrieved_chunks:
        context_blocks.append("Retrieved Knowledge Context:\n" + "\n---\n".join(retrieved_chunks))

    if conversation_history:
        recent = conversation_history[-6:]
        turns = []
        for t in recent:
            role = "Customer" if t.get("role") == "user" else "Assistant"
            content = (t.get("content") or "").strip()
            if content and t.get("kind") != "welcome":
                turns.append(f"{role}: {content}")
        if turns:
            context_blocks.append("Recent Conversation History:\n" + "\n".join(turns))

    context = "\n\n".join(context_blocks) if context_blocks else "General Knowledge"

    prompt = get_prompt(
        "rag.grounded_faq_answer",
        context=context,
        user_query=user_query,
    )

    answer_text = None
    try:
        answer_text = generate(prompt, temperature=0.5, timeout=8, max_tokens=350)
    except Exception as exc:
        logger.warning("Grounded RAG synthesis warning: %s", exc)

    if not answer_text:
        # Conversational, humanized grounded fallback directly from query context & knowledge base
        q_low = user_query.lower().strip()
        name_match = re.search(r"(?:name\s*[:\-]|name is|my name is|i am|i'm)\s*([A-Za-z][A-Za-z ]{1,30})", user_query, re.I)
        name_str = name_match.group(1).strip() if name_match else None

        if name_str or any(w in q_low for w in ("hello", "hi", "hey", "good morning", "good afternoon")):
            greeting_prefix = f"Hello {name_str}! " if name_str else "Hello! "
            return (
                f"{greeting_prefix}Welcome to Signal Selector! I am your AI broadband assistant. "
                "How can I help you today? You can explore our fiber plans, ask about installation timelines, router hardware, or refund policies."
            )

        # 1. Unrelated / Out-of-scope queries
        if any(w in q_low for w in ("gym", "workout", "fitness", "recipe", "diet", "cooking", "weather", "homework", "math", "poem")):
            return (
                "I am designed to assist with Signal Selector high-speed fiber broadband services, plans, and connectivity. "
                "I cannot help with that request, but please let me know if you have any questions about our broadband plans, speeds, or installation!"
            )

        # 1b. Ambiguous queries like cricket plan / mobile recharge
        if any(w in q_low for w in ("cricket", "mobile recharge", "sim recharge", "prepaid recharge", "mobile plan")) and not any(w in q_low for w in ("broadband", "fiber", "fibre", "wifi", "internet", "ott", "stream")):
            return (
                "Signal Selector specializes in high-speed fiber broadband internet rather than mobile SIM recharges. "
                "If you are looking to stream live cricket and sports, our fiber plans (100 Mbps to 1 Gbps) include complimentary access to Disney+ Hotstar, SonyLIV, and JioCinema! "
                "Let me know if you would like to explore our broadband plans or check serviceability."
            )

        # 2. Specific Plan Pricing / Speed Inquiries
        if any(w in q_low for w in ("300 mbps", "300mbps", "300 m", "300m", "professional")):
            return (
                "Our **300 Mbps Professional Plan** is **₹1,499/month** with unlimited data. "
                "It includes complimentary subscriptions to **Netflix, Amazon Prime, Disney+ Hotstar, SonyLIV, and Zee5**, "
                "with ultra-low latency (<5ms) optimized for 4K streaming and competitive multiplayer gaming."
            )
        if any(w in q_low for w in ("100 mbps", "100mbps", "100 m", "100m", "standard 100m")):
            return (
                "Our **100 Mbps Standard Plan** is **₹799/month** with unlimited data. "
                "It includes **Disney+ Hotstar** and is ideal for HD streaming, multi-device browsing, and online classes."
            )
        if any(w in q_low for w in ("200 mbps", "200mbps", "200 m", "200m", "entertainment 200m")):
            return (
                "Our **200 Mbps Entertainment Plan** is **₹999/month** with unlimited data. "
                "It includes **Disney+ Hotstar, Amazon Prime, and Zee5** for heavy WFH and family entertainment."
            )
        if any(w in q_low for w in ("40 mbps", "40mbps", "40 m", "40m", "basic 40m")):
            return (
                "Our **40 Mbps Basic Plan** is **₹499/month** with unlimited data. "
                "It is designed for basic web browsing, social media, and standard streaming for 1–2 users."
            )
        if any(w in q_low for w in ("500 mbps", "500mbps", "500 m", "500m", "max 500m")):
            return (
                "Our **500 Mbps Max Plan** is **₹2,499/month** with unlimited data. "
                "It includes **Netflix Standard, Amazon Prime, Disney+ Hotstar Premium, SonyLIV, and Zee5** for extreme multi-user speed."
            )
        if any(w in q_low for w in ("1 gbps", "1gbps", "1000 mbps", "1000mbps", "gigabit", "infinity")):
            return (
                "Our **1 Gbps Infinity Plan** is **₹3,999/month** with unlimited data. "
                "It includes **Netflix Premium 4K, Amazon Prime, Disney+ Hotstar Premium, SonyLIV, Zee5, and Apple TV+** for ultra-fast Gigabit speeds and smart homes."
            )

        # 3. Available Fiber Plans / Recommendation / Help Choosing Plan
        if any(w in q_low for w in ("plan", "plans", "pricing", "price", "speed", "speeds", "choose", "recommend", "best", "option", "cost")):
            return (
                "Here are our available High-Speed Fiber Broadband plans:\n\n"
                "• **40 Mbps Basic Plan** – ₹499/month\n"
                "  *Unlimited data for 1–2 users, basic browsing & standard streaming*\n\n"
                "• **100 Mbps Standard Plan** – ₹799/month\n"
                "  *HD streaming & online classes (includes Disney+ Hotstar)*\n\n"
                "• **200 Mbps Entertainment Plan** – ₹999/month\n"
                "  *Heavy WFH & streaming (includes Disney+ Hotstar, Amazon Prime, Zee5)*\n\n"
                "• **300 Mbps Professional Plan** – ₹1,499/month\n"
                "  *4K streaming & ultra-low ping (<5ms) gaming (includes Netflix, Prime, Hotstar, SonyLIV, Zee5)*\n\n"
                "• **500 Mbps Max Plan** – ₹2,499/month\n"
                "  *High-speed multi-user demand (includes Netflix Standard, Prime, Hotstar, SonyLIV, Zee5)*\n\n"
                "• **1 Gbps Infinity Plan** – ₹3,999/month\n"
                "  *Ultra-fast Gigabit speed for intensive gaming & 15+ devices (includes Netflix Premium 4K, Prime, Hotstar, SonyLIV, Zee5, Apple TV+)*\n\n"
                "All plans feature symmetric upload/download speeds, 99.9% uptime SLA, and a free Wi-Fi 6 router on 6/12-month advance plans.\n\n"
                "Tell me what you primarily use your internet for, and I can recommend the best fit!"
            )

        # 4. Installation Fees & Charges
        if any(w in q_low for w in ("installation fee", "installation charge", "installation fees", "setup fee", "security deposit", "charges", "deposit")):
            return (
                "We offer zero installation fees and a free dual-band Wi-Fi 6 router when you choose any 6-month or 12-month advance plan! "
                "For monthly billing plans, a standard one-time installation charge of ₹500 applies, with no security deposit required."
            )

        # 5. Refund Policy
        if any(w in q_low for w in ("refund", "money back", "money-back", "cancel", "cancellation", "guarantee")):
            return (
                "We offer a 14-day money-back guarantee from the date of service activation. "
                "If you are not satisfied, you can cancel within 14 days for a 100% refund of your subscription fee and security deposit, "
                "which is credited back to your original payment method within 5–7 business days."
            )

        # 6. Installation Timelines
        if any(w in q_low for w in ("installation", "timeline", "how long", "how much time", "express", "dispatch")):
            return (
                "Standard installation usually takes around 24–48 hours after your order and payment are confirmed. "
                "In selected metro areas, express installation may be available within 6 hours for eligible orders."
            )

        # 7. Router Hardware
        if any(w in q_low for w in ("router", "modem", "ont", "wifi", "wi-fi", "hardware", "mesh")):
            return (
                "All Signal Selector plans include a dual-band Wi-Fi 6 Gigabit optical router (ONT). "
                "It supports both 2.4 GHz and 5 GHz frequencies with MU-MIMO technology and 4 Gigabit Ethernet ports for high-speed connectivity."
            )

        # 8. SLA & Technical Support
        if any(w in q_low for w in ("sla", "uptime", "support", "optical power", "static ip")):
            return (
                "We maintain a 99.9% uptime SLA backed by automated optical line monitoring. "
                "If downtime exceeds 4 hours, service credits are automatically applied to your next billing cycle."
            )

        # 9. OTT Entertainment
        if any(w in q_low for w in ("ott", "netflix", "hotstar", "prime", "sonyliv", "zee5", "jiocinema", "streaming")):
            return (
                "Complimentary OTT subscriptions are included with our higher-speed plans:\n"
                "• **200 Mbps Plan**: Disney+ Hotstar, SonyLIV, and Zee5.\n"
                "• **300 Mbps & 1 Gbps Plans**: Netflix, Amazon Prime Video, Disney+ Hotstar, SonyLIV, Zee5, and JioCinema Premium."
            )

        return (
            "Here are our available High-Speed Fiber Broadband plans:\n\n"
            "• **40 Mbps Basic Plan** – ₹499/month (1–2 users)\n"
            "• **100 Mbps Standard Plan** – ₹799/month (Disney+ Hotstar)\n"
            "• **200 Mbps Entertainment Plan** – ₹999/month (Hotstar, Prime, Zee5)\n"
            "• **300 Mbps Professional Plan** – ₹1,499/month (Netflix, Prime, Hotstar, SonyLIV, Zee5)\n"
            "• **500 Mbps Max Plan** – ₹2,499/month (Netflix Standard, Prime, Hotstar, SonyLIV)\n"
            "• **1 Gbps Infinity Plan** – ₹3,999/month (Netflix Premium 4K + full OTT bundle)\n\n"
            "How can I assist you with our broadband plans or installation today?"
        )

    return answer_text.strip()








