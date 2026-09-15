import json
import logging
from pathlib import Path
from typing import Any
from app.utils.trace import trace, trace_async

logger = logging.getLogger(__name__)

DATA_DIR = Path(__file__).resolve().parents[2] / "data"


@trace
def retrieve_plans(query: str, plans: list[Any], limit: int = 5) -> list[Any]:
    """Use Chroma when available; fall back to a rank-matching algorithm over plan catalogs and activity logs."""
    try:
        from app.config import get_settings
        if not get_settings().chroma_enabled:
            raise RuntimeError("Chroma retrieval disabled for local demo")
        import chromadb
        client = chromadb.PersistentClient(path=get_settings().chroma_path)
        collection = client.get_or_create_collection("plans")
        if plans:
            collection.upsert(
                ids=[getattr(p, "plan_id", f"P-{idx}") for idx, p in enumerate(plans)],
                documents=[f"{getattr(p, 'name', '')} {getattr(p, 'type', '')} {getattr(p, 'speed_mbps', '')} Mbps" for p in plans]
            )
        result = collection.query(query_texts=[query], n_results=min(limit, len(plans)))
        ids = (result.get("ids") or [[]])[0]
        by_id = {getattr(p, "plan_id", ""): p for p in plans}
        ranked = [by_id[i] for i in ids if i in by_id]
        return ranked or plans[:limit]
    except Exception:
        words = set(query.lower().split())
        return sorted(
            plans,
            key=lambda p: (
                getattr(p, "type", "fiber").lower() in words or any(w in getattr(p, "name", "").lower() for w in words),
                getattr(p, "speed_mbps", 0)
            ),
            reverse=True
        )[:limit]


@trace
def search_knowledge_base(query: str, limit: int = 5) -> list[dict]:
    """Semantic vector search over faq_knowledge_base.md using ChromaDB embeddings collection."""
    results = []
    try:
        from app.rag.chroma_rag import query_faq_collection
        chunks = query_faq_collection(query, top_k=limit)
        for chunk in chunks:
            results.append({
                "source": "faq_knowledge_base.md",
                "document": "faq_knowledge_base.md",
                "content": chunk,
                "score": 1.0
            })
    except Exception as exc:
        logger.warning("ChromaDB vector retrieval in search_knowledge_base error: %s", exc)

    return results[:limit]
