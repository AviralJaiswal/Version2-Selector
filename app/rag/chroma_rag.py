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

    # 1. Try ChromaDB retrieval
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

    # 2. Priority check: If user query explicitly asks about plans, pricing, speeds, or tariffs,
    # ensure the Broadband Plans chunk is included at position 0.
    plan_keywords = [
        "plan", "plans", "pricing", "price", "prices", "cost", "costs", "speed", "speeds",
        "rate", "rates", "package", "packages", "tier", "tiers", "tariff", "tariffs"
    ]
    order_keywords = [
        "buy", "book", "purchase", "subscribe", "sign up", "get a new", "want to book",
        "i want a new", "need a new", "get connection", "new connection", "order connection"
    ]
    is_plan_query = any(k in q_low for k in plan_keywords) and not any(k in q_low for k in order_keywords)
    if is_plan_query:
        plan_chunk = next((c["text"] for c in all_chunks if "Broadband Plan Recommendations" in c.get("header", "") or "40 Mbps Basic Plan" in c["text"]), None)
        if plan_chunk:
            if docs:
                if plan_chunk not in docs:
                    docs = [plan_chunk] + docs[:top_k - 1]
            else:
                docs = [plan_chunk]

    if docs:
        return docs

    # 3. Fallback ranker over markdown chunks
    q_words = set(re.findall(r'\w+', q_low))
    scored = []
    for c in all_chunks:
        text_lower = c["text"].lower()
        score = sum(1 for w in q_words if w in text_lower and len(w) > 2)
        scored.append((score, c["text"]))

    scored.sort(key=lambda x: x[0], reverse=True)
    return [text for score, text in scored[:top_k] if score > 0]


@trace
def generate_grounded_faq_answer(user_query: str, retrieved_chunks: List[str]) -> str:
    """Dynamic RAG synthesis grounded on telecom knowledge base via model prompt instructions."""
    context = "\n---\n".join(retrieved_chunks) if retrieved_chunks else ""

    prompt = get_prompt(
        "rag.grounded_faq_answer",
        context=context,
        user_query=user_query,
    )

    answer_text = None
    try:
        answer_text = generate(prompt, temperature=0.5, timeout=8, max_tokens=250)
    except Exception as exc:
        logger.warning("Grounded RAG synthesis warning: %s", exc)

    if not answer_text:
        return "⚠️ LLM API Key Required: Please provide a valid GEMINI_API_KEY (starts with AIzaSy...) or OPENROUTER_API_KEY (starts with sk-or-...) in your .env file to enable live AI responses."

    return answer_text.strip()








