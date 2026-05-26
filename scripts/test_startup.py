#!/usr/bin/env python3
"""Quick test of retro_enrich startup."""
import sys
import time
from pathlib import Path

print("Step 1: imports", flush=True)
PROJECT_DIR = Path(__file__).resolve().parent.parent
if str(PROJECT_DIR) not in sys.path:
    sys.path.insert(0, str(PROJECT_DIR))

try:
    sys.stdout.reconfigure(line_buffering=True)
    print("  reconfigure OK", flush=True)
except Exception as e:
    print(f"  reconfigure failed: {e}", flush=True)

print("Step 2: loading signald modules", flush=True)
from signald.db import get_db
print("  db OK", flush=True)

from signald.analyzer import run_enrichment
print("  analyzer OK", flush=True)

from signald.scrapers import fetch_url_content, fetch_instagram_content
print("  scrapers OK", flush=True)

print("Step 3: get DB entries", flush=True)
db = get_db()
entries = db.all()
entries.sort(key=lambda e: e.get("created_at", ""))
print(f"  {len(entries)} entries loaded", flush=True)

print("Step 4: about to loop", flush=True)
total = len(entries)
for i, entry in enumerate(entries):
    title = entry.get("title", "Untitled")[:60]
    source_type = entry.get("source_type", "?")
    existing_enrichment = entry.get("enrichment") or {}
    
    if existing_enrichment.get("enriched_at"):
        print(f"[{i+1}/{total}] SKIP (already enriched): {title}", flush=True)
        continue

    print(f"[{i+1}/{total}] {source_type}: {title}", flush=True)
    
    # Just do first entry for this test
    print("  stopping after first entry (test)", flush=True)
    break

print("Done", flush=True)
