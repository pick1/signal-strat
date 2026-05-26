"""Entity extraction and enrichment for SIGNAL.

After the initial LLM analysis, extracts key entities (tools,
frameworks, papers, repos) and searches for real-world resources
— GitHub repos, docs, related articles — to add rigor and detail.
"""

import json
import re
import time
from datetime import datetime, timezone
from urllib.parse import quote

import requests

from signald.config import (
    OLLAMA_MODEL,
    ENRICHMENT_REQUESTS,
)
from signald.analyzer import analyze_with_ollama, parse_json_result


# ─── Entity Extraction ──────────────────────────────────────────────────────

EXTRACT_PROMPT = """You are a research entity extractor. Given a tech article's
content and its analysis, extract the key technical entities mentioned.

Return a JSON array of objects with:
  - name: the entity name (tool, framework, library, paper, repo, person)
  - type: one of ["tool", "framework", "paper", "repo", "person", "concept"]
  - reason: why this entity matters (1 sentence)

Example:
[
  {"name": "FastMCP", "type": "framework",
   "reason": "Python library for building MCP servers"},
  {"name": "ollama/ollama", "type": "repo",
   "reason": "GitHub repo for running LLMs locally"}
]

Return ONLY valid JSON. No markdown fences."""


def extract_entities(text: str, analysis: dict) -> list[dict]:
    """Use the local LLM to extract entities from content + analysis."""
    content_snippet = text[:2000] if text else ""
    analysis_snippet = json.dumps({
        "title": analysis.get("title"),
        "summary": analysis.get("summary"),
        "tags": analysis.get("tags"),
        "verdict": analysis.get("verdict"),
        "implementability": analysis.get("implementability"),
        "opencode_fit": analysis.get("opencode_fit"),
    }, indent=2)

    prompt = (
        f"--- Article Content (first 2000 chars) ---\n{content_snippet}\n\n"
        f"--- Analysis Results ---\n{analysis_snippet}\n\n"
        "Extract all technical entities. Return ONLY JSON array."
    )

    try:
        result = analyze_with_ollama(prompt, "entity extraction", OLLAMA_MODEL)
        entities = result if isinstance(result, list) else result.get("entities", [])
        return entities[:10]  # Cap at 10
    except Exception as e:
        return [{"name": "error", "type": "error", "reason": str(e)}]


# ─── GitHub Search ──────────────────────────────────────────────────────────

_SEARCH_CACHE = {}


def search_github(query: str, limit: int = 3) -> list[dict]:
    """Search GitHub repos by keyword. Returns repo metadata."""
    cache_key = f"github:{query}"
    if cache_key in _SEARCH_CACHE:
        return _SEARCH_CACHE[cache_key]

    params = {
        "q": query,
        "sort": "stars",
        "per_page": limit,
        "order": "desc",
    }
    headers = {
        "Accept": "application/vnd.github.v3+json",
        "User-Agent": "SIGNAL-Enricher/1.0",
    }

    try:
        resp = requests.get(
            "https://api.github.com/search/repositories",
            params=params,
            headers=headers,
            timeout=15,
        )
        if resp.status_code == 403:
            return [{"error": "GitHub API rate limited"}]
        resp.raise_for_status()
        items = resp.json().get("items", [])
        results = [
            {
                "name": repo["full_name"],
                "url": repo["html_url"],
                "stars": repo["stargazers_count"],
                "description": repo.get("description", "") or "",
                "language": repo.get("language", ""),
                "topics": repo.get("topics", []),
                "updated_at": repo.get("updated_at", ""),
                "source": "github",
            }
            for repo in items[:limit]
        ]
    except Exception as e:
        results = [{"error": str(e), "source": "github"}]

    _SEARCH_CACHE[cache_key] = results
    return results


def fetch_readme(full_name: str) -> str | None:
    """Fetch a repo's README content (first ~2K chars)."""
    url = f"https://api.github.com/repos/{full_name}/readme"
    headers = {
        "Accept": "application/vnd.github.v3.raw",
        "User-Agent": "SIGNAL-Enricher/1.0",
    }
    try:
        resp = requests.get(url, headers=headers, timeout=10)
        if resp.status_code == 200:
            text = resp.text[:2000]
            # Strip markdown to get plain-ish text
            text = re.sub(r"```.*?```", "", text, flags=re.DOTALL)
            text = re.sub(r"#+\s*", "", text)
            text = re.sub(r"\[([^\]]+)\]\([^)]+\)", r"\1", text)
            return text.strip()[:1500]
    except Exception:
        pass
    return None


def enrich_github_repos(entities: list[dict]) -> list[dict]:
    """For each repo-type entity, search GitHub and fetch README summaries."""
    enriched = []
    seen = set()

    for entity in entities:
        entity_type = entity.get("type", "")
        name = entity.get("name", "")
        if not name:
            continue

        # Every entity can yield repo results
        results = search_github(name)
        for repo in results:
            if repo.get("name") and repo["name"] not in seen:
                seen.add(repo["name"])
                readme = fetch_readme(repo["name"])
                if readme:
                    repo["readme_snippet"] = readme
                enriched.append(repo)
                if len(enriched) >= 6:
                    return enriched

        time.sleep(0.5)  # Be nice to GitHub API

    return enriched


