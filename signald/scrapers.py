"""Content fetching and scraping for SIGNAL.

URL fetching, Instagram post/reel extraction (with Whisper audio transcription),
and GitHub repository metadata enrichment.
"""

import os
import re
import tempfile
from pathlib import Path

import instaloader
import requests
import trafilatura
import whisper
from bs4 import BeautifulSoup

from signald.config import INSTAGRAM_RE, GITHUB_REPO_RE
from urllib.parse import quote


# ─── URL Scraping ────────────────────────────────────────────────────────────


def fetch_url_content(url: str) -> str:
    """Two-stage scraping: trafilatura first, BS4 fallback."""
    try:
        downloaded = trafilatura.fetch_url(url)
        if downloaded:
            text = trafilatura.extract(downloaded, include_comments=False, include_tables=True)
            if text and len(text) > 200:
                return text
        headers = {"User-Agent": "Mozilla/5.0 (compatible; SIGNALBot/1.0)"}
        resp = requests.get(url, headers=headers, timeout=10)
        resp.raise_for_status()
        soup = BeautifulSoup(resp.text, "lxml")
        for tag in soup(["script", "style", "nav", "footer", "aside"]):
            tag.decompose()
        return soup.get_text(separator="\n", strip=True)[:8000]
    except Exception as e:
        return f"[Could not fetch URL: {e}]"


# ─── Instagram ───────────────────────────────────────────────────────────────


def extract_shortcode(url: str) -> str | None:
    """Extract Instagram post/reel shortcode from URL."""
    m = INSTAGRAM_RE.search(url)
    return m.group(1) if m else None


_instaloader_instance = None
_whisper_model = None


def get_instaloader() -> instaloader.Instaloader:
    """Singleton Instaloader instance."""
    global _instaloader_instance
    if _instaloader_instance is None:
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
        config_dir = Path.home() / ".config" / "instaloader"
        if config_dir.is_dir():
            session_files = list(config_dir.glob("session*"))
            if session_files:
                try:
                    L.load_session_from_file(None, str(session_files[0]))
                except Exception:
                    pass
        _instaloader_instance = L
    return _instaloader_instance


def get_whisper():
    """Singleton Whisper model (base)."""
    global _whisper_model
    if _whisper_model is None:
        _whisper_model = whisper.load_model("base")
    return _whisper_model


def transcribe_video(video_url: str) -> str:
    """Download a reel video and transcribe with Whisper."""
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
        return result.get("text", "").strip()
    except Exception as e:
        return f"[transcription error: {e}]"
    finally:
        try:
            os.unlink(tmp.name)
        except Exception:
            pass


def fetch_instagram_content(url: str) -> tuple[str, dict]:
    """Fetch Instagram post/reel metadata and optional audio transcript.
    Returns (content_for_llm, metadata_for_display).
    """
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

    if post.is_video and post.video_url:
        meta["video_url"] = post.video_url
        transcript = transcribe_video(post.video_url)
        meta["transcript"] = transcript
        if transcript and not transcript.startswith("[transcription error"):
            parts.append("Audio transcript:\n" + transcript)

    content = "\n\n".join(parts)
    return content, meta


# ─── GitHub ──────────────────────────────────────────────────────────────────


def fetch_repo_info(owner: str, repo: str) -> dict | None:
    """Fetch repository metadata from GitHub API."""
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
    """Search GitHub for a repository by name prefix variations."""
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
                    # Guard: require >100 stars to avoid irrelevant matches
                    if d.get("stargazers_count", 0) < 100:
                        continue
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


