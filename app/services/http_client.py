"""Shared HTTP client helpers for external API calls."""
from __future__ import annotations

from app.config import get_settings
from app.utils.trace import trace, trace_async


@trace
def requests_verify_setting() -> bool | str:
    """Return verify= value for requests: True, False, or a CA bundle path."""
    settings = get_settings()
    ca = getattr(settings, "http_ca_bundle", None)
    if ca:
        return ca
    return getattr(settings, "llm_verify_ssl", True)


@trace
def nominatim_verify_setting() -> bool | str:
    """Return verify= value for Nominatim requests."""
    settings = get_settings()
    ca = getattr(settings, "http_ca_bundle", None)
    if ca:
        return ca
    return getattr(settings, "nominatim_verify_ssl", True)
