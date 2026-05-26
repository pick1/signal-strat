"""Configuration constants for SIGNAL."""

import os
import re
from pathlib import Path

# ─── Paths ───────────────────────────────────────────────────────────────────
PROJECT_DIR = Path(__file__).resolve().parent.parent
DB_PATH = PROJECT_DIR / "data" / "signal.json"
DB_PATH.parent.mkdir(exist_ok=True)

PASSWORD_FILE = PROJECT_DIR / "data" / ".password_hash"

# ─── Default Models ──────────────────────────────────────────────────────────
OLLAMA_MODEL = "qwen3:14b"

# ─── Multi-Model Config ──────────────────────────────────────────────────────
MODEL_TIERS = {
    "light":   {"ollama": "qwen3:latest",       "openai": "deepseek-v4-flash-free"},
    "default": {"ollama": "gemma4:e4b",         "openai": "deepseek-v4-flash-free"},
    "deep":    {"ollama": "deepseek-r1:14b",    "openai": "nemotron-3-super-free"},
}

SOURCE_TIER = {
    "tweet":      "light",
    "instagram":  "light",
    "url":        "default",
    "article":    "default",
    "newsletter": "default",
    "note":       "default",
}

# ─── Provider Config ─────────────────────────────────────────────────────────
API_PROVIDER = os.getenv("SIGNAL_API_PROVIDER", "ollama")
OPENAI_BASE_URL = os.getenv("SIGNAL_OPENAI_BASE_URL", "https://opencode.ai/zen/v1")
OPENAI_API_KEY = os.getenv("SIGNAL_OPENAI_API_KEY", "")
OPENAI_MODEL = os.getenv("SIGNAL_OPENAI_MODEL", "deepseek-v4-flash-free")
FALLBACK_ENABLED = os.getenv("SIGNAL_FALLBACK_ENABLED", "true").lower() == "true"

# ─── Enrichment ───────────────────────────────────────────────────────────────
ENRICHMENT_REQUESTS = {
    "github": True,
    "links": True,
    "wikipedia": False,
}

# ─── Regex Patterns ──────────────────────────────────────────────────────────
INSTAGRAM_RE = re.compile(
    r'https?://(?:www\.)?(?:instagram\.com|instagr\.am)/'
    r'(?:p|reel|tv)/([A-Za-z0-9_\-]+)'
)
GITHUB_REPO_RE = re.compile(r'github\.com/([A-Za-z0-9_.-]+)/([A-Za-z0-9_.-]+)')

# ─── Category Colors & Labels ────────────────────────────────────────────────
CAT_COLORS = {
    "viable":    "#00ff88",
    "work":      "#4488ff",
    "vaporware": "#ff4466",
    "redundant": "#ffaa00",
    "watch":     "#aa66ff",
    "mixed":     "#88ddff",
}

CAT_LABELS = {
    "viable":    "Viable",
    "work":      "Work",
    "vaporware": "Vaporware",
    "redundant": "Redundant",
    "watch":     "Watch",
    "mixed":     "Mixed",
}

# ─── LLM System Prompt ─────────────────────────────────────────────────────────
SYSTEM_PROMPT = """You are a senior technology analyst and engineer with 20 years of experience evaluating emerging tech, tools, frameworks, products, and industry trends. Your job is to analyze content submitted by a tech professional and produce a structured intelligence report.

Your analysis must be HONEST, OPINIONATED, and TECHNICALLY PRECISE. Avoid hype. Identify BS clearly.

The person you are analyzing for uses OpenCode as their AI coding assistant, runs local LLMs via Ollama (Qwen3:14b, DeepSeek-R1), self-hosts apps on Ubuntu Linux, and is actively building and extending their local AI stack. Tailor next_steps and opencode_fit to this specific context.

Return ONLY valid JSON — no markdown, no backticks, no explanation outside the JSON. Schema:
{
  "title": "Short punchy title for this entry (max 10 words). Include the exact tool/product name if one is featured.",
  "source_type": "article|instagram|url|tweet|newsletter|note|unknown",
  "category": "viable|work|vaporware|redundant|watch|mixed",
  "tags": ["2 to 5 topic tags. Include the tool/product name as a tag if applicable."],
  "summary": "2-3 sentence plain-language summary of what this is actually about. Identify the specific tool or product by name.",
  "implementability": "1-2 sentences: Can this be built/used today? What would it take?",
  "work_relevance": "1-2 sentences: Is this relevant to a professional engineering or product context?",
  "verdict": "Your blunt 1-2 sentence take. No hedging. Call it like you see it.",
  "confidence": 0.85,
  "next_steps": ["2 to 4 concrete actionable next steps to evaluate or implement this technology"],
  "opencode_fit": "1-2 sentences on how this fits into an OpenCode + local Ollama workflow. Be specific about MCP servers, model routing, tooling integrations, or say not applicable."
}

Categories:
- viable: Real technology that exists and can be implemented now
- work: Directly useful for professional/enterprise engineering contexts
- vaporware: Announced but does not exist or likely will not ship as promised
- redundant: Already solved by existing tools, nothing new here
- watch: Interesting but not ready, worth monitoring
- mixed: Multiple categories apply"""
