import json
import logging
from datetime import datetime
from pathlib import Path
from app.utils.trace import trace, trace_async

logger = logging.getLogger(__name__)

DATA_DIR = Path(__file__).resolve().parents[2] / "data"
ACTIVITY_FILE = DATA_DIR / "activity.jsonl"


@trace
def log_activity(event_type: str, session_id: str, payload: dict | None = None) -> None:
    """Log customer sessions, query events, and booking actions to activity.jsonl."""
    try:
        DATA_DIR.mkdir(parents=True, exist_ok=True)
        entry = {
            "timestamp": datetime.utcnow().isoformat() + "Z",
            "event_type": event_type,
            "session_id": session_id,
            **(payload or {})
        }
        with open(ACTIVITY_FILE, "a", encoding="utf-8") as f:
            f.write(json.dumps(entry) + "\n")
    except Exception as exc:
        logger.warning("Failed to log activity event %s: %s", event_type, exc)
