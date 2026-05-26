"""LLM analysis for SIGNAL.

Supports Ollama (local) and OpenAI-compatible API providers with
content-type routing, model tiers, and automatic fallback.
"""

import json
import re

import ollama
import requests

from signald.config import (
    MODEL_TIERS,
    SOURCE_TIER,
    SYSTEM_PROMPT,
    OPENAI_BASE_URL,
    OPENAI_API_KEY,
    FALLBACK_ENABLED,
    OLLAMA_MODEL,
    ENRICHMENT_REQUESTS,
)

# Callback for UI notifications (injected by app.py if needed)
_notification_callback = None


def set_notification_callback(callback):
    """Register a callback for non-critical notifications (e.g., fallback warnings)."""
    global _notification_callback
    _notification_callback = callback


def _notify(msg: str, icon: str = "!"):
    if _notification_callback:
        _notification_callback(msg, icon)


# ─── Parsing ─────────────────────────────────────────────────────────────────


def parse_json_result(raw: str) -> dict:
    """Parse JSON from model output, stripping markdown fences."""
    clean = re.sub(r"```json|```", "", raw).strip()
    try:
        return json.loads(clean)
    except json.JSONDecodeError:
        match = re.search(r"\{.*\}", raw, re.DOTALL)
        if match:
            return json.loads(match.group())
        raise ValueError("Could not parse JSON from model output:\n" + raw[:500])


# ─── Prompt Building ─────────────────────────────────────────────────────────


def build_prompt(content: str, source_hint: str) -> tuple[str, str]:
    """Return (system_prompt, user_prompt)."""
    user_prompt = "Analyze this " + source_hint + ":\n\n---\n" + content[:6000] + "\n---"
    return SYSTEM_PROMPT, user_prompt


# ─── Ollama ─────────────────────────────────────────────────────────────────


def analyze_with_ollama(content: str, source_hint: str, model: str) -> dict:
    """Analyze content using a local Ollama model."""
    system_prompt, user_prompt = build_prompt(content, source_hint)
    try:
        response = ollama.chat(
            model=model,
            messages=[
                {"role": "system", "content": system_prompt},
                {"role": "user",   "content": user_prompt},
            ],
            options={"temperature": 0.3, "num_ctx": 8192},
        )
        raw = response["message"]["content"]
        return parse_json_result(raw)
    except Exception as e:
        raise ValueError(f"Ollama ({model}) failed: {e}")


# ─── OpenAI-Compatible API ────────────────────────────────────────────────────


def analyze_with_openai(content: str, source_hint: str, model: str) -> dict:
    """Analyze content using an OpenAI-compatible API."""
    system_prompt, user_prompt = build_prompt(content, source_hint)
    headers = {
        "Authorization": f"Bearer {OPENAI_API_KEY}",
        "Content-Type": "application/json",
    }
    payload = {
        "model": model,
        "messages": [
            {"role": "system", "content": system_prompt},
            {"role": "user",   "content": user_prompt},
        ],
        "temperature": 0.3,
        "max_tokens": 4096,
    }
    try:
        resp = requests.post(
            OPENAI_BASE_URL.rstrip("/") + "/chat/completions",
            headers=headers,
            json=payload,
            timeout=120,
        )
        resp.raise_for_status()
        raw = resp.json()["choices"][0]["message"]["content"]
        return parse_json_result(raw)
    except Exception as e:
        raise ValueError(f"OpenAI API ({model}) failed: {e}")


# ─── Model Selection ──────────────────────────────────────────────────────────


def pick_model(source_type: str, provider: str, tier_override: str | None = None) -> str:
    """Pick model based on source type, provider, and optional tier override."""
    if tier_override and tier_override != "auto":
        tier = tier_override
    else:
        tier = SOURCE_TIER.get(source_type, "default")

    model_map = MODEL_TIERS.get(tier, MODEL_TIERS["default"])
    return model_map.get(provider, model_map.get("ollama", OLLAMA_MODEL))


# ─── Dispatch ────────────────────────────────────────────────────────────────


def analyze_content(
    content: str,
    source_hint: str,
    provider: str,
    tier_override: str | None = None,
) -> dict:
    """Analyze content with the appropriate provider and fallback chain.

    Args:
        content: Text content to analyze.
        source_hint: Content type hint (url, article, tweet, instagram, etc.)
        provider: 'ollama' or 'openai'
        tier_override: Force a specific tier (light/default/deep), or None for auto.

    Returns:
        Parsed JSON dict with title, category, summary, verdict, etc.

    Raises:
        ValueError: If all providers fail.
    """
    model = pick_model(source_hint, provider, tier_override)

    if provider == "openai":
        if not OPENAI_API_KEY:
            raise ValueError("OpenAI API key not set (SIGNAL_OPENAI_API_KEY env var)")
        try:
            return analyze_with_openai(content, source_hint, model)
        except Exception as e:
            if FALLBACK_ENABLED:
                fallback_model = MODEL_TIERS["default"]["ollama"]
                _notify(f"OpenAI failed ({model}), falling back to Ollama ({fallback_model})", "W")
                return analyze_with_ollama(content, source_hint, fallback_model)
            raise
    else:
        # Ollama (default)
        try:
            result = analyze_with_ollama(content, source_hint, model)
        except Exception as e:
            if FALLBACK_ENABLED:
                fallback_model = MODEL_TIERS["default"]["openai"]
                if OPENAI_API_KEY:
                    _notify(f"Ollama failed ({model}), falling back to OpenAI ({fallback_model})", "W")
                    return analyze_with_openai(content, source_hint, fallback_model)
            raise
        return result


# ─── Enrichment Integration ──────────────────────────────────────────────────


def run_enrichment(content: str, analysis: dict) -> dict | None:
    """Post-analysis enrichment: extract entities, search for resources.

    Returns enrichment dict or None if enrichment is disabled or fails.
    """
    if not any(ENRICHMENT_REQUESTS.values()):
        return None
    try:
        from signald.enricher import enrich
        return enrich(content, analysis)
    except Exception as e:
        _notify(f"Enrichment failed: {e}", "W")
        return None
