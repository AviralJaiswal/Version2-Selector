from typing import Any
from app.utils.trace import trace, trace_async


class SessionStore:
    def __init__(self) -> None:
        self._data: dict[str, dict[str, Any]] = {}

    def create(self, session_id: str) -> dict[str, Any]:
        return self._data.setdefault(session_id, {})

    def get(self, session_id: str) -> dict[str, Any]:
        return self._data.setdefault(session_id, {})

    def exists(self, session_id: str) -> bool:
        return session_id in self._data

    @trace
    def update(self, session_id: str, values: dict[str, Any]) -> dict[str, Any]:
        self.get(session_id).update(values)
        return self.get(session_id)


session_store = SessionStore()