# ─── Link Following ─────────────────────────────────────────────────────────


def find_and_fetch_links(text: str, max_links: int = 5) -> list[dict]:
    """Extract URLs from article content and fetch them for more detail."""
    urls = re.findall(r"https?://[^\s\"'<>)]+", text)
    # Filter to interesting domains
    interesting = [u for u in urls if any(
        d in u for d in [
            "github.com", "arxiv.org", "wikipedia.org", "docs.",
            "blog.", "dev.to", "medium.com", "huggingface.co",
            "pypi.org", "npmjs.com", "crates.io",
        ]
    )][:max_links]

    results = []
    for url in interesting:
        try:
            resp = requests.get(
                url,
                headers={"User-Agent": "SIGNAL-Enricher/1.0"},
                timeout=8,
            )
            if resp.status_code == 200:
                snippets = re.findall(r"<p[^>]*>(.*?)</p>", resp.text, re.DOTALL)[:3]
                content = " ".join(
                    re.sub(r"<[^>]+>", "", s).strip()
                    for s in snippets if s
                )[:1000]
                results.append({
                    "url": url,
                    "title": (
                        _re_match.group(1)[:100]
                        if (_re_match := re.search(r"<title[^>]*>(.*?)</title>", resp.text, re.DOTALL))
                        else url
                    ),
                    "snippet": content,
                    "source": "web",
                })
        except Exception:
            pass

    return results


# ─── Enrichment Synthesis ───────────────────────────────────────────────────

SYNTHESIS_PROMPT = """You are a research synthesis agent. Given the original
article analysis and the research results below, produce a structured enrichment.

The enrichment should answer:
1. What real tools/repos exist for this topic?
2. Where are the official docs or repos?
3. What concrete details (stars, activity, language) back up the analysis?
4. Is there additional context that changes or deepens the original verdict?

Return JSON with:
  - key_findings: list of 2-5 sentence findings
  - resources: list of {name, url, description, relevance} objects
  - verdict_update: "confirmed", "strengthened", "weakened", or "unchanged"
  - rigor_notes: what concrete facts were uncovered

Return ONLY valid JSON. No markdown."""


def synthesize_enrichment(
    analysis: dict,
    github_results: list[dict],
    link_results: list[dict],
    entities: list[dict],
) -> dict:
    """Use the local LLM to synthesize research findings into enrichment."""
    context = {
        "original_analysis": {
            "title": analysis.get("title"),
            "summary": analysis.get("summary"),
            "verdict": analysis.get("verdict"),
            "tags": analysis.get("tags"),
        },
        "github_findings": [
            {
                "repo": r.get("name"),
                "stars": r.get("stars"),
                "description": r.get("description"),
                "readme_snippet": r.get("readme_snippet", "")[:500],
            }
            for r in github_results if "name" in r
        ],
        "web_findings": [
            {
                "title": r.get("title"),
                "url": r.get("url"),
                "snippet": r.get("snippet", "")[:300],
            }
            for r in link_results
        ],
        "entities": [e.get("name") for e in entities],
    }

    prompt = (
        "--- Research Context ---\n"
        f"{json.dumps(context, indent=2, default=str)}\n\n"
        "Synthesize a structured enrichment report. Return ONLY JSON."
    )

    try:
        result = analyze_with_ollama(prompt, "enrichment synthesis", OLLAMA_MODEL)
        return result if isinstance(result, dict) else {"key_findings": [], "resources": []}
    except Exception as e:
        return {
            "key_findings": [f"Enrichment synthesis failed: {e}"],
            "resources": [],
            "verdict_update": "unchanged",
            "rigor_notes": "",
        }


# ─── Main Pipeline ──────────────────────────────────────────────────────────


def enrich(text: str, analysis: dict) -> dict:
    """Run the full enrichment pipeline.

    Steps:
      1. Extract entities from content + analysis
      2. Search GitHub for each entity
      3. Fetch READMEs for top repos
      4. Follow links from the original content
      5. Synthesize everything into a structured enrichment
    """
    start = time.time()

    # Step 1: Extract entities
    entities = extract_entities(text, analysis)
    entity_types = " | ".join(f"{e.get('name','?')}[{e.get('type','?')}]" for e in entities)

    # Step 2-3: GitHub search + READMEs
    github_results = enrich_github_repos(entities) if ENRICHMENT_REQUESTS.get("github") else []

    # Step 4: Follow links
    link_results = find_and_fetch_links(text) if ENRICHMENT_REQUESTS.get("links") else []

    # Step 5: Synthesize
    synthesized = synthesize_enrichment(analysis, github_results, link_results, entities)

    elapsed = time.time() - start

    return {
        "entities": entities,
        "entity_summary": entity_types[:300],
        "github_results": github_results,
        "link_results": link_results,
        "key_findings": synthesized.get("key_findings", []),
        "resources": synthesized.get("resources", []),
        "verdict_update": synthesized.get("verdict_update", "unchanged"),
        "rigor_notes": synthesized.get("rigor_notes", ""),
        "enriched_at": datetime.now(timezone.utc).isoformat(),
        "enrichment_time": round(elapsed, 1),
    }
