"""Server-side OpenRouter LLM adapter shared by assistant features."""
from __future__ import annotations

import json
import logging
import re
from typing import Any

import requests

from app.config import get_settings
from app.assistant.prompts import get_prompt
from app.services.http_client import requests_verify_setting
from app.utils.trace import trace, trace_async

logger = logging.getLogger(__name__)


class LLMError(Exception):
    """Actionable OpenRouter failure with safe diagnostic details."""

    def __init__(
        self,
        message: str,
        *,
        status_code: int | None = None,
        response_body: str | None = None,
        model: str | None = None,
        endpoint: str | None = None,
        retryable: bool = False,
    ) -> None:
        super().__init__(message)
        self.status_code = status_code
        self.response_body = response_body
        self.model = model
        self.endpoint = endpoint
        self.retryable = retryable

    @trace
    def user_message(self) -> str:
        if self.status_code == 402:
            return (
                "The AI assistant is temporarily unavailable due to account credit limits. "
                "Please try again later or contact support."
            )
        if self.status_code == 401:
            return "The AI assistant is misconfigured. Please contact support."
        if self.status_code == 429:
            return "The AI assistant is busy right now. Please try again in a moment."
        if self.status_code in {500, 502, 503}:
            return "The AI assistant encountered a temporary service error. Please try again."
        return "The AI assistant is temporarily unavailable. Please try again."


@trace
def _safe_response_body(response: requests.Response | None) -> str:
    if response is None:
        return ""
    try:
        return response.text[:2000]
    except Exception:
        return ""


@trace
def _raise_for_http_error(response: requests.Response, *, model: str | None = None, endpoint: str | None = None) -> None:
    status_code = response.status_code
    body = _safe_response_body(response)
    retryable = status_code in {429, 500, 502, 503, 504}
    msg = f"OpenRouter HTTP error {status_code}: {body[:200]}"
    raise LLMError(
        msg,
        status_code=status_code,
        response_body=body,
        model=model,
        endpoint=endpoint,
        retryable=retryable,
    )


@trace
def strip_thinking_and_reasoning(text: str | None) -> str:
    """Robustly sanitize LLM output to eliminate internal thinking, reasoning tags, and drafting traces."""
    if not text:
        return ""
    cleaned = str(text)

    # 1. Remove XML/HTML style thought/think/reasoning tags
    cleaned = re.sub(r"<(?:think|thought|reasoning|system)>.*?</(?:think|thought|reasoning|system)>", "", cleaned, flags=re.DOTALL | re.IGNORECASE)
    cleaned = re.sub(r"^<(?:think|thought|reasoning|system)>.*?</(?:think|thought|reasoning|system)>", "", cleaned, flags=re.DOTALL | re.IGNORECASE)

    # 2. Strip "Here's a thinking process:" and any reasoning blocks up to the final answer
    if re.search(r"^\s*(?:Here(?:'s| is) a thinking process|Thinking Process|Internal Reasoning|Reasoning Process):", cleaned, flags=re.IGNORECASE):
        # Look for explicit response headers
        final_match = re.search(
            r"(?:###\s*(?:Final Response|Final Answer|Response|Output|Customer-Facing Response)|(?:\*\*|__)(?:Final Response|Final Answer|Response|Output)(?:\*\*|__)|(?:Final Response|Final Answer|Response|Output):\s*)(.*)",
            cleaned,
            flags=re.DOTALL | re.IGNORECASE,
        )
        if final_match and final_match.group(1).strip():
            cleaned = final_match.group(1).strip()
        else:
            lines = cleaned.split("\n")
            output_lines = []
            in_thinking = True
            for line in lines:
                l_strip = line.strip()
                if in_thinking:
                    # Check if line marks start of customer-facing greeting or content
                    if re.match(r"^(?:Hello|Hi|Welcome|Sure|Great|Thank you|Dear|Namaste|Signal Selector|\*|I can help|We offer|Good day)", l_strip, flags=re.IGNORECASE) and not re.search(r"Draft|Word count|Attempt|Analyze|Identify", l_strip, flags=re.IGNORECASE):
                        in_thinking = False
                        output_lines.append(line)
                    elif re.match(r"^(?:Final Response|Response|Output):", l_strip, flags=re.IGNORECASE):
                        in_thinking = False
                else:
                    if not re.match(r"^(?:Word count:|Note:|Explanation:)", l_strip, flags=re.IGNORECASE):
                        output_lines.append(line)
            if output_lines:
                cleaned = "\n".join(output_lines).strip()
            else:
                # If output contained only thinking without a final response, clean to empty so fallback/retry can handle it
                cleaned = ""

    # 3. Strip leading/trailing code block fences wrapping plain text
    cleaned = re.sub(r"^```(?:markdown|text|plaintext)?\s*", "", cleaned, flags=re.IGNORECASE)
    cleaned = re.sub(r"\s*```$", "", cleaned)

    # 4. Strip system instruction or language directive echoes
    cleaned = re.sub(r"\[(?:System Instruction|Language Directive|Internal Analysis)\]:?.*?\n", "", cleaned, flags=re.IGNORECASE)

    return cleaned.strip()


