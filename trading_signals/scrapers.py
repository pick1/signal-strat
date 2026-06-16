"""Content fetching and scraping for TRADING SIGNALS.

Focused on financial news sources — Yahoo Finance, SEC filings, company announcements,
earnings reports, and general financial articles.
"""

import re

import requests
import trafilatura
from bs4 import BeautifulSoup

from trading_signals.config import (
    YAHOO_FINANCE_RE,
    SEC_RE,
)


# ─── URL Scraping ────────────────────────────────────────────────────────────


def fetch_url_content(url: str) -> str:
    """Two-stage scraping: trafilatura first, BS4 fallback."""
    try:
        downloaded = trafilatura.fetch_url(url)
        if downloaded:
            text = trafilatura.extract(downloaded, include_comments=False, include_tables=True)
            if text and len(text) > 200:
                return text
        headers = {"User-Agent": "Mozilla/5.0 (compatible; TradingSignalsBot/1.0)"}
        resp = requests.get(url, headers=headers, timeout=15)
        resp.raise_for_status()
        soup = BeautifulSoup(resp.text, "lxml")
        for tag in soup(["script", "style", "nav", "footer", "aside", "noscript"]):
            tag.decompose()
        return soup.get_text(separator="\n", strip=True)[:12000]
    except Exception as e:
        return f"[Could not fetch URL: {e}]"


# ─── Input Detection ─────────────────────────────────────────────────────────


def detect_input_type(text: str) -> str:
    """Guess whether user input is a URL, financial article, or note."""
    text = text.strip()
    if re.match(r"https?://", text):
        return "url"
    if len(text) < 300:
        return "tweet"
    return "article"


# ─── Ticker Detection ────────────────────────────────────────────────────────


def extract_tickers(text: str) -> list[str]:
    """Extract potential stock tickers from text.

    Heuristic: uppercase 1-5 letter words. Filters obvious non-tickers.
    """
    candidates = re.findall(r'\b[A-Z]{1,5}\b', text)
    # Filter out common English words that happen to be uppercase
    skip = {"A", "I", "THE", "AND", "FOR", "ARE", "WAS", "NOT", "ITS",
            "BUT", "ALL", "CAN", "YOU", "HAS", "HAD", "NOW", "THEN",
            "THAN", "MORE", "MUCH", "VERY", "HERE", "THERE", "THIS",
            "THAT", "WHAT", "WHEN", "WHERE", "WHICH", "WHO", "WHY",
            "HOW", "YOUR", "OUR", "THEIR", "HAVE", "DOES", "DID",
            "WILL", "WOULD", "COULD", "SHOULD", "MAY", "ALSO", "YET",
            "JUST", "ABOUT", "INTO", "OVER", "SUCH", "ONLY", "OTHER",
            "NEW", "EACH", "SOME", "MOST", "MANY", "SAME", "PART",
            "FACT", "CASE", "WEEK", "YEAR", "TIME", "GOOD", "LONG",
            "HIGH", "LOW", "BEST", "NEXT", "LAST", "FIRST", "SAID",
            "MADE", "MAKE", "TAKE", "COME", "CAME", "GIVE", "KNOW",
            "DATA", "INFO", "TYPE", "SIZE", "AREA", "CORE", "VIEW",
            "CEO", "CFO", "COO", "CTO", "USA", "NYSE", "NASDAQ",
            "SEC", "IPO", "GDP", "CPI", "PPI", "ETF", "REIT",
            "EPS", "PE", "EV", "EBITDA", "ROI", "ROE", "PEG",
            "AI", "ML", "API", "SaaS", "B2B", "B2C", "DTC",
            "YTD", "Q1", "Q2", "Q3", "Q4", "FY", "H1", "H2",
            "MACD", "RSI", "SMA", "EMA", "ATH", "OTC", "AMEX",
            "INC", "LLC", "CORP", "LTD", "PLC", "AG", "NV", "SA",
        }
    return [c for c in candidates if c not in skip][:10]


# ─── Source Detection ───────────────────────────────────────────────────────


def is_financial_url(url: str) -> bool:
    """Check if a URL is from a known financial news source."""
    financial_domains = [
        "finance.yahoo.com", "yahoo.com/news", "sec.gov", "marketwatch.com",
        "benzinga.com", "seekingalpha.com", "bloomberg.com", "reuters.com",
        "cnbc.com", "fool.com", "investopedia.com", "wsj.com", "ft.com",
        "barrons.com", "thestreet.com", "zerohedge.com",
        "coindesk.com", "cointelegraph.com",
    ]
    return any(d in url for d in financial_domains)


# ─── SEC Filing Detection ────────────────────────────────────────────────────


def fetch_sec_filing(url: str) -> str:
    """Fetch and extract content from an SEC EDGAR filing URL."""
    try:
        headers = {
            "User-Agent": "TradingSignals/1.0 (contact@example.com)",
            "Accept": "text/html,application/xhtml+xml",
        }
        resp = requests.get(url, headers=headers, timeout=15)
        resp.raise_for_status()
        soup = BeautifulSoup(resp.text, "lxml")
        # SEC filings have the actual content in <body> or in a separate document
        text = soup.get_text(separator="\n", strip=True)
        return text[:12000]
    except Exception as e:
        return f"[Could not fetch SEC filing: {e}]"
