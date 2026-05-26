import streamlit as st
import ollama
import requests
import json
import re
import time
import hashlib
import secrets
from datetime import datetime
from pathlib import Path
from tinydb import TinyDB, Query
import trafilatura
import pandas as pd
import instaloader
import whisper
import tempfile
import os
from urllib.parse import quote

# ─── CONFIG ───────────────────────────────────────────────────────────────────
DB_PATH = Path(__file__).parent / "data" / "signal.json"
DB_PATH.parent.mkdir(exist_ok=True)

OLLAMA_MODEL = "qwen3:14b"

# ─── Multi-Model Config ──────────────────────────────────────────────────────
# Each tier maps to a specific model. You can switch between Ollama
# and OpenAI-compatible providers per-tier.
#
# Model tiers:
#   light  — fast/cheap for tweets, short notes, quick scans
#   default — balanced for articles, URLs, most content
#   deep   — heavy reasoning for papers, complex technical analysis
#
# Content-type routing:
#   tweet, instagram → light
#   url, article, newsletter, note → default
#   (all can use 'deep' via manual override)

MODEL_TIERS = {
    "light":   {"ollama": "qwen3:latest",       "openai": "deepseek-v4-flash-free"},
    "default": {"ollama": "qwen3:14b",          "openai": "deepseek-v4-flash-free"},
    "deep":    {"ollama": "deepseek-r1:14b",    "openai": "nemotron-3-super-free"},
}

# Source type → model tier mapping
SOURCE_TIER = {
    "tweet":      "light",
    "instagram":  "light",
    "url":        "default",
    "article":    "default",
    "newsletter": "default",
    "note":       "default",
}

# Provider
API_PROVIDER = os.getenv("SIGNAL_API_PROVIDER", "ollama")  # "ollama" or "openai"
OPENAI_BASE_URL = os.getenv("SIGNAL_OPENAI_BASE_URL", "https://opencode.ai/zen/v1")
OPENAI_API_KEY = os.getenv("SIGNAL_OPENAI_API_KEY", "")
OPENAI_MODEL = os.getenv("SIGNAL_OPENAI_MODEL", "deepseek-v4-flash-free")

# Fallback: if primary model fails, try this tier
FALLBACK_ENABLED = os.getenv("SIGNAL_FALLBACK_ENABLED", "true").lower() == "true"

INSTAGRAM_RE = re.compile(
    r'https?://(?:www\.)?(?:instagram\.com|instagr\.am)/'
    r'(?:p|reel|tv)/([A-Za-z0-9_\-]+)'
)
# Captures owner/repo from github.com URLs — used to auto-fetch repo metadata via GitHub API
GITHUB_REPO_RE = re.compile(r'github\.com/([A-Za-z0-9_.-]+)/([A-Za-z0-9_.-]+)')

CAT_COLORS = {
    "viable":    "#00ff88",
    "work":      "#4488ff",
    "vaporware": "#ff4466",
    "redundant": "#ffaa00",
    "watch":     "#aa66ff",
    "mixed":     "#88ddff",
}

CAT_LABELS = {
    "viable":    "Viable",
    "work":      "Work",
    "vaporware": "Vaporware",
    "redundant": "Redundant",
    "watch":     "Watch",
    "mixed":     "Mixed",
}

SYSTEM_PROMPT = """You are a senior technology analyst and engineer with 20 years of experience evaluating emerging tech, tools, frameworks, products, and industry trends. Your job is to analyze content submitted by a tech professional and produce a structured intelligence report.

Your analysis must be HONEST, OPINIONATED, and TECHNICALLY PRECISE. Avoid hype. Identify BS clearly.

The person you are analyzing for uses OpenCode as their AI coding assistant, runs local LLMs via Ollama (Qwen3:14b, DeepSeek-R1), self-hosts apps on Ubuntu Linux, and is actively building and extending their local AI stack. Tailor next_steps and opencode_fit to this specific context.

Return ONLY valid JSON — no markdown, no backticks, no explanation outside the JSON. Schema:
{
  "title": "Short punchy title for this entry (max 10 words). Include the exact tool/product name if one is featured.",
  "source_type": "article|instagram|url|tweet|newsletter|note|unknown",
  "category": "viable|work|vaporware|redundant|watch|mixed",
  "tags": ["2 to 5 topic tags. Include the tool/product name as a tag if applicable."],
  "summary": "2-3 sentence plain-language summary of what this is actually about. Identify the specific tool or product by name.",
  "implementability": "1-2 sentences: Can this be built/used today? What would it take?",
  "work_relevance": "1-2 sentences: Is this relevant to a professional engineering or product context?",
  "verdict": "Your blunt 1-2 sentence take. No hedging. Call it like you see it.",
  "confidence": 0.85,
  "next_steps": ["2 to 4 concrete actionable next steps to evaluate or implement this technology"],
  "opencode_fit": "1-2 sentences on how this fits into an OpenCode + local Ollama workflow. Be specific about MCP servers, model routing, tooling integrations, or say not applicable."
}

Categories:
- viable: Real technology that exists and can be implemented now
- work: Directly useful for professional/enterprise engineering contexts
- vaporware: Announced but does not exist or likely will not ship as promised
- redundant: Already solved by existing tools, nothing new here
- watch: Interesting but not ready, worth monitoring
- mixed: Multiple categories apply"""


