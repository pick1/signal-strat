#!/usr/bin/env python3
"""
SIGNAL — RSS/Atom Feed Ingester
=================================
Fetches configured RSS/Atom feeds, detects new entries, and optionally
analyzes them through the SIGNAL pipeline.

Usage:
    # Show feeds and check for new items (no analysis)
    python scripts/rss_ingester.py check

    # Fetch and auto-analyze new items, saving to SIGNAL database
    python scripts/rss_ingester.py ingest --analyze

    # List recent items from feeds
    python scripts/rss_ingester.py list
"""

import os
import sys
import time
import argparse
import json
import hashlib
from pathlib import Path
from datetime import datetime
from typing import Optional

# Add project root to path for signald package imports
_PROJECT_ROOT = Path(__file__).resolve().parent.parent
if str(_PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(_PROJECT_ROOT))

import feedparser
import requests

from signald.config import PROJECT_DIR, DB_PATH
from signald.db import save_entry
from signald.analyzer import analyze_content, run_enrichment

DATA_DIR = PROJECT_DIR / "data"
FEEDS_CONFIG = DATA_DIR / "rss_feeds.json"
SEEN_FILE = DATA_DIR / "rss_seen.json"

# Default feeds config template
DEFAULT_FEEDS = {
    "_note": "Add RSS/Atom feed URLs here. You can also add category hints.",
    "feeds": [
        {
            "url": "https://hnrss.org/frontpage",
            "name": "Hacker News",
            "category_hint": "url",
            "enabled": False,
        },
        {
            "url": "https://lobste.rs/rss",
            "name": "Lobsters",
            "category_hint": "url",
            "enabled": False,
        },
    ],
}


# ─── Helpers ─────────────────────────────────────────────────────────────────


def _ensure_file(path: Path, default_content=None):
    """Create file with default content if it doesn't exist."""
    if not path.exists():
        if default_content is not None:
            path.write_text(
                json.dumps(default_content, indent=2) if isinstance(default_content, (dict, list))
                else str(default_content)
            )
        else:
            path.touch()
        print(f"Created {path}")


def load_feeds() -> list[dict]:
    """Load enabled feeds from config."""
    if not FEEDS_CONFIG.exists():
        _ensure_file(FEEDS_CONFIG, DEFAULT_FEEDS)
        print(f"Edit {FEEDS_CONFIG} to add your feeds, then re-run.")
        sys.exit(0)

    config = json.loads(FEEDS_CONFIG.read_text())
    feeds = [f for f in config.get("feeds", []) if f.get("enabled", True)]
    return feeds


def load_seen() -> dict:
    """Load the set of seen entry links."""
    if not SEEN_FILE.exists():
        return {}
    return json.loads(SEEN_FILE.read_text())


def save_seen(seen: dict):
    SEEN_FILE.write_text(json.dumps(seen, indent=2, default=str))


def entry_id(link: str, title: str) -> str:
    """Deterministic unique ID for a feed entry."""
    raw = f"{link}|{title}"
    return hashlib.sha256(raw.encode()).hexdigest()[:16]


# ─── Feed Fetching ───────────────────────────────────────────────────────────


def fetch_feed(feed_cfg: dict) -> list[dict]:
    """Fetch and parse a feed. Returns list of entry dicts."""
    url = feed_cfg["url"]
    name = feed_cfg.get("name", url)
    hint = feed_cfg.get("category_hint", "url")

    print(f"  Fetching {name}...", end=" ")
    try:
        parsed = feedparser.parse(url)
        if parsed.bozo and not parsed.entries:
            print(f"ERROR: {parsed.bozo_exception}")
            return []
    except Exception as e:
        print(f"ERROR: {e}")
        return []

    entries = []
    for entry in parsed.entries[:20]:  # Max 20 per feed per check
        link = entry.get("link", "")
        title = entry.get("title", "Untitled")
        published = entry.get("published", "")
        summary = entry.get("summary", "")[:500]

        entries.append({
            "feed_name": name,
            "feed_url": url,
            "title": title,
            "url": link,
            "published": published,
            "summary": summary,
            "source_hint": hint,
        })

    print(f"{len(entries)} entries")
    return entries


def fetch_content_for_analysis(entry: dict) -> str:
    """Fetch full article content for analysis."""
    url = entry.get("url", "")
    if not url:
        return entry.get("summary", "")

    try:
        from trafilatura import fetch_url, extract
        downloaded = fetch_url(url)
        if downloaded:
            text = extract(downloaded, include_comments=False, include_tables=True)
            if text and len(text) > 200:
                return text
        # Fallback
        headers = {"User-Agent": "Mozilla/5.0 (compatible; SIGNALBot/1.0)"}
        resp = requests.get(url, headers=headers, timeout=10)
        resp.raise_for_status()
        from bs4 import BeautifulSoup
        soup = BeautifulSoup(resp.text, "lxml")
        for tag in soup(["script", "style", "nav", "footer", "aside"]):
            tag.decompose()
        return soup.get_text(separator="\n", strip=True)[:8000]
    except Exception as e:
        return entry.get("summary", f"[Could not fetch: {e}]")


