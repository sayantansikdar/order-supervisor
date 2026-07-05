"""Thin LLM wrapper.

Returns parsed JSON from the model when an ANTHROPIC_API_KEY is configured,
otherwise callers fall back to the deterministic mock policy. Kept isolated so
the rest of the system never imports the SDK directly.
"""
import json
import re
from typing import Optional

from ..config import get_settings


def llm_available() -> bool:
    return get_settings().llm_enabled


async def complete_json(system: str, user: str, max_tokens: int = 1200) -> Optional[dict]:
    """Call Claude and parse a JSON object from the response.

    Returns None on any failure so the caller can fall back to the mock policy.
    """
    settings = get_settings()
    if not settings.llm_enabled:
        return None
    try:
        from anthropic import AsyncAnthropic

        client = AsyncAnthropic(api_key=settings.anthropic_api_key)
        # Prompt caching on the (stable) system block keeps repeated turns cheap.
        resp = await client.messages.create(
            model=settings.llm_model,
            max_tokens=max_tokens,
            system=[{"type": "text", "text": system, "cache_control": {"type": "ephemeral"}}],
            messages=[{"role": "user", "content": user}],
        )
        text = "".join(block.text for block in resp.content if block.type == "text")
        return _extract_json(text)
    except Exception as exc:  # noqa: BLE001 - POC: degrade gracefully to mock
        print(f"[llm] falling back to mock policy: {exc}")
        return None


def _extract_json(text: str) -> Optional[dict]:
    text = text.strip()
    # Strip ```json fences if present
    fence = re.search(r"```(?:json)?\s*(\{.*\})\s*```", text, re.DOTALL)
    if fence:
        text = fence.group(1)
    start = text.find("{")
    end = text.rfind("}")
    if start == -1 or end == -1:
        return None
    try:
        return json.loads(text[start : end + 1])
    except json.JSONDecodeError:
        return None
