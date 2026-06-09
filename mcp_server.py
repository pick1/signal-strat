#!/usr/bin/env python3
"""
SIGNAL — MCP Server
====================
Exposes the SIGNAL Tech Intelligence database as MCP tools/resources.

This lets any MCP client (Hermes Agent, OpenCode, Claude Code, etc.)
query the intelligence feed, search entries, get stats, and trigger
analysis — all via MCP tool calls.

Usage:
    # Run with stdio transport (for MCP client integration)
    python mcp_server.py

    # Run with SSE transport (for HTTP/StreamableHTTP clients)
    python mcp_server.py --transport sse --port 8765
"""

import json
import os
import sys
import argparse
from pathlib import Path
from datetime import datetime
from typing import Optional

from tinydb import TinyDB, Query
from mcp.server.fastmcp import FastMCP

from signald.db import load_entries, search_entries, get_stats, get_db
from signald.analyzer import analyze_content, run_enrichment, parse_json_result
from signald.config import MODEL_TIERS, SOURCE_TIER, CAT_LABELS, CAT_COLORS

PROJECT_DIR = Path(__file__).parent.resolve()
DB_PATH = PROJECT_DIR / "data" / "signal.json"

# ─── Server Setup ────────────────────────────────────────────────────────────
mcp = FastMCP("SIGNAL — Tech Intelligence Digest")


# ─── DB Helpers ──────────────────────────────────────────────────────────────
def _get_db() -> TinyDB:
    """Get a TinyDB instance (thread-safe reads)."""
    return TinyDB(DB_PATH)


# ─── Tools ───────────────────────────────────────────────────────────────────


@mcp.tool()
def signal_list_entries(
    category: str = None,
    limit: int = 50,
    offset: int = 0,
) -> str:
    """List analyzed intelligence entries with optional category filter.

    Args:
        category: Optional filter — 'viable', 'work', 'vaporware', 'redundant', 'watch', 'mixed'
        limit: Max entries to return (default 50)
        offset: Pagination offset
    """
    db = _get_db()
    entries = db.all()
    # Sort newest first
    entries.sort(key=lambda x: x.get("created_at", ""), reverse=True)

    if category:
        entries = [e for e in entries if e.get("category") == category]

    total = len(entries)
    entries = entries[offset : offset + limit]

    summarized = []
    for e in entries:
        summarized.append(
            {
                "id": e.get("id"),
                "title": e.get("title", "Untitled"),
                "category": e.get("category", "unknown"),
                "source_type": e.get("source_type", "unknown"),
                "confidence": e.get("confidence", 0),
                "tags": e.get("tags", []),
                "date": e.get("created_at", "")[:10],
                "verdict": e.get("verdict", ""),
                "summary": e.get("summary", ""),
            }
        )

    result = {"total": total, "returned": len(summarized), "entries": summarized}
    return json.dumps(result, indent=2)


@mcp.tool()
def signal_search_entries(query: str, limit: int = 20) -> str:
    """Search entries by keyword across title, summary, verdict, and tags.

    Args:
        query: Search keyword (case-insensitive)
        limit: Max results to return
    """
    db = _get_db()
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
            or q in e.get("implementability", "").lower()
            or q in e.get("work_relevance", "").lower()
            or q in e.get("opencode_fit", "").lower()
        ):
            matches.append(
                {
                    "id": e.get("id"),
                    "title": e.get("title", "Untitled"),
                    "category": e.get("category", "unknown"),
                    "tags": e.get("tags", []),
                    "date": e.get("created_at", "")[:10],
                    "verdict": e.get("verdict", ""),
                }
            )

    matches = matches[:limit]
    result = {"query": query, "total_matches": len(matches), "entries": matches}
    return json.dumps(result, indent=2)


@mcp.tool()
def signal_get_entry(entry_id: str) -> str:
    """Get a full entry by its unique ID.

    Args:
        entry_id: The entry's string ID (e.g. '1779601758639')
    """
    db = _get_db()
    Entry = Query()
    entry = db.get(Entry.id == entry_id)
    if not entry:
        return json.dumps({"error": f"Entry '{entry_id}' not found"})
    return json.dumps(entry, indent=2, default=str)