# ─── DB ───────────────────────────────────────────────────────────────────────
@st.cache_resource
def get_db():
    return TinyDB(DB_PATH)  # JSON-backed, persists at data/signal.json

def load_entries():
    db = get_db()
    entries = db.all()
    return sorted(entries, key=lambda x: x.get("created_at", ""), reverse=True)

def save_entry(entry):
    db = get_db()
    db.insert(entry)

def delete_entry(doc_id):
    db = get_db()
    db.remove(doc_ids=[doc_id])


# ─── AUTH ─────────────────────────────────────────────────────────────────────
PASSWORD_FILE = DB_PATH.parent / ".password_hash"

def _hash_password(password: str, salt: str = None) -> tuple[str, str]:
    if salt is None:
        salt = secrets.token_hex(16)
    h = hashlib.sha256((salt + password).encode()).hexdigest()
    return salt, h

def is_password_set() -> bool:
    return PASSWORD_FILE.exists()

def verify_password(password: str) -> bool:
    if not is_password_set():
        return True
    stored = PASSWORD_FILE.read_text().strip()
    salt, expected = stored.split(":", 1)
    _, actual = _hash_password(password, salt)
    return actual == expected

def set_password(password: str):
    salt, h = _hash_password(password)
    PASSWORD_FILE.write_text(f"{salt}:{h}")


# ─── SCRAPING ─────────────────────────────────────────────────────────────────
def fetch_url_content(url: str) -> str:
    # Two-stage scraping: trafilatura first (best for articles), then manual BS4 fallback
    try:
        downloaded = trafilatura.fetch_url(url)
        if downloaded:
            text = trafilatura.extract(downloaded, include_comments=False, include_tables=True)
            if text and len(text) > 200:
                return text
        # Fallback: strip non-content tags and grab raw text
        headers = {"User-Agent": "Mozilla/5.0 (compatible; SIGNALBot/1.0)"}
        resp = requests.get(url, headers=headers, timeout=10)
        resp.raise_for_status()
        from bs4 import BeautifulSoup
        soup = BeautifulSoup(resp.text, "lxml")
        for tag in soup(["script", "style", "nav", "footer", "aside"]):
            tag.decompose()
        return soup.get_text(separator="\n", strip=True)[:8000]
    except Exception as e:
        return f"[Could not fetch URL: {e}]"


# ─── INSTAGRAM ────────────────────────────────────────────────────────────────
def extract_shortcode(url: str) -> str | None:
    # Pull the post/reel ID from URLs like instagram.com/p/ABC123 or instagr.am/reel/ABC123
    m = INSTAGRAM_RE.search(url)
    return m.group(1) if m else None


@st.cache_resource
def get_instaloader():
    # Lightweight config — we only need metadata, no media downloads
    L = instaloader.Instaloader(
        quiet=True,
        download_pictures=False,
        download_videos=False,
        download_video_thumbnails=False,
        download_geotags=False,
        download_comments=False,
        save_metadata=False,
        compress_json=False,
    )
    # Auto-load session if one exists (created via `instaloader --login=USERNAME`)
    config_dir = Path.home() / ".config" / "instaloader"
    if config_dir.is_dir():
        session_files = list(config_dir.glob("session*"))
        if session_files:
            try:
                L.load_session_from_file(None, str(session_files[0]))
            except Exception:
                pass
    return L


@st.cache_resource
def get_whisper():
    # "base" model: ~140MB, good accuracy, fast on GPU. Downloaded to ~/.cache/whisper on first call
    return whisper.load_model("base")


def transcribe_video(video_url: str) -> str:
    # Download reel video to temp file, transcribe with whisper, clean up
    tmp = tempfile.NamedTemporaryFile(suffix=".mp4", delete=False)
    try:
        resp = requests.get(video_url, stream=True, timeout=30)
        resp.raise_for_status()
        for chunk in resp.iter_content(chunk_size=8192):
            if chunk:
                tmp.write(chunk)
        tmp.close()
        model = get_whisper()
        result = model.transcribe(tmp.name, language="en")
        return result["text"].strip()
    except Exception as e:
        return f"[transcription error: {e}]"
    finally:
        try:
            os.unlink(tmp.name)
        except Exception:
            pass


