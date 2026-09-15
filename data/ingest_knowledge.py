"""Index Markdown knowledge documents into Chroma when configured.

Run from the project root: ``python -m data.ingest_knowledge``.
The application continues to use deterministic file retrieval when Chroma is
disabled or unavailable.
"""
from pathlib import Path

from app.config import get_settings

ROOT = Path(__file__).resolve().parent
KNOWLEDGE_DIR = ROOT / "knowledge_base"


def chunks():
    for path in KNOWLEDGE_DIR.glob("*.md"):
        content = path.read_text(encoding="utf-8")
        for index, section in enumerate(content.split("\n## ")):
            section = section.strip()
            if not section:
                continue
            text = section if section.startswith("## ") else f"## {section}"
            yield f"{path.stem}-{index}", text, {"category": path.stem, "topic": text.splitlines()[0].lstrip("# "), "document": path.name, "authority": "prototype_knowledge_base"}


def ingest() -> None:
    settings = get_settings()
    import chromadb

    client = chromadb.PersistentClient(path=settings.chroma_path)
    collection = client.get_or_create_collection("signal_selector_knowledge")
    items = list(chunks())
    collection.upsert(ids=[item[0] for item in items], documents=[item[1] for item in items], metadatas=[item[2] for item in items])
    print(f"Indexed {len(items)} knowledge chunks in {settings.chroma_path}")


if __name__ == "__main__":
    ingest()