@mcp.tool()
def signal_get_stats() -> str:
    """Get summary statistics about the intelligence feed."""
    db = _get_db()
    entries = db.all()

    categories = {}
    source_types = {}
    all_tags = []

    for e in entries:
        cat = e.get("category", "unknown")
        categories[cat] = categories.get(cat, 0) + 1

        src = e.get("source_type", "unknown")
        source_types[src] = source_types.get(src, 0) + 1

        all_tags.extend(e.get("tags", []))

    # Tag frequency
    tag_freq = {}
    for t in all_tags:
        tag_freq[t] = tag_freq.get(t, 0) + 1
    top_tags = sorted(tag_freq.items(), key=lambda x: -x[1])[:20]

    # Recent activity (entries in last 7 days)
    week_ago = datetime.now().timestamp() - 7 * 86400
    recent = sum(
        1
        for e in entries
        if datetime.fromisoformat(e.get("created_at", "2000-01-01")).timestamp()
        > week_ago
    )

    result = {
        "total_entries": len(entries),
        "by_category": categories,
        "by_source_type": source_types,
        "top_tags": [{"tag": t, "count": c} for t, c in top_tags],
        "entries_this_week": recent,
    }
    return json.dumps(result, indent=2)


@mcp.tool()
def signal_export(format: str = "json") -> str:
    """Export all entries as JSON or Markdown.

    Args:
        format: 'json' or 'markdown'
    """
    db = _get_db()
    entries = db.all()
    entries.sort(key=lambda x: x.get("created_at", ""), reverse=True)

    if format == "json":
        return json.dumps(entries, indent=2, default=str)

    # Markdown export
    cat_labels = {
        "viable": "Viable",
        "work": "Work",
        "vaporware": "Vaporware",
        "redundant": "Redundant",
        "watch": "Watch",
        "mixed": "Mixed",
    }

    lines = [
        "# SIGNAL — Tech Intelligence Digest",
        f"_Exported {datetime.now().strftime('%Y-%m-%d')}_",
        "",
    ]

    for cat, label in sorted(cat_labels.items()):
        group = [e for e in entries if e.get("category") == cat]
        if not group:
            continue
        lines.append(f"## {label}")
        lines.append("")
        for e in group:
            steps = "\n".join(f"- {s}" for s in e.get("next_steps", []))
            lines.extend(
                [
                    f"### {e.get('title', 'Untitled')}",
                    f"**Tags:** {', '.join(e.get('tags', []))} | **Date:** {str(e.get('created_at', ''))[:10]}",
                    "",
                    e.get("summary", ""),
                    "",
                    f"**Implementability:** {e.get('implementability', '')}",
                    f"**Work Relevance:** {e.get('work_relevance', '')}",
                    f"**Verdict:** _{e.get('verdict', '')}_",
                    f"**Next Steps:**",
                    steps,
                    f"**OpenCode Fit:** {e.get('opencode_fit', '')}",
                    f"**Confidence:** {round(e.get('confidence', 0.8) * 100)}%",
                    "",
                    "---",
                    "",
                ]
            )

    return "\n".join(lines)


@mcp.tool()
def signal_enrich_entry(entry_id: str) -> str:
    """Run enrichment on an existing entry: extract entities, search GitHub,
    find related repos and resources, and synthesize research findings.

    Args:
        entry_id: The entry's string ID (e.g. '1779601758639')
    """
    db = _get_db()
    Entry = Query()
    entry = db.get(Entry.id == entry_id)
    if not entry:
        return json.dumps({"error": f"Entry '{entry_id}' not found"})

    # Get the raw content — stored content or summary
    content = entry.get("_raw_content", "")
    if not content:
        content = entry.get("summary", "") + "\n" + entry.get("verdict", "")

    result = run_enrichment(content, entry, "ollama")
    if result is None:
        return json.dumps({"error": "Enrichment failed or disabled"})

    # Save enrichment to the entry in DB
    entry["enrichment"] = result
    db.update(entry, Entry.id == entry_id)

    return json.dumps(result, indent=2, default=str)


# ─── Resources ───────────────────────────────────────────────────────────────


@mcp.resource("signal://entries")
def get_all_entries() -> str:
    """All entries as a resource."""
    return signal_list_entries(limit=200)


@mcp.resource("signal://stats")
def get_statistics() -> str:
    """Feed statistics as a resource."""
    return signal_get_stats()


# ─── Main ────────────────────────────────────────────────────────────────────


def main():
    parser = argparse.ArgumentParser(description="SIGNAL MCP Server")
    parser.add_argument(
        "--transport",
        choices=["stdio", "sse"],
        default="stdio",
        help="Transport protocol (default: stdio for MCP client integration)",
    )
    parser.add_argument(
        "--port",
        type=int,
        default=8765,
        help="Port for SSE transport (default: 8765)",
    )
    parser.add_argument(
        "--host",
        default="127.0.0.1",
        help="Host for SSE transport (default: 127.0.0.1)",
    )
    args = parser.parse_args()

    if args.transport == "sse":
        print(
            f"Starting SIGNAL MCP server on {args.host}:{args.port} (SSE)",
            file=sys.stderr,
        )
        mcp.run(transport="sse", host=args.host, port=args.port)
    else:
        # Stdio transport — used by Hermes/OpenCode MCP client integration
        mcp.run(transport="stdio")


if __name__ == "__main__":
    main()