def fetch_instagram_content(url: str) -> tuple[str, dict]:
    # Returns (content_for_llm, metadata_for_display)
    shortcode = extract_shortcode(url)
    if not shortcode:
        return f"[Could not parse Instagram URL: {url}]", {}

    L = get_instaloader()
    post = instaloader.Post.from_shortcode(L.context, shortcode)

    meta = {}
    parts = []

    meta["author"] = post.owner_username
    parts.append(f"Author: @{post.owner_username}")

    if post.date:
        meta["date"] = post.date.isoformat()
        parts.append(f"Date: {post.date.strftime('%Y-%m-%d')}")

    caption = post.caption or ""
    meta["caption"] = caption
    if caption:
        parts.append("Caption:\n" + caption)

    meta["likes"] = post.likes
    meta["comments_count"] = post.comments
    parts.append(f"Stats: {post.likes} likes, {post.comments} comments")

    meta["is_video"] = post.is_video
    meta["post_url"] = post.url

    # For reels: download audio and transcribe to feed into LLM analysis
    if post.is_video and post.video_url:
        meta["video_url"] = post.video_url
        transcript = transcribe_video(post.video_url)
        meta["transcript"] = transcript
        if transcript and not transcript.startswith("[transcription error"):
            parts.append("Audio transcript:\n" + transcript)

    content = "\n\n".join(parts)
    return content, meta


# ─── GITHUB ──────────────────────────────────────────────────────────────────
SLASH_REPO_RE = re.compile(r'(?<!/|\w)([A-Z][A-Za-z0-9_.-]+)/([A-Z][A-Za-z0-9_.-]+)(?!/|\w)')
# Matches inline Owner/Repo patterns (CamelCase owner, CamelCase repo) without github.com prefix
GITHUB_CONTEXT_RE = re.compile(r'\b(github|repo|repos|repository|stars|MIT\s*license)\b', re.IGNORECASE)
REPO_CANDIDATE_RE = re.compile(r'[A-Z][a-z]+[A-Z][A-Za-z-]*')  # PascalCase compound names like ScrapegraphAI


def fetch_repo_info(owner: str, repo: str) -> dict | None:
    try:
        resp = requests.get(
            f"https://api.github.com/repos/{owner}/{repo}",
            headers={"Accept": "application/vnd.github.v3+json"},
            timeout=10,
        )
        if resp.status_code == 200:
            d = resp.json()
            return {
                "full_name": d.get("full_name"),
                "description": (d.get("description") or "")[:200],
                "stars": d.get("stargazers_count"),
                "language": d.get("language"),
                "topics": d.get("topics", [])[:5],
                "url": d.get("html_url"),
                "forks": d.get("forks_count"),
                "license": d.get("license", {}).get("spdx_id") if d.get("license") else None,
            }
    except Exception:
        pass
    return None


def search_repo_by_name(name: str) -> dict | None:
    # Try exact match first
    for prefix in ["", "scrape", "ai-", "py-", "node-"]:
        q = f"{prefix}{name}"
        try:
            resp = requests.get(
                f"https://api.github.com/search/repositories?q={q}+in:name&sort=stars&per_page=1",
                headers={"Accept": "application/vnd.github.v3+json"},
                timeout=10,
            )
            if resp.status_code == 200:
                items = resp.json().get("items", [])
                if items:
                    d = items[0]
                    return {
                        "full_name": d.get("full_name"),
                        "description": (d.get("description") or "")[:200],
                        "stars": d.get("stargazers_count"),
                        "language": d.get("language"),
                        "topics": d.get("topics", [])[:5],
                        "url": d.get("html_url"),
                        "forks": d.get("forks_count"),
                        "license": d.get("license", {}).get("spdx_id") if d.get("license") else None,
                    }
        except Exception:
            pass
    return None