@trace
def llm_available() -> bool:
    settings = get_settings()
    return bool(settings.gemini_api_key or settings.openrouter_api_key or settings.openai_api_key)


@trace
def _call_gemini_rest(
    messages: list[dict[str, str]],
    api_key: str,
    model: str = "gemini-2.5-flash",
    *,
    system: str | None = None,
    timeout: int = 8,
    temperature: float = 0.8,
) -> str | None:
    models_to_try = [model, "gemini-2.5-flash", "gemini-2.0-flash", "gemini-1.5-flash"]
    target_models = list(dict.fromkeys([m for m in models_to_try if m]))

    contents = []
    if system:
        contents.append({"role": "user", "parts": [{"text": get_prompt("llm.gemini_system_instruction", system=system)}]})
    for m in messages:
        role = "user" if m.get("role") in {"user", "system"} else "model"
        contents.append({"role": role, "parts": [{"text": m.get("content", "")}]})

    payload = {
        "contents": contents,
        "generationConfig": {
            "temperature": temperature,
            "thinkingConfig": {"thinkingBudget": 0},
        },
    }

    for target_model in target_models:
        url = f"https://generativelanguage.googleapis.com/v1beta/models/{target_model}:generateContent?key={api_key}"
        try:
            res = requests.post(url, json=payload, timeout=min(timeout, 8), verify=requests_verify_setting())
            if res.status_code == 200:
                data = res.json()
                candidates = data.get("candidates", [])
                if candidates:
                    parts = candidates[0].get("content", {}).get("parts", [])
                    if parts:
                        # Filter out internal thought parts completely
                        non_thought = [p.get("text", "") for p in parts if not p.get("thought")]
                        raw_text = "".join(non_thought).strip() if non_thought else "".join(p.get("text", "") for p in parts).strip()
                        cleaned = strip_thinking_and_reasoning(raw_text)
                        if cleaned:
                            return cleaned
        except Exception as exc:
            logger.warning("Gemini REST API attempt failed model=%s err=%s", target_model, exc)
    return None


# Global set of models that failed with 402 to avoid repeated 402 attempts during process lifecycle
_FAILED_402_MODELS: set[str] = set()


@trace
def chat(
    messages: list[dict[str, str]],
    *,
    system: str | None = None,
    timeout: int = 10,
    temperature: float = 0.7,
    max_tokens: int | None = None,
    raise_on_error: bool = False,
) -> str | None:
    """Return assistant text from Gemini or OpenRouter, or None when unavailable."""
    settings = get_settings()

    if not llm_available():
        logger.warning("LLM unavailable: no API key loaded in environment")
        if raise_on_error:
            raise LLMError("LLM is not configured")
        return None

    openrouter_key = settings.openrouter_api_key or (settings.gemini_api_key if settings.gemini_api_key and settings.gemini_api_key.startswith("sk-or-") else None)

    # 1. Try OpenRouter API if OpenRouter key is configured
    if openrouter_key:
        sys_directive = "Provide ONLY the final customer-facing response. Do NOT output thinking, analysis, reasoning steps, drafting notes, or planning."
        full_system = f"{sys_directive}\n{system}" if system else sys_directive

        payload_messages: list[dict[str, str]] = [{"role": "system", "content": full_system}]
        payload_messages.extend(messages)

        url = f"{settings.openrouter_base_url.rstrip('/')}/chat/completions"
        configured_model = settings.llm_model if "/" in settings.llm_model else "openai/gpt-4o-mini"
        headers = {
            "Authorization": f"Bearer {openrouter_key}",
            "Content-Type": "application/json",
            "HTTP-Referer": settings.api_base_url,
            "X-Title": settings.app_name,
        }

        # Build candidate list: if paid model hit 402, use active free models directly
        candidate_models: list[str] = []
        if configured_model not in _FAILED_402_MODELS:
            candidate_models.append(configured_model)
        if ":free" not in configured_model or configured_model in _FAILED_402_MODELS:
            candidate_models.extend([
                "nvidia/nemotron-3-super-120b-a12b:free",
                "nvidia/nemotron-3.5-lightning:free",
                "inclusionai/ling-3.0-flash-sante:free",
            ])

        for candidate_model in candidate_models:
            eff_tokens = max_tokens if max_tokens is not None else (settings.llm_max_tokens or 350)
            payload = {
                "model": candidate_model,
                "messages": payload_messages,
                "temperature": temperature,
                "max_tokens": eff_tokens,
                "reasoning": {"max_tokens": 0},
            }

            try:
                logger.info("Calling OpenRouter: model=%s url=%s", candidate_model, url)
                response = requests.post(
                    url,
                    headers=headers,
                    json=payload,
                    timeout=min(timeout, 8),
                    verify=requests_verify_setting(),
                )

                if response.status_code == 402:
                    _OPENROUTER_PAID_402 = True
                    logger.warning("OpenRouter 402 on %s, switching to free models", candidate_model)
                    if raise_on_error and candidate_model == configured_model and len(candidate_models) == 1:
                        _raise_for_http_error(response, model=candidate_model, endpoint=url)
                    elif raise_on_error and candidate_model == configured_model:
                        _raise_for_http_error(response, model=candidate_model, endpoint=url)
                    continue

                if response.status_code == 429:
                    logger.warning("OpenRouter 429 rate limit on %s: %s", candidate_model, response.text[:150])
                    if raise_on_error and candidate_model == configured_model:
                        _raise_for_http_error(response, model=candidate_model, endpoint=url)
                    if "free-models-per-day" in response.text:
                        break
                    continue

                if response.status_code >= 400:
                    logger.warning("OpenRouter API non-200 response (%s): status=%s body=%s", candidate_model, response.status_code, response.text[:200])
                    if raise_on_error and candidate_model == configured_model:
                        _raise_for_http_error(response, model=candidate_model, endpoint=url)
                    continue

                body = response.json()
                choices = body.get("choices")
                if not choices:
                    continue

                raw_content = str(choices[0].get("message", {}).get("content") or "").strip()
                cleaned = strip_thinking_and_reasoning(raw_content)
                if cleaned:
                    return cleaned

            except (LLMError, requests.HTTPError):
                if raise_on_error:
                    raise
            except Exception as exc:
                logger.warning("OpenRouter API attempt failed model=%s err=%s", candidate_model, exc)

    # 2. Try Gemini REST API if GEMINI_API_KEY is available
    if settings.gemini_api_key and not settings.gemini_api_key.startswith("sk-or-"):
        res = _call_gemini_rest(
            messages,
            settings.gemini_api_key,
            model=settings.llm_model,
            system=system,
            timeout=timeout,
        )
        if res:
            return res

    if raise_on_error:
        raise LLMError("LLM call failed")
    return None


