#!/usr/bin/env python3
"""
Retroactive Enrichment: Run the research pipeline on every existing entry
that doesn't already have enrichment data.

For each entry: re-fetch article/URL/Instagram content → extract entities
→ search GitHub → follow links → synthesize findings → save enrichment.
"""

import sys
import time
import json
from pathlib import Path
from datetime import datetime

# Add project root to path
PROJECT_DIR = Path(__file__).resolve().parent.parent
if str(PROJECT_DIR) not in sys.path:
    sys.path.insert(0, str(PROJECT_DIR))

# Unbuffer stdout for background process output
sys.stdout.reconfigure(line_buffering=True)

from signald.db import get_db
from signald.analyzer import run_enrichment
from signald.scrapers import fetch_url_content, fetch_instagram_content


def get_raw_content_for_entry(entry: dict) -> str | None:
    """Re-fetch the raw content for an entry based on its type."""
    source_type = entry.get("source_type", "")
    raw_url = entry.get("raw_url", "")

    if source_type == "instagram":
        if not raw_url:
            print("    SKIP: no Instagram URL")
            return None
        try:
            content_text, _metadata = fetch_instagram_content(raw_url)
            if content_text:
                return content_text
        except Exception as e:
            print(f"    FAIL: Instagram fetch: {e}")
            return None

    elif source_type in ("url", "article"):
        if not raw_url:
            print("    SKIP: no URL")
            return None
        try:
            result = fetch_url_content(raw_url)
            if result:
                return result
        except Exception as e:
            print(f"    FAIL: URL fetch: {e}")
            return None

    elif source_type == "tweet":
        if not raw_url:
            print("    SKIP: no tweet URL")
            return None
        # For tweets, try fetching as a URL
        try:
            result = fetch_url_content(raw_url)
            if result:
                return result
        except Exception as e:
            print(f"    FAIL: Tweet fetch: {e}")
            return None

    else:
        # For direct text entries, we don't store the raw text
        print(f"    SKIP: source_type={source_type} (no stored content)")
        return None


def main():
    db = get_db()
    entries = db.all()

    # Sort by created_at so oldest first
    entries.sort(key=lambda e: e.get("created_at", ""))

    total = len(entries)
    done = 0
    skipped = 0
    failed = 0
    rate_limit_hits = 0

    print(f"Found {total} entries in SIGNAL database\n", flush=True)

    for i, entry in enumerate(entries):
        title = entry.get("title", "Untitled")[:60]
        source_type = entry.get("source_type", "?")

        # Check if already enriched
        existing_enrichment = entry.get("enrichment") or {}
        if existing_enrichment.get("enriched_at"):
            print(f"[{i+1}/{total}] SKIP (already enriched): {title}")
            skipped += 1
            continue

        print(f"[{i+1}/{total}] {source_type}: {title}")

        # Re-fetch content
        content = get_raw_content_for_entry(entry)
        if not content:
            skipped += 1
            continue

        # Run enrichment
        try:
            enrichment = run_enrichment(content, entry)
        except Exception as e:
            err_str = str(e)
            if "403" in err_str or "rate limit" in err_str.lower():
                print(f"    RATE LIMITED — waiting 60s...")
                time.sleep(60)
                try:
                    enrichment = run_enrichment(content, entry)
                except Exception as e2:
                    print(f"    FAIL (retry): {e2}")
                    failed += 1
                    continue
            else:
                print(f"    FAIL: {e}")
                failed += 1
                continue

        if enrichment:
            # Add enrichment to entry
            entry["enrichment"] = enrichment
            entry["enrichment"]["enriched_at"] = datetime.now().isoformat()

            # Save back to DB
            try:
                db.update(entry, doc_ids=[entry.doc_id])
            except AttributeError:
                # entry might not have doc_id
                pass

            repo_count = len(enrichment.get("github_results", []))
            finding_count = len(enrichment.get("key_findings", []))
            print(f"    ENRICHED: {repo_count} repos, {finding_count} findings")
            done += 1
        else:
            print(f"    EMPTY: enrichment returned no data")
            skipped += 1

        # Brief pause between entries to be kind to APIs
        time.sleep(2)

    print(f"\n{'='*50}")
    print(f"Done: {done} enriched, {skipped} skipped, {failed} failed")


if __name__ == "__main__":
    main()