def enrich_with_repos(content: str, raw_input: str = "") -> tuple[str, list[dict]]:
    scan_text = raw_input + "\n" + content
    seen = set()
    repos = []

    # 1. Match github.com/owner/repo URLs
    for m in GITHUB_REPO_RE.finditer(scan_text):
        owner, repo = m.group(1).strip("/"), m.group(2).strip("/")
        key = f"{owner}/{repo}"
        if key in seen or not owner or not repo:
            continue
        seen.add(key)
        info = fetch_repo_info(owner, repo)
        if info:
            repos.append(info)

    # 2. Match inline Owner/Repo without domain (e.g. "VinciGit00/Scrapegraph-ai")
    for m in SLASH_REPO_RE.finditer(scan_text):
        owner, repo = m.group(1), m.group(2)
        key = f"{owner}/{repo}"
        if key in seen:
            continue
        seen.add(key)
        info = fetch_repo_info(owner, repo)
        if info:
            repos.append(info)

    # 3. When content mentions GitHub/repo context, search by candidate project names
    has_context = bool(GITHUB_CONTEXT_RE.search(scan_text))
    if has_context:
        seen.add("github")  # Skip "GitHub" — it's a context keyword, not a repo
        for m in REPO_CANDIDATE_RE.finditer(scan_text):
            name = m.group()
            if name.lower() in seen:
                continue
            seen.add(name.lower())
            info = search_repo_by_name(name)
            if info:
                repos.append(info)

    # 4. Fallback: search GitHub using top meaningful keywords
    if has_context and not repos and len(scan_text) > 50:
        _STOP = {'the','a','an','is','was','are','were','it','its','this','that',
            'for','of','to','in','on','with','and','or','by','from','at','has',
            'have','had','not','but','all','just','got','dropped','one','free',
            'already','every','does','now','then','than','more','much','can',
            'will','would','could','should','may','also','very','here','there',
            'their','our','your','how','what','why','who','github','repo','repos',
            'repository','stars','license'}
        # Keep capitalized short terms (e.g. "AI", "MIT") but filter lowercase noise
        terms = [w for w in re.findall(r'[A-Za-z][A-Za-z0-9]*', scan_text)
                 if w.lower() not in _STOP and (len(w) > 2 or (len(w) == 2 and w[0].isupper()))]

        def _search(q):
            r = requests.get(
                f"https://api.github.com/search/repositories?q={quote(q)}+in:name&sort=stars&per_page=1",
                headers={"Accept": "application/vnd.github.v3+json"}, timeout=10,
            )
            if r.status_code == 200:
                items = r.json().get("items", [])
                if items and items[0]["stargazers_count"] > 100:
                    d = items[0]
                    if d["full_name"].lower() not in seen:
                        seen.add(d["full_name"].lower())
                        return {"full_name": d.get("full_name"),
                            "description": (d.get("description") or "")[:200],
                            "stars": d.get("stargazers_count"),
                            "language": d.get("language"),
                            "topics": d.get("topics", [])[:5],
                            "url": d.get("html_url"),
                            "forks": d.get("forks_count"),
                            "license": d.get("license",{}).get("spdx_id") if d.get("license") else None}
            return None

        # Collect candidates from all strategies, pick highest-star result
        candidates = []

        # Bigrams (catches "scrape graph")
        for i in range(len(terms) - 1):
            info = _search(" ".join(terms[i:i+2]))
            if info: candidates.append(info)

        # Joining adjacent words (catches "scrapegraph" from "scrape graph")
        for i in range(len(terms) - 1):
            info = _search(terms[i] + terms[i+1])
            if info: candidates.append(info)

        # Triple join (catches "scrapegraphAI" from "scrape graph AI")
        if len(terms) > 2:
            for i in range(len(terms) - 2):
                joined = terms[i] + terms[i+1] + terms[i+2]
                info = _search(joined)
                if info: candidates.append(info)

        # Triple join with lowercase middle word (catches "Scrapegraph-ai" style)
        if len(terms) > 2:
            for i in range(len(terms) - 2):
                joined = terms[i] + terms[i+1].lower() + terms[i+2].lower()
                info = _search(joined)
                if info: candidates.append(info)

        # Title-case joins (catches "ScrapeGraphAI")
        for i in range(len(terms) - 1):
            info = _search(terms[i].title() + terms[i+1].title())
            if info: candidates.append(info)

        if candidates:
            candidates.sort(key=lambda x: x["stars"] or 0, reverse=True)
            repos.append(candidates[0])

    # Dedup by full_name (different detection paths may find same repo)
    seen_names = set()
    unique_repos = []
    for r in repos:
        key = r["full_name"].lower()
        if key not in seen_names:
            seen_names.add(key)
            unique_repos.append(r)

    repos = unique_repos

    if not repos:
        return content, []

    lines = [content, "", "--- Referenced Repositories ---"]
    for r in repos:
        parts = [f"{r['full_name']}: {r['description'] or 'No description'}"]
        meta_bits = []
        if r["stars"] is not None:
            meta_bits.append(f"stars: {r['stars']}")
        if r["language"]:
            meta_bits.append(r["language"])
        if r["topics"]:
            meta_bits.append(f"topics: {', '.join(r['topics'])}")
        if meta_bits:
            parts.append(" | ".join(meta_bits))
        lines.append("  ".join(parts))
    return "\n".join(lines), repos


# ─── INPUT DETECTION ──────────────────────────────────────────────────────────
def detect_input_type(text: str) -> str:
    text = text.strip()
    if re.match(r"https?://", text):
        if INSTAGRAM_RE.search(text):
            return "instagram"
        return "url"
    if len(text) < 400 and ("#" in text or "@" in text):
        return "instagram"
    if len(text) < 300:
        return "tweet"
    return "article"


# ─── ANALYSIS ─────────────────────────────────────────────────────────────────
def _parse_json_result(raw: str) -> dict:
    """Parse JSON from model output, stripping markdown fences."""
    clean = re.sub(r"```json|```", "", raw).strip()
    try:
        return json.loads(clean)
    except json.JSONDecodeError:
        match = re.search(r"\{.*\}", raw, re.DOTALL)
        if match:
            return json.loads(match.group())
        raise ValueError("Could not parse JSON from model output:\n" + raw[:500])


def _build_prompt(content: str, source_hint: str) -> tuple[str, str]:
    user_prompt = "Analyze this " + source_hint + ":\n\n---\n" + content[:6000] + "\n---"
    return SYSTEM_PROMPT, user_prompt