SLASH_REPO_RE = re.compile(r'(?<!/|\w)([A-Z][A-Za-z0-9_.-]+)/([A-Z][A-Za-z0-9_.-]+)(?!/|\w)')
GITHUB_CONTEXT_RE = re.compile(r'\b(github|repo|repos|repository|stars|MIT\s*license)\b', re.IGNORECASE)
REPO_CANDIDATE_RE = re.compile(r'[A-Z][a-z]+[A-Z][A-Za-z-]*')
_STOP_WORDS = {
    'the','a','an','is','was','are','were','it','its','this','that',
    'for','of','to','in','on','with','and','or','by','from','at','has',
    'have','had','not','but','all','just','got','dropped','one','free',
    'already','every','does','now','then','than','more','much','can',
    'will','would','could','should','may','also','very','here','there',
    'their','our','your','how','what','why','who','github','repo','repos',
    'repository','stars','license',
}


def _github_search(q: str, seen: set) -> dict | None:
    """Single GitHub search helper."""
    try:
        r = requests.get(
            f"https://api.github.com/search/repositories?q={quote(q)}+in:name&sort=stars&per_page=1",
            headers={"Accept": "application/vnd.github.v3+json"}, timeout=10,
        )
        if r.status_code == 200:
            items = r.json().get("items", [])
            if items and items[0].get("stargazers_count", 0) > 100:
                d = items[0]
                fn = d["full_name"].lower()
                if fn not in seen:
                    seen.add(fn)
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
    """Scan content for repo references and enrich with GitHub metadata.
    Returns (enriched_content, list_of_repo_dicts).
    """
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

    # 2. Match inline Owner/Repo patterns
    for m in SLASH_REPO_RE.finditer(scan_text):
        owner, repo = m.group(1), m.group(2)
        key = f"{owner}/{repo}"
        if key in seen:
            continue
        seen.add(key)
        info = fetch_repo_info(owner, repo)
        if info:
            repos.append(info)

    # 3. Content with GitHub context → search by candidate project names
    has_context = bool(GITHUB_CONTEXT_RE.search(scan_text))
    if has_context:
        seen.add("github")
        for m in REPO_CANDIDATE_RE.finditer(scan_text):
            name = m.group()
            if name.lower() in seen:
                continue
            seen.add(name.lower())
            info = search_repo_by_name(name)
            if info:
                repos.append(info)

    # 4. Smart fallback: keyword-based repo search
    if has_context and not repos and len(scan_text) > 50:
        terms = [w for w in re.findall(r'[A-Za-z][A-Za-z0-9]*', scan_text)
                 if w.lower() not in _STOP_WORDS and (len(w) > 2 or (len(w) == 2 and w[0].isupper()))]

        candidates = []
        for i in range(len(terms) - 1):
            info = _github_search(" ".join(terms[i:i+2]), seen)
            if info: candidates.append(info)

        for i in range(len(terms) - 1):
            info = _github_search(terms[i] + terms[i+1], seen)
            if info: candidates.append(info)

        if len(terms) > 2:
            for i in range(len(terms) - 2):
                info = _github_search(terms[i] + terms[i+1] + terms[i+2], seen)
                if info: candidates.append(info)

        if len(terms) > 2:
            for i in range(len(terms) - 2):
                joined = terms[i] + terms[i+1].lower() + terms[i+2].lower()
                info = _github_search(joined, seen)
                if info: candidates.append(info)

        for i in range(len(terms) - 1):
            info = _github_search(terms[i].title() + terms[i+1].title(), seen)
            if info: candidates.append(info)

        if candidates:
            candidates.sort(key=lambda x: x["stars"] or 0, reverse=True)
            repos.append(candidates[0])

    # Dedup
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
        bits = [f"{r['full_name']}: {r['description'] or 'No description'}"]
        meta_bits = []
        if r["stars"] is not None:
            meta_bits.append(f"stars: {r['stars']}")
        if r["language"]:
            meta_bits.append(r["language"])
        if r["topics"]:
            meta_bits.append(f"topics: {', '.join(r['topics'])}")
        if meta_bits:
            bits.append(" | ".join(meta_bits))
        lines.append("  ".join(bits))
    return "\n".join(lines), repos


# ─── Input Detection ─────────────────────────────────────────────────────────


def detect_input_type(text: str) -> str:
    """Guess whether user input is a URL, Instagram post, tweet, or article."""
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
