"""
LLM provider layer for Receipts.

Primary provider (Power rule): Meterless Nightshift, an OpenAI-compatible
endpoint. Configuration comes from the environment:

    METERLESS_BASE_URL        e.g. http://127.0.0.1:8088/v1
                              (default http://127.0.0.1:8088/v1, but the
                              provider only activates when the variable is
                              explicitly set, so existing deployments keep
                              using Gemini until Nightshift is configured)
    METERLESS_RUNTIME_TOKEN   bearer token for the runtime
    METERLESS_MODEL           default "meterless/auto"

Every request carries "Authorization: Bearer <token>" and the header
"meterless-app: receipts". If Nightshift is not configured, or a call to
it fails, generation falls back to the existing Gemini path so the app
keeps working in sample mode with no live provider credentials.
"""

import json
import os
from typing import Any, Callable, List, Optional

import httpx

DEFAULT_BASE_URL = "http://127.0.0.1:8088/v1"
APP_HEADER_VALUE = "receipts"


def meterless_base_url() -> Optional[str]:
    """Return the configured Nightshift base URL, or None if unset."""
    url = os.environ.get("METERLESS_BASE_URL", "").strip()
    return url.rstrip("/") if url else None


def meterless_configured() -> bool:
    return meterless_base_url() is not None


def meterless_model() -> str:
    return os.environ.get("METERLESS_MODEL", "meterless/auto")


def _headers() -> dict:
    token = os.environ.get("METERLESS_RUNTIME_TOKEN", "")
    return {
        "Authorization": f"Bearer {token}",
        "meterless-app": APP_HEADER_VALUE,
        "Content-Type": "application/json",
    }


def _clean_json(text: str) -> Any:
    cleaned = text.strip()
    if cleaned.startswith("```"):
        cleaned = cleaned.strip("`")
        if cleaned.startswith("json"):
            cleaned = cleaned[4:].strip()
    return json.loads(cleaned)


def meterless_generate_json(
    prompt: str,
    timeout_sec: float = 25.0,
    transport: Optional[httpx.BaseTransport] = None,
) -> Any:
    """One JSON-mode chat completion against Nightshift.

    Raises on any transport or HTTP error so callers can fall back.
    ``transport`` is injectable for offline unit tests.
    """
    base = meterless_base_url() or DEFAULT_BASE_URL
    payload = {
        "model": meterless_model(),
        "messages": [{"role": "user", "content": prompt}],
        "response_format": {"type": "json_object"},
    }
    with httpx.Client(timeout=timeout_sec, transport=transport) as client:
        resp = client.post(
            f"{base}/chat/completions", headers=_headers(), json=payload
        )
        resp.raise_for_status()
        data = resp.json()
    content = data["choices"][0]["message"]["content"]
    return _clean_json(content)


def discover_models(
    timeout_sec: float = 5.0,
    transport: Optional[httpx.BaseTransport] = None,
) -> List[str]:
    """GET /v1/models on the Nightshift endpoint; returns model ids."""
    base = meterless_base_url() or DEFAULT_BASE_URL
    with httpx.Client(timeout=timeout_sec, transport=transport) as client:
        resp = client.get(f"{base}/models", headers=_headers())
        resp.raise_for_status()
        data = resp.json()
    return [m.get("id", "") for m in data.get("data", [])]


async def generate_json(
    prompt: str,
    gemini_caller: Callable[[str, float], Any],
    timeout_sec: float = 25.0,
    transport: Optional[httpx.BaseTransport] = None,
) -> Any:
    """Route a JSON generation request.

    Nightshift first when configured; Gemini on any Nightshift failure
    or when Nightshift is not configured. ``gemini_caller`` is an async
    callable (prompt, timeout_sec) supplied by app.py so this module
    stays free of Gemini imports.
    """
    if meterless_configured():
        try:
            import asyncio

            return await asyncio.to_thread(
                meterless_generate_json, prompt, timeout_sec, transport
            )
        except Exception as exc:
            print(f"[Provider Warning] Nightshift failed, falling back to Gemini: {exc}")
    return await gemini_caller(prompt, timeout_sec)
