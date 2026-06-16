#!/usr/bin/env python3
"""
TRADING SIGNALS — MCP Server
============================
Exposes the Trading Signals database as MCP tools/resources for external
AI agents (Hermes Agent, OpenCode, Claude Code, etc.).

Usage:
    python mcp_server.py                    # stdio transport
    python mcp_server.py --transport sse --port 8765  # HTTP/SSE
"""

import json
import sys
import argparse
from pathlib import Path
from datetime import datetime

from mcp.server.fastmcp import FastMCP

from trading_signals.db import load_entries, search_entries, get_db
from trading_signals.analyzer import analyze_content
from trading_signals.strategy_engine import (
    create_strategies,
    load_strategies,
    get_strategy_stats,
)
from trading_signals.portfolio import build_portfolio_context
from trading_signals.config import CAT_LABELS, CAT_COLORS

PROJECT_DIR = Path(__file__).parent.resolve()
DB_PATH = PROJECT_DIR / "data" / "trading_signals.json"

# ─── Server Setup ────────────────────────────────────────────────────────────
mcp = FastMCP("TRADING SIGNALS — Financial Intelligence & Strategy")


# ─── Tools ───────────────────────────────────────────────────────────────────


@mcp.tool()
def ts_list_entries(
    category: str = None,
    limit: int = 50,
    offset: int = 0,
) -> str:
    """List financial analysis entries with optional category filter.

    Args:
        category: Optional filter — 'bullish', 'bearish', 'neutral', 'catalyst', 'swing', 'macro', 'earnings'
        limit: Max entries to return (default 50)
        offset: Pagination offset
    """
    from tinydb import TinyDB
    db = TinyDB(DB_PATH)
    entries = db.all()
    entries.sort(key=lambda x: x.get("created_at", ""), reverse=True)

    if category:
        entries = [e for e in entries if e.get("category") == category]

    total = len(entries)
    entries = entries[offset : offset + limit]

    summarized = []
    for e in entries:
        summarized.append({
            "id": e.get("id"),
            "title": e.get("title", "Untitled"),
            "category": e.get("category", "unknown"),
            "tickers": e.get("tickers", []),
            "confidence": e.get("confidence", 0),
            "tags": e.get("tags", []),
            "date": e.get("created_at", "")[:10],
            "verdict": e.get("verdict", ""),
            "summary": e.get("summary", ""),
            "market_impact": e.get("market_impact", ""),
            "catalyst_date": e.get("catalyst_date", ""),
        })

    return json.dumps({"total": total, "returned": len(summarized), "entries": summarized}, indent=2)


@mcp.tool()
def ts_search_entries(query: str, limit: int = 20) -> str:
    """Search entries by keyword across title, summary, verdict, tags, and tickers.

    Args:
        query: Search keyword or ticker (case-insensitive)
        limit: Max results to return
    """
    from tinydb import TinyDB
    db = TinyDB(DB_PATH)
    q = query.lower()
    entries = db.all()
    entries.sort(key=lambda x: x.get("created_at", ""), reverse=True)

    matches = []
    for e in entries:
        if (
            q in e.get("title", "").lower()
            or q in e.get("summary", "").lower()
            or q in e.get("verdict", "").lower()
            or any(q in t.lower() for t in e.get("tags", []))
            or any(q in t.lower() for t in e.get("tickers", []))
            or q in e.get("market_impact", "").lower()
        ):
            matches.append({
                "id": e.get("id"),
                "title": e.get("title", "Untitled"),
                "category": e.get("category", "unknown"),
                "tickers": e.get("tickers", []),
                "tags": e.get("tags", []),
                "date": e.get("created_at", "")[:10],
                "verdict": e.get("verdict", ""),
            })

    return json.dumps({"query": query, "total_matches": len(matches), "entries": matches[:limit]}, indent=2)


@mcp.tool()
def ts_get_entry(entry_id: str) -> str:
    """Get a full entry by its unique ID.

    Args:
        entry_id: The entry's string ID (e.g. '1779601758639')
    """
    from tinydb import TinyDB, Query
    db = TinyDB(DB_PATH)
    Entry = Query()
    entry = db.get(Entry.id == entry_id)
    if not entry:
        return json.dumps({"error": f"Entry '{entry_id}' not found"})
    return json.dumps(entry, indent=2, default=str)