def analyze_with_ollama(content: str, source_hint: str, model: str) -> dict:
    system_prompt, user_prompt = _build_prompt(content, source_hint)
    try:
        response = ollama.chat(
            model=model,
            messages=[
                {"role": "system", "content": system_prompt},
                {"role": "user",   "content": user_prompt},
            ],
            options={"temperature": 0.3, "num_ctx": 8192},
            think=False,
        )
        raw = response["message"]["content"]
        return _parse_json_result(raw)
    except Exception as e:
        raise ValueError(f"Ollama ({model}) failed: {e}")


def analyze_with_openai(content: str, source_hint: str, model: str) -> dict:
    system_prompt, user_prompt = _build_prompt(content, source_hint)
    headers = {
        "Authorization": f"Bearer {OPENAI_API_KEY}",
        "Content-Type": "application/json",
    }
    payload = {
        "model": model,
        "messages": [
            {"role": "system", "content": system_prompt},
            {"role": "user",   "content": user_prompt},
        ],
        "temperature": 0.3,
        "max_tokens": 4096,
    }
    try:
        resp = requests.post(
            OPENAI_BASE_URL.rstrip("/") + "/chat/completions",
            headers=headers,
            json=payload,
            timeout=120,
        )
        resp.raise_for_status()
        raw = resp.json()["choices"][0]["message"]["content"]
        return _parse_json_result(raw)
    except Exception as e:
        raise ValueError(f"OpenAI API ({model}) failed: {e}")


def pick_model_for_source(source_type: str, provider: str, tier_override: str = None) -> str:
    """Pick the model based on source type, provider, and optional tier override."""
    if tier_override and tier_override != "auto":
        tier = tier_override
    else:
        tier = SOURCE_TIER.get(source_type, "default")

    model_map = MODEL_TIERS.get(tier, MODEL_TIERS["default"])
    return model_map.get(provider, model_map.get("ollama", "qwen3:14b"))


def analyze_content(
    content: str,
    source_hint: str,
    provider: str,
    tier_override: str = None,
) -> dict:
    """Analyze content with the appropriate provider and fallback chain."""
    model = pick_model_for_source(source_hint, provider, tier_override)

    if provider == "openai":
        if not OPENAI_API_KEY:
            raise ValueError("OpenAI API key not set (SIGNAL_OPENAI_API_KEY env var)")
        try:
            return analyze_with_openai(content, source_hint, model)
        except Exception as e:
            if FALLBACK_ENABLED:
                fallback_model = MODEL_TIERS["default"]["ollama"]
                st.toast(f"OpenAI failed ({model}), falling back to Ollama ({fallback_model})", icon="W")
                return analyze_with_ollama(content, source_hint, fallback_model)
            raise
    else:
        # Ollama (default)
        try:
            return analyze_with_ollama(content, source_hint, model)
        except Exception as e:
            if FALLBACK_ENABLED:
                fallback_model = MODEL_TIERS["default"]["openai"]
                if OPENAI_API_KEY:
                    st.toast(f"Ollama failed ({model}), falling back to OpenAI ({fallback_model})", icon="W")
                    return analyze_with_openai(content, source_hint, fallback_model)
            raise


