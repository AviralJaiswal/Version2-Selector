"""Loader for externalized LLM prompt templates stored in PROMPTS.txt.

All prompt text used anywhere in the backend lives in PROMPTS.txt at the
repo root, keyed by dotted names (e.g. "service.escape_reset"). This module
parses that file once, caches it, and exposes `get_prompt(key, **kwargs)`
for formatting.

Editing prompt wording should only ever require editing PROMPTS.txt -
no Python changes needed unless a prompt's variable set changes.
"""
from __future__ import annotations

import re
from contextvars import ContextVar
from functools import lru_cache
from pathlib import Path

PROMPTS_FILE = Path(__file__).resolve().parents[2] / "PROMPTS.txt"

_ENTRY_PATTERN = re.compile(
    r"BEGIN_PROMPT[ \t]+(\S+)\r?\n(.*?)\r?\nEND_PROMPT[ \t]+\1",
    re.DOTALL,
)

# Per-request "current response language" - set once at the top of
# handle_message() via set_current_language(), read by every get_prompt()
# call for the rest of that request without threading a `language` param
# through dozens of _generate_* function signatures. ContextVar is safe
# across FastAPI's async request handling (each request gets its own copy).
_current_language: ContextVar[str] = ContextVar("_current_language", default="en")


def set_current_language(language: str | None) -> None:
    _current_language.set(language or "en")


def get_current_language() -> str:
    return _current_language.get()


class PromptError(Exception):
    """Raised when a requested prompt key is missing or the file is unreadable."""


@lru_cache
def _load_prompts() -> dict[str, str]:
    if not PROMPTS_FILE.exists():
        raise PromptError(f"PROMPTS.txt not found at {PROMPTS_FILE}")

    content = PROMPTS_FILE.read_text(encoding="utf-8")
    matches = _ENTRY_PATTERN.findall(content)
    if not matches:
        raise PromptError(f"No BEGIN_PROMPT/END_PROMPT entries found in {PROMPTS_FILE}")

    prompts: dict[str, str] = {}
    for key, body in matches:
        prompts[key] = body.strip("\n")
    return prompts


def reload_prompts() -> None:
    """Clear the cache so the next get_prompt() call re-reads PROMPTS.txt from disk."""
    _load_prompts.cache_clear()


def get_prompt(key: str, *, language: str | None = None, **kwargs: object) -> str:
    """Return the prompt template for `key`, with {{placeholder}} tokens filled from kwargs.

    Only literal ``{{name}}`` tokens are substituted (regex-based, not str.format),
    so runtime values - RAG context, raw user messages, LLM output being re-fed
    into a prompt - can safely contain stray `{` or `}` characters without
    breaking rendering. Curly braces belong to any template author writing
    PROMPTS.txt; only their {{double-brace}} tokens are treated as placeholders.

    Language detection and response mirroring are LLM-driven: the prompt instructs
    the model to automatically understand and reply in the customer's language.

    Raises PromptError if the key doesn't exist, so a missing/renamed key fails
    loudly at call time instead of silently sending an empty prompt to the LLM.
    """
    prompts = _load_prompts()
    if key not in prompts:
        raise PromptError(f"Unknown prompt key: {key!r} (not found in {PROMPTS_FILE})")

    template = prompts[key]

    def _substitute(match: re.Match) -> str:
        name = match.group(1)
        if name not in kwargs:
            raise PromptError(f"Prompt {key!r} references missing placeholder {{{{{name}}}}}")
        return str(kwargs[name])

    rendered = re.sub(r"\{\{(\w+)\}\}", _substitute, template) if kwargs else template

    # For customer-facing generation prompts (not internal JSON classifiers), add dynamic LLM language and output instruction
    if not key.endswith(".system_json") and not key.endswith(".system_fallback") and not key.endswith(".system") and "classify" not in key and "extraction" not in key:
        rendered += (
            "\n\n[Directive]: Provide ONLY the final customer-facing response. Do NOT output internal thinking process, reasoning, planning, analysis, or drafting notes. "
            "Detect the language of the customer's input. Always write your response in the EXACT same language (e.g. English, Hindi, Telugu, Tamil, Kannada, Malayalam, Marathi, Bengali, etc.). "
            "Never translate or modify plan names, brand names ('Signal Selector'), plan IDs, URLs, or numeric values (prices, speeds, PIN codes)."
        )

    return rendered