@mcp.tool()
def ts_get_stats() -> str:
    """Get summary statistics about the financial intelligence feed."""
    from tinydb import TinyDB
    db = TinyDB(DB_PATH)
    entries = db.all()

    categories = {}
    all_tickers = {}
    all_tags = []

    for e in entries:
        cat = e.get("category", "unknown")
        categories[cat] = categories.get(cat, 0) + 1

        for t in e.get("tickers", []):
            all_tickers[t] = all_tickers.get(t, 0) + 1

        all_tags.extend(e.get("tags", []))

    tag_freq = {}
    for t in all_tags:
        tag_freq[t] = tag_freq.get(t, 0) + 1
    top_tags = sorted(tag_freq.items(), key=lambda x: -x[1])[:20]
    top_tickers = sorted(all_tickers.items(), key=lambda x: -x[1])[:10]

    week_ago = datetime.now().timestamp() - 7 * 86400
    recent = sum(
        1 for e in entries
        if datetime.fromisoformat(e.get("created_at", "2000-01-01")).timestamp() > week_ago
    )

    result = {
        "total_entries": len(entries),
        "by_category": categories,
        "top_tickers": [{"ticker": t, "count": c} for t, c in top_tickers],
        "top_tags": [{"tag": t, "count": c} for t, c in top_tags],
        "entries_this_week": recent,
    }
    return json.dumps(result, indent=2)


@mcp.tool()
def ts_list_strategies(status: str = None, ticker: str = None) -> str:
    """List trading strategies with optional filters.

    Args:
        status: Filter by status — 'active', 'entered', 'closed_win', 'closed_loss', 'expired', 'cancelled'
        ticker: Filter by ticker symbol (e.g. 'AAPL')
    """
    strats = load_strategies()
    if status:
        strats = [s for s in strats if s.get("status") == status]
    if ticker:
        ticker = ticker.upper()
        strats = [s for s in strats if s.get("ticker", "").upper() == ticker]

    return json.dumps({
        "total": len(strats),
        "strategies": [
            {
                "id": s.get("id"),
                "ticker": s.get("ticker"),
                "strategy_type": s.get("strategy_type"),
                "direction": s.get("direction"),
                "status": s.get("status"),
                "confidence": s.get("confidence"),
                "risk_level": s.get("risk_level"),
                "entry_conditions": s.get("entry_conditions"),
                "suggested_entry": s.get("suggested_entry"),
                "stop_loss": s.get("stop_loss"),
                "take_profit": s.get("take_profit"),
                "time_horizon": s.get("time_horizon"),
                "rationale": s.get("rationale"),
                "pnl_pct": s.get("pnl_pct"),
                "created_at": s.get("created_at"),
            }
            for s in strats
        ]
    }, indent=2)


@mcp.tool()
def ts_get_strategy_stats() -> str:
    """Get aggregate statistics about trading strategy performance."""
    stats = get_strategy_stats()
    return json.dumps(stats, indent=2)


@mcp.tool()
def ts_analyze_and_generate(content: str, provider: str = "ollama") -> str:
    """Analyze financial content and generate trading strategies in one call.

    Args:
        content: Financial article text, URL, or news snippet
        provider: 'ollama' or 'openai' (default: ollama)
    """
    from trading_signals.scrapers import fetch_url_content, extract_tickers

    # Fetch if URL
    if content.startswith("http://") or content.startswith("https://"):
        fetched = fetch_url_content(content)
        content = fetched

    # Analyze
    result = analyze_content(content, "url", provider)

    # Extract tickers if missing
    if not result.get("tickers"):
        result["tickers"] = extract_tickers(content)[:5]

    # Save entry
    from trading_signals.db import save_entry
    entry = {
        "id": str(int(datetime.now().timestamp() * 1000)),
        "created_at": datetime.now().isoformat(),
        "source_type": "url" if content.startswith(("http://", "https://")) else "article",
        **result,
    }
    save_entry(entry)

    # Generate strategies
    portfolio_context = build_portfolio_context()
    strategies = create_strategies(entry, portfolio_context, provider)

    return json.dumps({
        "analysis": result,
        "strategies_generated": len(strategies),
        "strategies": strategies,
    }, indent=2, default=str)


# ─── Resources ───────────────────────────────────────────────────────────────


@mcp.resource("trading-signals://entries")
def get_all_entries() -> str:
    """All entries as a resource."""
    return ts_list_entries(limit=200)


@mcp.resource("trading-signals://stats")
def get_statistics() -> str:
    """Feed statistics as a resource."""
    return ts_get_stats()


@mcp.resource("trading-signals://strategies")
def get_all_strategies() -> str:
    """All strategies as a resource."""
    return ts_list_strategies()


# ─── Main ────────────────────────────────────────────────────────────────────


def main():
    parser = argparse.ArgumentParser(description="TRADING SIGNALS MCP Server")
    parser.add_argument(
        "--transport",
        choices=["stdio", "sse"],
        default="stdio",
        help="Transport protocol (default: stdio for MCP client integration)",
    )
    parser.add_argument(
        "--port", type=int, default=8765,
        help="Port for SSE transport (default: 8765)",
    )
    parser.add_argument(
        "--host", default="127.0.0.1",
        help="Host for SSE transport (default: 127.0.0.1)",
    )
    args = parser.parse_args()

    if args.transport == "sse":
        print(f"Starting TRADING SIGNALS MCP server on {args.host}:{args.port} (SSE)", file=sys.stderr)
        mcp.run(transport="sse", host=args.host, port=args.port)
    else:
        mcp.run(transport="stdio")


if __name__ == "__main__":
    main()