# ─── CARD RENDERER ────────────────────────────────────────────────────────────
def render_card(entry, color, label, conf, tags, date):
    cat_tag = '<span class="tag" style="color:' + color + ';border-color:' + color + ';background:rgba(0,0,0,0.3)">' + label + '</span>'

    topic_tags = ""
    for t in tags:
        topic_tags += '<span class="tag" style="color:#7070a0;border-color:#353550">' + t + '</span>'

    repo_tags = ""
    for r in entry.get("repos", []):
        name = r.get("full_name", "")
        url = r.get("url", "")
        if name:
            href = f' href="{url}" target="_blank"' if url else ""
            repo_tags += '<a' + href + '><span class="tag" style="color:#44ff88;border-color:#44ff8833;background:rgba(68,255,136,0.05)">' + name + '</span></a>'

    if entry.get("raw_url"):
        src_tag = '<span class="tag" style="color:#7070a0;border-color:#353550">url</span>'
    else:
        src_tag = '<span class="tag" style="color:#7070a0;border-color:#353550">' + entry.get("source_type", "?") + '</span>'

    next_steps_html = ""
    for s in entry.get("next_steps", []):
        next_steps_html += "▸ " + str(s) + "<br>"
    if not next_steps_html:
        next_steps_html = "none"

    opencode_fit = entry.get("opencode_fit", "not analyzed")
    verdict      = entry.get("verdict", "")
    summary      = entry.get("summary", "")
    impl         = entry.get("implementability", "")
    work_rel     = entry.get("work_relevance", "")
    title = entry.get("title", "Untitled")

    instagram_html = ""
    meta = entry.get("instagram_meta")
    if meta:
        author = meta.get("author", "")
        likes = meta.get("likes", 0)
        caption = (meta.get("caption", "") or "")[:80]
        is_video = meta.get("is_video", False)
        has_transcript = bool(meta.get("transcript")) and not meta["transcript"].startswith("[transcription error")
        bits = []
        if author:
            bits.append(f"@{author}")
        if is_video:
            bits.append('<span class="tag" style="color:#ff4466;border-color:#ff446633;background:rgba(255,68,102,0.1)">REEL</span>')
        if likes:
            bits.append(f"likes: {likes}")
        if caption:
            bits.append(f'<span style="color:#606090">"{caption}{"..." if len((meta.get("caption") or "")) > 80 else ""}"</span>')
        if has_transcript:
            bits.append('<span class="tag" style="color:#44aaff;border-color:#44aaff33;background:rgba(68,170,255,0.1)">TRANSCRIPT</span>')
        if bits:
            instagram_html = '<div style="margin-bottom:10px;font-size:11px;color:#8080b0">' + " · ".join(bits) + '</div>'

    return (
        '<div class="card" style="border-left-color:' + color + '">'
        '<div class="card-title">' + title + '</div>'
        '<div style="margin-bottom:10px">' + cat_tag + src_tag + repo_tags + topic_tags + '</div>'
        + instagram_html +
        '<div class="section-text" style="margin-bottom:12px">' + summary + '</div>'
        '<div style="display:flex;gap:16px;margin-bottom:12px">'
          '<div style="flex:1;background:#0a0a0f;border:1px solid #252535;border-radius:8px;padding:10px 12px">'
            '<div class="section-label">Implementability</div>'
            '<div class="section-text">' + impl + '</div>'
          '</div>'
          '<div style="flex:1;background:#0a0a0f;border:1px solid #252535;border-radius:8px;padding:10px 12px">'
            '<div class="section-label">Work Relevance</div>'
            '<div class="section-text">' + work_rel + '</div>'
          '</div>'
        '</div>'
        '<div style="background:#0a0a0f;border:1px solid #252535;border-radius:8px;padding:10px 14px;margin-bottom:10px">'
          '<div class="section-label">Verdict</div>'
          '<div class="verdict-text">' + verdict + '</div>'
        '</div>'
        '<div style="display:flex;gap:16px;margin-bottom:10px">'
          '<div style="flex:1;background:#0a0a0f;border:1px solid #353550;border-radius:8px;padding:10px 12px">'
            '<div class="section-label">Next Steps</div>'
            '<div class="section-text">' + next_steps_html + '</div>'
          '</div>'
          '<div style="flex:1;background:#0a0a0f;border:1px solid #4488ff33;border-radius:8px;padding:10px 12px">'
            '<div class="section-label">OpenCode Fit</div>'
            '<div class="section-text">' + opencode_fit + '</div>'
          '</div>'
        '</div>'
        '<div style="display:flex;justify-content:space-between;align-items:center;border-top:1px solid #252535;padding-top:8px">'
          '<span style="color:#404060;font-size:11px">' + date + '</span>'
          '<span style="color:#404060;font-size:11px">confidence ' + str(conf) + '%'
            '<span style="display:inline-block;width:60px;height:4px;background:#252535;border-radius:2px;vertical-align:middle;margin-left:6px">'
              '<span style="display:block;width:' + str(conf) + '%;height:100%;background:' + color + ';border-radius:2px"></span>'
            '</span>'
          '</span>'
        '</div>'
        '</div>'
    )


# ─── PAGE SETUP ───────────────────────────────────────────────────────────────
st.set_page_config(
    page_title="SIGNAL — Tech Intelligence",
    page_icon="S",
    layout="wide",
    initial_sidebar_state="expanded",
)

st.markdown("""
<style>
@import url('https://fonts.googleapis.com/css2?family=Syne:wght@700;800&family=DM+Mono:ital,wght@0,300;0,400;1,300&display=swap');
html, body, [class*="css"] { font-family: 'DM Mono', monospace; }
.signal-header { font-family: 'Syne', sans-serif; font-size: 28px; font-weight: 800; color: #00ff88; letter-spacing: 0.15em; text-shadow: 0 0 30px rgba(0,255,136,0.4); margin-bottom: 0; }
.signal-sub { font-size: 10px; letter-spacing: 0.3em; color: #404060; text-transform: uppercase; margin-top: 0; }
.card { background: #111118; border: 1px solid #252535; border-radius: 12px; padding: 18px 20px; margin-bottom: 14px; border-left-width: 3px; }
.card-title { font-family: 'Syne', sans-serif; font-size: 17px; font-weight: 700; margin-bottom: 8px; }
.tag { display: inline-block; padding: 2px 10px; border-radius: 20px; font-size: 10px; letter-spacing: 0.1em; text-transform: uppercase; border: 1px solid; margin-right: 4px; margin-bottom: 4px; }
.section-label { font-size: 9px; letter-spacing: 0.2em; text-transform: uppercase; color: #404060; margin-bottom: 4px; }
.section-text { font-size: 12px; color: #9090b0; line-height: 1.6; }
.verdict-text { font-style: italic; font-size: 13px; color: #e8e8f0; line-height: 1.6; }
</style>
""", unsafe_allow_html=True)