@trace
def generate(
    prompt: str,
    *,
    system: str | None = None,
    timeout: int = 10,
    temperature: float = 0.7,
    max_tokens: int | None = None,
    raise_on_error: bool = False,
) -> str | None:
    """Single-turn helper used by welcome, RAG, and routing."""
    return chat(
        [{"role": "user", "content": prompt}],
        system=system,
        timeout=timeout,
        temperature=temperature,
        max_tokens=max_tokens,
        raise_on_error=raise_on_error,
    )


@trace
def generate_json(
    prompt: str,
    *,
    system: str | None = None,
    timeout: int = 8,
    raise_on_error: bool = False,
) -> dict[str, Any] | None:
    """Ask the model for a JSON object and parse the first object found."""
    text = generate(
        prompt + "\n\n" + get_prompt("llm.generate_json.response_suffix"),
        system=system or get_prompt("llm.generate_json.default_system"),
        timeout=timeout,
        temperature=0.2,
        max_tokens=300,
        raise_on_error=raise_on_error,
    )
    if not text:
        return None

    cleaned = strip_thinking_and_reasoning(text)
    match = re.search(r"\{.*\}", cleaned, re.DOTALL)
    if not match:
        logger.warning("LLM returned non-JSON payload: %s", cleaned[:300])
        return None

    try:
        return json.loads(match.group(0))
    except json.JSONDecodeError:
        logger.warning("LLM returned invalid JSON: %s", cleaned[:300])
        return None


@trace
def classify_conversation_route(message: str, session: dict) -> str | None:
    """Return TRANSACTION or KNOWLEDGE using strict JSON classification."""

    prompt = get_prompt(
        "llm.classify_conversation_route",
        session_mode=session.get("mode"),
        workflow_state=session.get("workflow_state"),
        message=message,
    )

    try:
        parsed = generate_json(
            prompt,
            system=get_prompt("llm.classify_conversation_route.system_json"),
            timeout=5,
        )
    except Exception as exc:
        logger.warning("Conversation route JSON classification failed: %s", exc)
        parsed = None
    if parsed:
        route = str(parsed.get("route", "")).strip().upper()
        if route in {"TRANSACTION", "KNOWLEDGE"}:
            return route

    # Legacy token fallback when JSON parsing fails
    try:
        result = generate(
            prompt,
            system=get_prompt("llm.classify_conversation_route.system_fallback"),
            timeout=5,
            temperature=0,
        )
    except Exception as exc:
        logger.warning("Conversation route fallback classification failed: %s", exc)
        return None
    if not result:
        return None
    normalized = strip_thinking_and_reasoning(result).strip().upper()
    if "TRANSACTION" in normalized:
        return "TRANSACTION"
    if "KNOWLEDGE" in normalized:
        return "KNOWLEDGE"
    return None
