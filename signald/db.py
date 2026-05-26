"""TinyDB operations for SIGNAL."""

from tinydb import TinyDB

from signald.config import DB_PATH


def get_db() -> TinyDB:
    """Return a singleton TinyDB instance."""
    return TinyDB(DB_PATH)


def load_entries() -> list:
    """Load all entries, sorted newest-first."""
    db = get_db()
    entries = db.all()
    return sorted(entries, key=lambda x: x.get("created_at", ""), reverse=True)


def save_entry(entry: dict) -> int:
    """Insert an entry and return its doc_id."""
    db = get_db()
    return db.insert(entry)


def delete_entry(doc_id: int):
    """Remove an entry by its doc_id."""
    db = get_db()
    db.remove(doc_ids=[doc_id])


def search_entries(query: str, field: str = None) -> list:
    """Search entries; if field is None, search across title/summary/verdict/tags."""
    from tinydb import Query
    q = Query()
    db = get_db()
    all_entries = db.all()

    q_lower = query.lower()
    results = []
    for e in all_entries:
        if field:
            if q_lower in str(e.get(field, "")).lower():
                results.append(e)
        else:
            if (
                q_lower in e.get("title", "").lower()
                or q_lower in e.get("summary", "").lower()
                or q_lower in e.get("verdict", "").lower()
                or any(q_lower in t.lower() for t in e.get("tags", []))
            ):
                results.append(e)
    return results


def get_stats() -> dict:
    """Return aggregate statistics over the whole database."""
    entries = load_entries()
    if not entries:
        return {"total": 0}

    from collections import Counter
    cats = Counter(e.get("category", "unknown") for e in entries)
    sources = Counter(e.get("source_type", "unknown") for e in entries)
    all_tags = []
    for e in entries:
        all_tags.extend(e.get("tags", []))
    top_tags = Counter(all_tags).most_common(10)

    return {
        "total": len(entries),
        "categories": dict(cats),
        "sources": dict(sources),
        "top_tags": top_tags,
    }