# ─── AUTH GATE ────────────────────────────────────────────────────────────────
if not st.session_state.get("authenticated"):
    st.markdown(
        '<div class="signal-header" style="text-align:center;margin-top:40px">SIGNAL</div>'
        '<div class="signal-sub" style="text-align:center">Tech Intelligence Digest</div>',
        unsafe_allow_html=True,
    )

    if not is_password_set():
        st.markdown('<div style="max-width:360px;margin:40px auto">', unsafe_allow_html=True)
        st.markdown("**Set a password** to secure this dashboard.")
        pw = st.text_input("Password", type="password", key="setup_pw")
        pw2 = st.text_input("Confirm", type="password", key="setup_pw2")
        if st.button("Set Password", type="primary", use_container_width=True):
            if pw and pw == pw2 and len(pw) >= 4:
                set_password(pw)
                st.session_state["authenticated"] = True
                st.rerun()
            else:
                st.error("Password must be 4+ chars and match.")
        st.markdown("</div>", unsafe_allow_html=True)
    else:
        st.markdown('<div style="max-width:360px;margin:40px auto">', unsafe_allow_html=True)
        pw = st.text_input("Password", type="password", key="login_pw")
        if st.button("Unlock", type="primary", use_container_width=True):
            if verify_password(pw):
                st.session_state["authenticated"] = True
                st.rerun()
            else:
                st.error("Incorrect password.")
        st.markdown("</div>", unsafe_allow_html=True)

    st.stop()


# ─── SIDEBAR ──────────────────────────────────────────────────────────────────
with st.sidebar:
    st.markdown('<div class="signal-header">SIGNAL</div>', unsafe_allow_html=True)
    st.markdown('<div class="signal-sub">Tech Intelligence Digest</div>', unsafe_allow_html=True)
    st.divider()

    st.markdown("**Provider**")
    provider_options = ["Ollama (local)", "OpenAI API"]
    if not OPENAI_API_KEY:
        provider_options = ["Ollama (local)"]
    provider_choice = st.selectbox(
        "Provider", provider_options,
        index=0,
        label_visibility="collapsed",
    )
    provider = "openai" if "OpenAI" in provider_choice else "ollama"

    st.markdown("**Analysis Depth**")
    tier_options = ["Auto (per source type)", "Light", "Default", "Deep"]
    tier_choice = st.selectbox(
        "Tier", tier_options,
        index=0,
        label_visibility="collapsed",
    )
    tier_map = {"Auto (per source type)": None, "Light": "light", "Default": "default", "Deep": "deep"}
    tier_override = tier_map[tier_choice]

    if st.button("Lock", use_container_width=True):
        st.session_state["authenticated"] = False
        st.rerun()

    st.divider()

    st.markdown("**New Entry**")
    input_text = st.text_area(
        "Paste content or URL",
        height=180,
        placeholder="Paste article text, a URL, Instagram post, tweet thread...\n\nURLs are fetched and scraped automatically.",
        label_visibility="collapsed",
    )
    source_override = st.selectbox("Source type", [
        "Auto-detect", "Article", "URL", "Instagram", "Tweet", "Newsletter", "Note"
    ])
    analyze_btn = st.button("ANALYZE", use_container_width=True, type="primary")

    st.divider()

    st.markdown("**Filter Feed**")
    search_query = st.text_input("Search", placeholder="keyword...", label_visibility="collapsed")
    cat_filter = st.multiselect(
        "Categories",
        options=list(CAT_LABELS.keys()),
        format_func=lambda x: CAT_LABELS[x],
        label_visibility="collapsed",
    )

    st.divider()

    entries_all = load_entries()
    if entries_all:
        md_lines = ["# SIGNAL — Tech Intelligence Digest", "_Exported " + datetime.now().strftime("%Y-%m-%d") + "_", ""]
        for cat, label in CAT_LABELS.items():
            group = [e for e in entries_all if e.get("category") == cat]
            if not group:
                continue
            md_lines += ["## " + label, ""]
            for e in group:
                steps = "\n".join("- " + s for s in e.get("next_steps", []))
                md_lines += [
                    "### " + e.get("title", "Untitled"),
                    "**Tags:** " + ", ".join(e.get("tags", [])) + " | **Date:** " + e.get("created_at", "")[:10],
                    "", e.get("summary", ""), "",
                    "**Implementability:** " + e.get("implementability", ""),
                    "**Work Relevance:** " + e.get("work_relevance", ""),
                    "**Verdict:** _" + e.get("verdict", "") + "_",
                    "**Next Steps:**\n" + steps,
                    "**OpenCode Fit:** " + e.get("opencode_fit", ""),
                    "**Confidence:** " + str(round(e.get("confidence", 0.8) * 100)) + "%",
                    "", "---", ""
                ]
        st.download_button("Export Markdown", "\n".join(md_lines),
                           file_name="signal-digest.md", mime="text/markdown",
                           use_container_width=True)
        st.download_button("Export JSON", json.dumps(entries_all, indent=2),
                           file_name="signal-digest.json", mime="application/json",
                           use_container_width=True)
        if st.button("Clear All", use_container_width=True):
            if st.session_state.get("confirm_clear"):
                get_db().truncate()
                st.session_state.confirm_clear = False
                st.rerun()
            else:
                st.session_state.confirm_clear = True
                st.warning("Click again to confirm.")


