"""
Trading Strategy Engine for TRADING SIGNALS.

Generates, stores, and manages trading strategies derived from financial analysis.
"""

import json
import time
from datetime import datetime, timezone
from typing import Any

from tinydb import TinyDB, Query

from trading_signals.config import (
    STRATEGIES_DB_PATH,
    STRATEGY_TYPES,
    RISK_LEVELS,
    TIME_HORIZONS,
)
from trading_signals.analyzer import generate_strategies


def get_strategies_db() -> TinyDB:
    """Return a singleton TinyDB instance for strategies."""
    return TinyDB(STRATEGIES_DB_PATH)


# ─── Strategy Lifecycle ──────────────────────────────────────────────────────


STATUS_OPTIONS = ["active", "entered", "monitoring", "closed_win", "closed_loss", "expired", "cancelled"]


def create_strategies(
    analysis: dict,
    portfolio_context: str | None = None,
    provider: str = "ollama",
) -> list[dict]:
    """Generate and save trading strategies from a financial analysis.

    Returns list of strategy dicts.
    """
    result = generate_strategies(analysis, portfolio_context, provider)
    raw_strategies = result.get("strategies", [])

    saved_strategies = []
    db = get_strategies_db()
    entry_id = analysis.get("id", str(int(time.time() * 1000)))

    for s in raw_strategies:
        strategy = {
            "id": f"strat_{int(time.time() * 1000)}_{len(saved_strategies)}",
            "entry_id": entry_id,
            "created_at": datetime.now(timezone.utc).isoformat(),
            "status": "active",
            "strategy_type": s.get("strategy_type", "no_trade"),
            "ticker": s.get("ticker", ""),
            "direction": s.get("direction", "neutral"),
            "entry_conditions": s.get("entry_conditions", ""),
            "suggested_entry": s.get("suggested_entry", ""),
            "stop_loss": s.get("stop_loss", ""),
            "take_profit": s.get("take_profit", ""),
            "time_horizon": s.get("time_horizon", "medium_1_3m"),
            "position_size": s.get("position_size", ""),
            "risk_level": s.get("risk_level", "medium"),
            "rationale": s.get("rationale", ""),
            "confidence": s.get("confidence", 0.5),
            "key_levels": s.get("key_levels", {"support": [], "resistance": []}),
            "confirmation_signals": s.get("confirmation_signals", []),
            "invalidation": s.get("invalidation", []),
            # Tracking
            "entry_price": None,
            "entry_date": None,
            "exit_price": None,
            "exit_date": None,
            "pnl_pct": None,
            "notes": "",
        }
        db.insert(strategy)
        saved_strategies.append(strategy)

    return saved_strategies


def load_strategies(entry_id: str | None = None, status: str | None = None) -> list[dict]:
    """Load strategies, optionally filtered by entry_id and/or status."""
    db = get_strategies_db()
    all_strats = db.all()
    all_strats.sort(key=lambda x: x.get("created_at", ""), reverse=True)

    if entry_id:
        all_strats = [s for s in all_strats if s.get("entry_id") == entry_id]
    if status:
        all_strats = [s for s in all_strats if s.get("status") == status]

    return all_strats


def update_strategy_status(
    strategy_id: str,
    status: str,
    entry_price: float | None = None,
    exit_price: float | None = None,
    notes: str = "",
) -> bool:
    """Update a strategy's status and optionally its entry/exit prices."""
    if status not in STATUS_OPTIONS:
        return False

    db = get_strategies_db()
    Strat = Query()
    strategy = db.get(Strat.id == strategy_id)
    if not strategy:
        return False

    update = {"status": status}
    if entry_price is not None:
        update["entry_price"] = entry_price
        update["entry_date"] = datetime.now(timezone.utc).isoformat()
    if exit_price is not None:
        update["exit_price"] = exit_price
        update["exit_date"] = datetime.now(timezone.utc).isoformat()
        # Calculate P&L if we have entry price
        if strategy.get("entry_price"):
            if strategy.get("direction") == "bullish":
                pnl = (exit_price - entry_price) / entry_price * 100
            else:
                pnl = (entry_price - exit_price) / entry_price * 100
            update["pnl_pct"] = round(pnl, 2)
    if notes:
        existing_notes = strategy.get("notes", "")
        update["notes"] = (existing_notes + "\n" + notes).strip()

    db.update(update, Strat.id == strategy_id)
    return True


def delete_strategy(strategy_id: str) -> bool:
    """Delete a strategy by ID."""
    db = get_strategies_db()
    Strat = Query()
    return bool(db.remove(Strat.id == strategy_id))


def get_strategy_stats() -> dict:
    """Return aggregate statistics about strategies."""
    db = get_strategies_db()
    all_strats = db.all()

    if not all_strats:
        return {"total": 0, "active": 0, "win_rate": 0, "total_pnl": 0}

    from collections import Counter

    status_counts = Counter(s.get("status", "unknown") for s in all_strats)
    risk_counts = Counter(s.get("risk_level", "unknown") for s in all_strats)
    type_counts = Counter(s.get("strategy_type", "unknown") for s in all_strats)

    closed = [s for s in all_strats if s.get("status") in ("closed_win", "closed_loss")]
    wins = sum(1 for s in closed if s.get("status") == "closed_win")
    losses = sum(1 for s in closed if s.get("status") == "closed_loss")
    win_rate = round(wins / len(closed) * 100, 1) if closed else 0

    pnls = [s.get("pnl_pct", 0) or 0 for s in closed]
    total_pnl = round(sum(pnls), 2) if pnls else 0

    return {
        "total": len(all_strats),
        "active": status_counts.get("active", 0),
        "entered": status_counts.get("entered", 0),
        "monitoring": status_counts.get("monitoring", 0),
        "closed_win": status_counts.get("closed_win", 0),
        "closed_loss": status_counts.get("closed_loss", 0),
        "win_rate": win_rate,
        "total_pnl_pct": total_pnl,
        "by_risk": dict(risk_counts),
        "by_type": dict(type_counts),
        "closed_count": len(closed),
    }


def format_strategy_for_display(strategy: dict) -> str:
    """Format a strategy as a readable string."""
    ticker = strategy.get("ticker", "")
    strat_type = strategy.get("strategy_type", "?")
    direction = strategy.get("direction", "neutral")
    confidence = strategy.get("confidence", 0)
    risk = strategy.get("risk_level", "medium")
    status = strategy.get("status", "active")

    lines = [
        f"{ticker} — {strat_type.upper()} ({direction})",
        f"Status: {status} | Confidence: {confidence:.0%} | Risk: {risk}",
        f"Entry: {strategy.get('suggested_entry', 'N/A')}",
    ]

    sl = strategy.get("stop_loss", "")
    tp = strategy.get("take_profit", "")
    if sl:
        lines.append(f"Stop Loss: {sl}")
    if tp:
        lines.append(f"Take Profit: {tp}")

    rationale = strategy.get("rationale", "")
    if rationale:
        lines.append(f"Rationale: {rationale}")

    pnl = strategy.get("pnl_pct")
    if pnl is not None:
        emoji = "✅" if pnl > 0 else "❌"
        lines.append(f"P&L: {emoji} {pnl:+.2f}%")

    return "\n".join(lines)
