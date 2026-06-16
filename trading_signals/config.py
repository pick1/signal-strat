"""
Configuration constants for TRADING SIGNALS.
"""

import os
import re
from pathlib import Path

# ─── Paths ───────────────────────────────────────────────────────────────────
PROJECT_DIR = Path(__file__).resolve().parent.parent
DB_PATH = PROJECT_DIR / "data" / "trading_signals.json"
DB_PATH.parent.mkdir(exist_ok=True)

PASSWORD_FILE = PROJECT_DIR / "data" / ".password_hash"

PORTFOLIO_DB_PATH = PROJECT_DIR / "data" / "portfolio.json"
STRATEGIES_DB_PATH = PROJECT_DIR / "data" / "strategies.json"


# ─── Default Models ──────────────────────────────────────────────────────────
OLLAMA_MODEL = "qwen3:14b"

# ─── Multi-Model Config ──────────────────────────────────────────────────────
MODEL_TIERS = {
    "light":   {"ollama": "qwen3:latest",       "openai": "deepseek-v4-flash-free"},
    "default": {"ollama": "gemma4:e4b",         "openai": "deepseek-v4-flash-free"},
    "deep":    {"ollama": "deepseek-r1:14b",    "openai": "nemotron-3-super-free"},
}

SOURCE_TIER = {
    "url":        "default",
    "article":    "default",
    "newsletter": "default",
    "note":       "default",
    "tweet":      "light",
}

# ─── Provider Config ─────────────────────────────────────────────────────────
API_PROVIDER = os.getenv("TRADING_API_PROVIDER", "ollama")
OPENAI_BASE_URL = os.getenv("TRADING_OPENAI_BASE_URL", "https://opencode.ai/zen/v1")
OPENAI_API_KEY = os.getenv("TRADING_OPENAI_API_KEY", "")
OPENAI_MODEL = os.getenv("TRADING_OPENAI_MODEL", "deepseek-v4-flash-free")
FALLBACK_ENABLED = os.getenv("TRADING_FALLBACK_ENABLED", "true").lower() == "true"

# ─── Enrichment ───────────────────────────────────────────────────────────────
ENRICHMENT_REQUESTS = {
    "github": False,  # Tech-focused, less relevant for finance
    "links": True,
}

# ─── Regex Patterns ──────────────────────────────────────────────────────────
TICKER_RE = re.compile(r'\b[A-Z]{1,5}\b')
YAHOO_FINANCE_RE = re.compile(r'(?:finance\.yahoo|yahoo\.com/news)')
SEC_RE = re.compile(r'(?:sec\.gov|edgar)')
MARKETWATCH_RE = re.compile(r'marketwatch')
BENZINGA_RE = re.compile(r'benzinga')
SEEKING_ALPHA_RE = re.compile(r'seekingalpha')
BLOOMBERG_RE = re.compile(r'(?:bloomberg|bloomberg\.com)')
REUTERS_RE = re.compile(r'reuters')
CNBC_RE = re.compile(r'cnbc')
MOTLEY_FOOL_RE = re.compile(r'fool\.com')

# ─── Trading Categories ──────────────────────────────────────────────────────
CAT_COLORS = {
    "bullish":    "#00ff88",
    "bearish":    "#ff4466",
    "neutral":    "#8888aa",
    "catalyst":   "#aa66ff",
    "swing":      "#4488ff",
    "macro":      "#ffaa00",
    "earnings":   "#44ddff",
}

CAT_LABELS = {
    "bullish":    "Bullish",
    "bearish":    "Bearish",
    "neutral":    "Neutral",
    "catalyst":   "Catalyst",
    "swing":      "Swing Trade",
    "macro":      "Macro",
    "earnings":   "Earnings Play",
}

CAT_DESCRIPTIONS = {
    "bullish":  "Positive sentiment — stock likely to appreciate",
    "bearish":  "Negative sentiment — stock likely to decline",
    "neutral":  "Balanced or uncertain — no clear directional bias",
    "catalyst": "Upcoming event could move the stock (product launch, FDA, etc.)",
    "swing":    "Short-to-medium term momentum play (days to weeks)",
    "macro":    "Macroeconomic trend affecting multiple sectors",
    "earnings": "Pre/post earnings report analysis",
}

STRATEGY_TYPES = [
    "long",
    "short",
    "swing",
    "call_option",
    "put_option",
    "covered_call",
    "cash_secured_put",
    "spread",
    "hold",
    "no_trade",
]

RISK_LEVELS = ["low", "medium", "high"]

TIME_HORIZONS = ["intraday", "swing_1_3d", "swing_1_2w", "medium_1_3m", "long_6m_plus"]