# ─── ANALYSIS TRIGGER ─────────────────────────────────────────────────────────
if analyze_btn and input_text.strip():
    raw_input = input_text.strip()
    detected = detect_input_type(raw_input) if source_override == "Auto-detect" else source_override.lower()

    content = raw_input
    fetch_notice = None
    instagram_meta = None
    repo_data = []

    if re.match(r"https?://", raw_input):
        if detected == "instagram":
            with st.spinner("Fetching Instagram post..."):
                content, instagram_meta = fetch_instagram_content(raw_input)
                notice_parts = ["Fetched Instagram post"]
                if instagram_meta:
                    m = instagram_meta
                    if m.get("is_video"):
                        notice_parts.append("reel")
                    if m.get("transcript") and not m["transcript"].startswith("[transcription error"):
                        notice_parts.append("audio transcript")
                fetch_notice = " · ".join(notice_parts) + f" ({len(content)} chars)"
        else:
            with st.spinner("Fetching " + raw_input[:60] + "..."):
                content = fetch_url_content(raw_input)
                fetch_notice = "Fetched " + str(len(content)) + " chars from URL"

    # Scan all content for github.com/owner/repo references and auto-fetch metadata
    if content and not content.startswith("[Could not"):
        enriched, repo_data = enrich_with_repos(content, raw_input)
        if repo_data:
            content = enriched
            n = len(repo_data)
            fetch_notice = (fetch_notice or "Ready") + f" · {n} repo{'s' if n > 1 else ''} found"

    with st.spinner(f"Analyzing via {provider}..."):
        try:
            result = analyze_content(content, detected, provider, tier_override)
            entry = {
                "id": str(int(time.time() * 1000)),
                "created_at": datetime.now().isoformat(),
                "raw_url": raw_input if re.match(r"https?://", raw_input) else None,
                "source_type": detected,
                "instagram_meta": instagram_meta,
                "repos": repo_data,
                **result,
            }
            save_entry(entry)
            if fetch_notice:
                st.toast(fetch_notice, icon="G")
            st.toast("Entry added to feed", icon="A")
            st.rerun()
        except Exception as e:
            st.error("Analysis failed: " + str(e))

elif analyze_btn:
    st.sidebar.warning("Paste some content first.")


# ─── MAIN FEED ────────────────────────────────────────────────────────────────
entries = load_entries()

if cat_filter:
    entries = [e for e in entries if e.get("category") in cat_filter]
if search_query:
    q = search_query.lower()
    entries = [e for e in entries if
               q in e.get("title", "").lower() or
               q in e.get("summary", "").lower() or
               q in e.get("verdict", "").lower() or
               any(q in t.lower() for t in e.get("tags", []))]

all_entries = load_entries()
c1, c2, c3, c4, c5 = st.columns(5)
with c1:
    st.metric("Total", len(all_entries))
with c2:
    st.metric("Viable", sum(1 for e in all_entries if e.get("category") == "viable"))
with c3:
    st.metric("Work", sum(1 for e in all_entries if e.get("category") == "work"))
with c4:
    st.metric("Vaporware", sum(1 for e in all_entries if e.get("category") == "vaporware"))
with c5:
    st.metric("Watch", sum(1 for e in all_entries if e.get("category") == "watch"))

st.divider()

feed_col, _ = st.columns([3, 0.01])

with feed_col:
    st.markdown("**Intelligence Feed** — " + str(len(entries)) + (" entry" if len(entries) == 1 else " entries"))

    if not entries:
        st.info("Feed is empty. Paste an article, URL, or post in the sidebar and hit Analyze.")
    else:
        for entry in entries:
            cat    = entry.get("category", "watch")
            color  = CAT_COLORS.get(cat, "#888")
            label  = CAT_LABELS.get(cat, cat)
            conf   = round(entry.get("confidence", 0.8) * 100)
            tags   = entry.get("tags", [])
            date   = entry.get("created_at", "")[:10]
            doc_id = entry.doc_id

            st.markdown(render_card(entry, color, label, conf, tags, date), unsafe_allow_html=True)

            if entry.get("raw_url"):
                st.markdown("[View source](" + entry["raw_url"] + ")")

            if st.button("Delete", key="del_" + str(doc_id), help="Remove this entry"):
                delete_entry(doc_id)
                st.rerun()

            st.markdown("<div style='margin-bottom:8px'></div>", unsafe_allow_html=True)

