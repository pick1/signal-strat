"""
Portfolio management for TRADING SIGNALS.

Stores and manages Robinhood portfolio context — current holdings, watchlist,
risk profile, and trading preferences. Used to personalize strategy generation.
"""

import json
from datetime import datetime, timezone
from pathlib import Path

from tinydb import TinyDB, Query

from trading_signals.config import PORTFOLIO_DB_PATH


def get_portfolio_db() -> TinyDB:
    """Return a singleton TinyDB instance for portfolio data."""
    return TinyDB(PORTFOLIO_DB_PATH)


# ─── Holdings ────────────────────────────────────────────────────────────────


def set_holdings(holdings: list[dict]) -> list[dict]:
    """Replace all holdings with a new list.

    Each holding: {
        "ticker": "AAPL",
        "shares": 10,
        "avg_cost": 150.00,
        "current_price": 155.00 (optional),
    }
    """
    db = get_portfolio_db()
    db.table("holdings").truncate()
    for h in holdings:
        h["updated_at"] = datetime.now(timezone.utc).isoformat()
        db.table("holdings").insert(h)
    return holdings


def get_holdings() -> list[dict]:
    """Get all current holdings."""
    db = get_portfolio_db()
    return db.table("holdings").all()


def add_holding(ticker: str, shares: int, avg_cost: float) -> dict:
    """Add a single holding."""
    db = get_portfolio_db()
    holding = {
        "ticker": ticker.upper(),
        "shares": shares,
        "avg_cost": avg_cost,
        "current_price": None,
        "updated_at": datetime.now(timezone.utc).isoformat(),
    }
    db.table("holdings").insert(holding)
    return holding


def remove_holding(ticker: str) -> bool:
    """Remove a holding by ticker."""
    db = get_portfolio_db()
    Holdings = Query()
    return bool(db.table("holdings").remove(Holdings.ticker == ticker.upper()))


# ─── Watchlist ───────────────────────────────────────────────────────────────


def set_watchlist(tickers: list[str]) -> list[str]:
    """Replace the watchlist."""
    cleaned = [t.upper().strip() for t in tickers if t.strip()]
    db = get_portfolio_db()
    db.table("watchlist").truncate()
    for t in cleaned:
        db.table("watchlist").insert({"ticker": t, "added_at": datetime.now(timezone.utc).isoformat()})
    return cleaned


def get_watchlist() -> list[str]:
    """Get watchlist tickers."""
    db = get_portfolio_db()
    return [w["ticker"] for w in db.table("watchlist").all()]


def add_to_watchlist(ticker: str) -> list[str]:
    """Add a ticker to the watchlist."""
    ticker = ticker.upper().strip()
    if not ticker:
        return get_watchlist()
    db = get_portfolio_db()
    Watchlist = Query()
    if not db.table("watchlist").get(Watchlist.ticker == ticker):
        db.table("watchlist").insert({"ticker": ticker, "added_at": datetime.now(timezone.utc).isoformat()})
    return get_watchlist()


def remove_from_watchlist(ticker: str) -> bool:
    """Remove a ticker from the watchlist."""
    db = get_portfolio_db()
    Watchlist = Query()
    return bool(db.table("watchlist").remove(Watchlist.ticker == ticker.upper()))


# ─── Risk Profile ────────────────────────────────────────────────────────────


def set_risk_profile(profile: dict) -> dict:
    """Set or update the trader's risk profile.

    profile: {
        "risk_tolerance": "conservative|moderate|aggressive",
        "max_position_size_pct": 25,  # max % of portfolio in one position
        "max_drawdown_pct": 15,
        "preferred_strategies": ["long", "swing", "call_option"],
        "account_value": 5000,
        "trading_style": "value|growth|momentum|income|blend",
        "experience_level": "beginner|intermediate|advanced",
    }
    """
    db = get_portfolio_db()
    profile["updated_at"] = datetime.now(timezone.utc).isoformat()
    db.table("profile").truncate()
    db.table("profile").insert(profile)
    return profile


def get_risk_profile() -> dict:
    """Get the current risk profile, or a default one."""
    db = get_portfolio_db()
    profiles = db.table("profile").all()
    if profiles:
        return profiles[0]
    return {
        "risk_tolerance": "moderate",
        "max_position_size_pct": 25,
        "max_drawdown_pct": 15,
        "preferred_strategies": ["long", "swing"],
        "account_value": 0,
        "trading_style": "growth",
        "experience_level": "intermediate",
    }


# ─── Portfolio Context String ───────────────────────────────────────────────


def build_portfolio_context() -> str:
    """Build a human-readable portfolio context string for LLM strategy generation."""
    holdings = get_holdings()
    watchlist = get_watchlist()
    profile = get_risk_profile()

    parts = [
        "=== PORTFOLIO CONTEXT ===",
        f"Risk Tolerance: {profile.get('risk_tolerance', 'moderate')}",
        f"Trading Style: {profile.get('trading_style', 'growth')}",
        f"Experience: {profile.get('experience_level', 'intermediate')}",
        f"Max Position Size: {profile.get('max_position_size_pct', 25)}%",
        f"Account Value: ${profile.get('account_value', 0):,.0f}",
        "",
    ]

    if holdings:
        parts.append("=== CURRENT HOLDINGS ===")
        for h in holdings:
            ticker = h.get("ticker", "?")
            shares = h.get("shares", 0)
            avg_cost = h.get("avg_cost", 0)
            parts.append(f"{ticker}: {shares} shares @ ${avg_cost:.2f}")
        parts.append("")

    if watchlist:
        parts.append("=== WATCHLIST ===")
        parts.append(", ".join(watchlist))
        parts.append("")

    parts.append(
        "Generate strategies appropriate for a retail trader with these holdings, "
        "risk constraints, and account size. Be realistic — no strategies requiring "
        "large capital, options approval beyond level 1, or complex multi-leg spreads "
        "unless the user's profile explicitly supports it."
    )

    return "\n".join(parts)