# ─── LLM System Prompt — Financial Analysis ───────────────────────────────────
SYSTEM_PROMPT = """You are a senior financial analyst and trader with 15 years of experience analyzing markets, earnings reports, SEC filings, macroeconomic data, and financial news. Your job is to analyze financial content submitted by an individual trader and produce a structured intelligence report.

Your analysis must be HONEST, OPINIONATED, and FINANCIALLY PRECISE. Avoid hype. Identify pump-and-dump signals clearly. Be skeptical of press releases.

The person you are analyzing for is a retail trader using Robinhood who builds trading strategies based on financial news and data. Tailor your analysis to actionable trading insights for a retail trader with moderate capital.

Return ONLY valid JSON — no markdown, no backticks, no explanation outside the JSON. Schema:
{
  "title": "Short punchy title (max 10 words). Include the ticker symbol if one is mentioned.",
  "tickers": ["List of stock/crypto ticker symbols mentioned, max 5"],
  "category": "bullish|bearish|neutral|catalyst|swing|macro|earnings",
  "tags": ["2 to 5 topic tags: sector, theme, ticker"],
  "summary": "2-3 sentence plain-language summary of the financial news and its market implications.",
  "market_impact": "1-2 sentences: Expected impact on the stock(s) or sector. Include price direction and magnitude if estimable.",
  "key_metrics": ["List 1-3 specific financial metrics mentioned (revenue, EPS, P/E, growth rate, debt, etc.)"],
  "verdict": "Your blunt 1-2 sentence trading take. Call it like you see it. Is this a real opportunity or noise?",
  "confidence": 0.85,
  "next_steps": ["2 to 4 concrete actionable next steps: what to watch, when to enter, what confirms or invalidates the thesis"],
  "catalyst_date": "YYYY-MM-DD or null if no specific catalyst date known"
}

Categories:
- bullish: Positive sentiment, strong fundamentals or catalysts — likely to appreciate
- bearish: Negative sentiment, deteriorating fundamentals, overvaluation — likely to decline
- neutral: Balanced or uncertain, no clear directional bias, conflicting signals
- catalyst: Specific upcoming event (earnings, FDA decision, product launch, macro data) that could move the stock
- swing: Short-to-medium term momentum play driven by technicals or news (days to weeks)
- macro: Macroeconomic trend, sector rotation, interest rate, or regulatory change affecting many tickers
- earnings: Pre-earnings analysis, earnings beat/miss reaction, post-earnings drift

Rules:
- If tickers are mentioned, include the exact ticker symbol as found
- If no specific company is mentioned, use "null" for tickers and "macro" or "neutral" for category
- Confidence varies based on information quality: High conviction=0.90-0.95, Medium=0.75-0.89, Low=0.50-0.74
- catalyst_date should be specific when a date is mentioned in the article
"""

# ─── Strategy Generation Prompt ──────────────────────────────────────────────
STRATEGY_PROMPT = """You are an experienced trading strategist. Given a financial analysis report and the trader's portfolio context, generate actionable trading strategies.

The trader uses Robinhood and has moderate capital. Generate strategies that are realistic for a retail trader.

Return ONLY valid JSON — no markdown, no backticks. Schema:
{
  "strategies": [
    {
      "strategy_type": "long|short|swing|call_option|put_option|covered_call|cash_secured_put|spread|hold|no_trade",
      "ticker": "TICKER",
      "direction": "bullish|bearish|neutral",
      "entry_conditions": "Conditions for entry — price range, technical indicators, or timing",
      "suggested_entry": "Specific entry suggestion: market order, limit price $XX.XX, or wait for pullback to $XX.XX",
      "stop_loss": "Stop loss level and rationale, or 'none'",
      "take_profit": "Take profit targets (1-2 levels), or 'none'",
      "time_horizon": "intraday|swing_1_3d|swing_1_2w|medium_1_3m|long_6m_plus",
      "position_size": "Suggested position size as % of portfolio (10%, 25%, 50%, etc.)",
      "risk_level": "low|medium|high",
      "rationale": "2-3 sentences explaining why this strategy makes sense",
      "confidence": 0.85,
      "key_levels": {
        "support": ["price level 1", "price level 2"],
        "resistance": ["price level 1", "price level 2"]
      },
      "confirmation_signals": ["What needs to happen for this to work"],
      "invalidation": ["What would invalidate this thesis"]
    }
  ]
}

Rules:
- Generate 1-3 strategies per analysis
- Be conservative — capital preservation first
- If there isn't a clear actionable opportunity, return "no_trade" strategy type with rationale
- Position size should reflect risk level: high risk <= 10%, medium <= 25%, low <= 50%
- Stop losses are mandatory for directional trades (long/short/swing)
- Option strategies require specific expiration reasoning
"""

# ─── Market data ─────────────────────────────────────────────────────────────
MARKET_DATA_SOURCES = {
    "yahoo_finance": True,
    "polygon": False,
}
POLYGON_API_KEY = os.getenv("POLYGON_API_KEY", "")

# ─── Robinhood config ───────────────────────────────────────────────────────
ROBINHOOD_USERNAME = os.getenv("ROBINHOOD_USERNAME", "")
ROBINHOOD_PASSWORD = os.getenv("ROBINHOOD_PASSWORD", "")
ROBINHOOD_MFA_CODE = os.getenv("ROBINHOOD_MFA_CODE", "")