# ─── Analysis ────────────────────────────────────────────────────────────────


def analyze_entry(
    content: str,
    source_hint: str,
    provider: str = "ollama",
    tier_override: str = None,
) -> Optional[dict]:
    """Run through SIGNAL's analysis pipeline."""
    try:
        result = analyze_content(content, source_hint, provider, tier_override)
        return result
    except Exception as e:
        print(f"    Analysis failed: {e}")
        return None


def save_to_db(entry: dict, analysis: dict, enrichment: dict = None, repo_data: list = None):
    """Save analyzed entry to SIGNAL TinyDB database."""
    db_entry = {
        "id": str(int(time.time() * 1000)),
        "created_at": datetime.now().isoformat(),
        "raw_url": entry.get("url"),
        "source_type": entry.get("source_hint", "url"),
        "repos": repo_data or [],
        **analysis,
        "enrichment": enrichment or {},
    }
    save_entry(db_entry)
    print(f"    Saved: {analysis.get('title', 'Untitled')}")


# ─── Commands ────────────────────────────────────────────────────────────────


def cmd_check():
    """Check feeds for new items without analyzing."""
    feeds = load_feeds()
    seen = load_seen()
    print(f"Checking {len(feeds)} feeds...\n")

    total_new = 0
    for feed_cfg in feeds:
        entries = fetch_feed(feed_cfg)
        for entry in entries:
            eid = entry_id(entry["url"], entry["title"])
            if eid not in seen:
                total_new += 1
                pub = entry.get("published", "")[:16]
                print(f"  [NEW] {entry['title']}")
                print(f"        {entry['url']}  ({pub})")

    print(f"\n{total_new} new items found")
    return total_new


def cmd_ingest(analyze: bool = False, provider: str = "ollama", enrich: bool = False):
    """Fetch feeds and optionally analyze new entries."""
    feeds = load_feeds()
    seen = load_seen()
    print(f"Ingesting {len(feeds)} feeds...\n")

    new_count = 0
    for feed_cfg in feeds:
        entries = fetch_feed(feed_cfg)
        for entry in entries:
            eid = entry_id(entry["url"], entry["title"])
            if eid in seen:
                continue

            seen[eid] = {
                "title": entry["title"],
                "url": entry["url"],
                "found_at": datetime.now().isoformat(),
            }
            new_count += 1

            print(f"\n  >>> {entry['title']}")
            print(f"      {entry['url']}")

            if analyze:
                print(f"      Fetching content...", end=" ")
                content = fetch_content_for_analysis(entry)
                print(f"{len(content)} chars")

                print(f"      Analyzing...", end=" ")
                result = analyze_entry(content, entry["source_hint"], provider)
                if result:
                    enrichment = None
                    if enrich:
                        print(f"      Enriching...", end=" ")
                        enrichment = run_enrichment(content, result)
                        print(f"done")
                    save_to_db(entry, result, enrichment=enrichment)
                else:
                    print(f"      SKIPPED (analysis failed)")

    save_seen(seen)
    print(f"\nDone. {new_count} new items processed.")
    return new_count


def cmd_list():
    """List recent items from feeds."""
    feeds = load_feeds()
    print(f"Feed sources ({len(feeds)} enabled):\n")
    for f in feeds:
        print(f"  {f.get('name', f['url'])}")
        print(f"    {f['url']}")
        print()

    seen = load_seen()
    if seen:
        print(f"Tracked entries: {len(seen)}")
        # Show last 10 by found_at
        sorted_items = sorted(seen.items(), key=lambda x: x[1].get("found_at", ""), reverse=True)
        for eid, info in sorted_items[:10]:
            print(f"  {info.get('found_at', '?')[:19]}  {info.get('title', '?')[:60]}")
    else:
        print("No tracked entries yet.")


# ─── Main ────────────────────────────────────────────────────────────────────


def main():
    parser = argparse.ArgumentParser(description="SIGNAL RSS/Feed Ingester")
    sub = parser.add_subparsers(dest="command", required=True)

    # check
    sub.add_parser("check", help="Check feeds for new items (no analysis)")

    # ingest
    ingest_p = sub.add_parser("ingest", help="Fetch and optionally analyze new items")
    ingest_p.add_argument("--analyze", "-a", action="store_true", help="Auto-analyze new items")
    ingest_p.add_argument("--enrich", "-e", action="store_true", help="Auto-enrich after analysis (requires --analyze)")
    ingest_p.add_argument("--provider", default="ollama", choices=["ollama", "openai"],
                          help="Analysis provider")

    # list
    sub.add_parser("list", help="Show feed sources and tracked entries")

    args = parser.parse_args()

    # Ensure data files exist
    _ensure_file(SEEN_FILE, {})

    if args.command == "check":
        cmd_check()
    elif args.command == "ingest":
        cmd_ingest(analyze=args.analyze, provider=args.provider, enrich=args.enrich)
    elif args.command == "list":
        cmd_list()


if __name__ == "__main__":
    main()
