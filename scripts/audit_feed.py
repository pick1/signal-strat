#!/usr/bin/env python3
"""Analyze SIGNAL db — is there anything worth implementing?"""

import json
import sys
from pathlib import Path
from collections import Counter
from datetime import datetime, timezone

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
from signald.db import load_entries
from signald.config import CAT_LABELS

entries = load_entries()
print(f"Total entries: {len(entries)}")

# ─── Category breakdown ───
cats = Counter(e.get("category", "unknown") for e in entries)
print("\n=== By Category ===")
for cat, count in cats.most_common():
    label = CAT_LABELS.get(cat, cat)
    print(f"  {label:15s}  {count} entries")

# ─── Source types ───
sources = Counter(e.get("source_type", "unknown") for e in entries)
print("\n=== By Source ===")
for src, count in sources.most_common():
    print(f"  {src:15s}  {count} entries")

# ─── Tags ───
all_tags = [t for e in entries for t in e.get("tags", [])]
tag_counts = Counter(all_tags)
print("\n=== Top 15 Tags ===")
for tag, count in tag_counts.most_common(15):
    print(f"  #{tag:25s}  {count}x")

# ─── Confidence ───
confs = [e.get("confidence", 0) for e in entries]
avg_conf = sum(confs) / len(confs)
print(f"\n=== Confidence (avg {avg_conf:.0%}) ===")
print(f"  High (>=0.85): {sum(1 for c in confs if c >= 0.85)} entries")
print(f"  Med (0.6-0.85): {sum(1 for c in confs if 0.6 <= c < 0.85)} entries")
print(f"  Low (<0.6): {sum(1 for c in confs if c < 0.6)} entries")

# ─── Recent ───
now_ts = datetime.now(timezone.utc).timestamp()
recent = sum(
    1 for e in entries
    if datetime.fromisoformat(e.get("created_at", "2000-01-01")).timestamp() > now_ts - 7 * 86400
)
print(f"\nEntries last 7 days: {recent}")

# ─── Deep dive: Viable entries ───
print("\n\n=== VIABLE (build these) ===")
viable = [e for e in entries if e.get("category") == "viable"]
for e in sorted(viable, key=lambda x: x.get("confidence", 0), reverse=True):
    print(f"\n  [{e.get('confidence', 0):.0%}] {e.get('title', '?')}")
    print(f"       {e.get('verdict', '')}")
    print(f"       tags: {', '.join(e.get('tags', []))}")
    for step in e.get("next_steps", []):
        print(f"       → {step}")

# ─── Deep dive: Work entries ───
print("\n\n=== WORK (investigate further) ===")
work = [e for e in entries if e.get("category") == "work"]
for e in sorted(work, key=lambda x: x.get("confidence", 0), reverse=True):
    print(f"\n  [{e.get('confidence', 0):.0%}] {e.get('title', '?')}")
    print(f"       {e.get('verdict', '')}")
    print(f"       tags: {', '.join(e.get('tags', []))}")

# ─── Deep dive: Watch entries ───
print("\n\n=== WATCH (keep an eye on) ===")
watch = [e for e in entries if e.get("category") == "watch"]
for e in sorted(watch, key=lambda x: x.get("confidence", 0), reverse=True)[:5]:
    print(f"\n  [{e.get('confidence', 0):.0%}] {e.get('title', '?')}")
    print(f"       {e.get('verdict', '')}")
