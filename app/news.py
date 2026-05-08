"""News layer.

Sources: Finnhub (primary), NewsAPI (fallback).
Bucketing: regex over titles + summaries into Rating Actions / Capital Activity /
           Management & Macro. A headline can land in multiple buckets.
Sentiment: FinBERT if `transformers` + the model are available, else a
           credit-tuned keyword scorer (NOT generic VADER — VADER misreads
           credit language, e.g., "downgrade" reads neutral).

The Top-10 aggregator caches for 15 minutes to avoid rate-limit punishment on
tab switches.
"""
from __future__ import annotations

import os
import re
import time
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from typing import Optional

import requests
import streamlit as st


# ---------- Bucketing ----------

BUCKETS = {
    "Rating Actions": [
        r"\brating\b", r"\bmoody'?s\b", r"\bs&p\b", r"\bfitch\b", r"\boutlook\b",
        r"\bupgrade\b", r"\bdowngrade\b", r"\bwatch\b", r"\baffirm\b",
    ],
    "Capital Activity": [
        r"\bissuance\b", r"\bbond\b", r"\bnotes?\b", r"\btender\b",
        r"\brefinanc\w*\b", r"\bbuy[- ]?back\b", r"\bdividend\b",
        r"\bcapital raise\b", r"\brevolver\b",
    ],
    "Management & Macro": [
        r"\bguidance\b", r"\bcap[- ]?ex\b", r"\bgeopolitical\b", r"\bsanction\w*\b",
        r"\btariff\w*\b", r"\ballocation\b", r"\bm&a\b", r"\bacquisition\b",
        r"\bdivestiture\b",
    ],
}
_BUCKET_REGEX = {b: re.compile("|".join(p), re.IGNORECASE) for b, p in BUCKETS.items()}


def categorize(text: str) -> list[str]:
    if not text:
        return []
    return [b for b, rx in _BUCKET_REGEX.items() if rx.search(text)]


# ---------- Sentiment ----------

# Credit-language keyword lists. The signs reflect credit perspective, not
# equity — buybacks score slightly negative because they consume cash.
NEG_TERMS = [
    "downgrade", "default", "bankruptcy", "miss", "weakness", "decline",
    "loss", "concern", "investigation", "restructuring", "covenant breach",
    "litigation", "warning", "negative outlook", "credit watch negative",
    "buyback", "dividend hike", "leveraged buyout", "lbo", "going concern",
]
POS_TERMS = [
    "upgrade", "affirmed", "stable outlook", "positive outlook", "deleverag",
    "tender", "refinanc", "improved", "raised guidance", "beat", "strengthen",
    "repayment", "debt reduction",
]
_NEG_RX = re.compile("|".join(re.escape(t) for t in NEG_TERMS), re.IGNORECASE)
_POS_RX = re.compile("|".join(re.escape(t) for t in POS_TERMS), re.IGNORECASE)

_FINBERT_PIPELINE = None  # lazily loaded


def _try_finbert():
    """Load FinBERT once; return None on any failure (network, missing deps, etc.)."""
    global _FINBERT_PIPELINE
    if _FINBERT_PIPELINE is False:
        return None
    if _FINBERT_PIPELINE is not None:
        return _FINBERT_PIPELINE
    if os.environ.get("DISABLE_FINBERT") == "1":
        _FINBERT_PIPELINE = False
        return None
    try:
        from transformers import pipeline  # type: ignore
        _FINBERT_PIPELINE = pipeline(
            "sentiment-analysis", model="ProsusAI/finbert", truncation=True, max_length=256,
        )
        return _FINBERT_PIPELINE
    except Exception:
        _FINBERT_PIPELINE = False
        return None


def score_sentiment(text: str) -> tuple[str, float]:
    """Returns ('Positive'|'Negative'|'Neutral', score in [-1,1])."""
    if not text or not text.strip():
        return "Neutral", 0.0
    pipe = _try_finbert()
    if pipe is not None:
        try:
            r = pipe(text[:512])[0]
            label = r["label"].capitalize()
            sc = float(r["score"])
            if label == "Negative":
                return "Negative", -sc
            if label == "Positive":
                return "Positive", sc
            return "Neutral", 0.0
        except Exception:
            pass  # fall through to keyword scorer
    # Keyword fallback.
    pos = len(_POS_RX.findall(text))
    neg = len(_NEG_RX.findall(text))
    if pos == 0 and neg == 0:
        return "Neutral", 0.0
    raw = (pos - neg) / max(pos + neg, 1)
    if raw > 0.2:
        return "Positive", min(raw, 1.0)
    if raw < -0.2:
        return "Negative", max(raw, -1.0)
    return "Neutral", raw


# ---------- Fetchers ----------


@dataclass
class NewsItem:
    ticker: str
    timestamp: datetime
    source: str
    headline: str
    summary: str
    url: str
    sentiment: str
    sentiment_score: float
    categories: list[str]


@st.cache_data(ttl=600, show_spinner=False)
def fetch_news_for_ticker(ticker: str, days: int = 30) -> list[dict]:
    """Returns a list of dicts (Streamlit cache prefers dicts over dataclasses)."""
    items = _fetch_finnhub(ticker, days) or _fetch_newsapi(ticker, days) or []
    enriched = []
    for it in items:
        sentiment, score = score_sentiment(f"{it['headline']} {it.get('summary', '')}")
        cats = categorize(f"{it['headline']} {it.get('summary', '')}")
        enriched.append({
            **it,
            "ticker": ticker,
            "sentiment": sentiment,
            "sentiment_score": score,
            "categories": cats,
        })
    return enriched


def _fetch_finnhub(ticker: str, days: int) -> Optional[list[dict]]:
    key = os.environ.get("FINNHUB_API_KEY")
    if not key:
        return None
    try:
        end = datetime.utcnow().date()
        start = end - timedelta(days=days)
        url = (
            f"https://finnhub.io/api/v1/company-news?symbol={ticker}"
            f"&from={start.isoformat()}&to={end.isoformat()}&token={key}"
        )
        r = requests.get(url, timeout=15)
        if r.status_code != 200:
            return None
        items = []
        for row in r.json():
            ts = datetime.fromtimestamp(row.get("datetime", 0), tz=timezone.utc)
            items.append({
                "timestamp": ts,
                "source": row.get("source", ""),
                "headline": row.get("headline", ""),
                "summary": row.get("summary", ""),
                "url": row.get("url", ""),
            })
        return items
    except Exception:
        return None


def _fetch_newsapi(ticker: str, days: int) -> Optional[list[dict]]:
    key = os.environ.get("NEWSAPI_KEY")
    if not key:
        return None
    try:
        end = datetime.utcnow().date()
        start = end - timedelta(days=days)
        url = (
            "https://newsapi.org/v2/everything"
            f"?q={ticker}&from={start.isoformat()}&to={end.isoformat()}"
            f"&sortBy=publishedAt&apiKey={key}&language=en"
        )
        r = requests.get(url, timeout=15)
        if r.status_code != 200:
            return None
        items = []
        for row in r.json().get("articles", []):
            try:
                ts = datetime.fromisoformat(row["publishedAt"].replace("Z", "+00:00"))
            except Exception:
                ts = datetime.utcnow().replace(tzinfo=timezone.utc)
            items.append({
                "timestamp": ts,
                "source": (row.get("source") or {}).get("name", ""),
                "headline": row.get("title", ""),
                "summary": row.get("description", "") or "",
                "url": row.get("url", ""),
            })
        return items
    except Exception:
        return None


# ---------- Top-10 aggregator ----------

# Composite-score weights from the spec — recency, credit keywords, sentiment magnitude.
W_RECENCY = 24.0
W_KEYWORD = 1.0
W_SENT_MAG = 0.5


def _composite_score(item: dict) -> float:
    ts = item["timestamp"]
    if ts.tzinfo is None:
        ts = ts.replace(tzinfo=timezone.utc)
    hours = max((datetime.now(timezone.utc) - ts).total_seconds() / 3600.0, 0.5)
    recency = W_RECENCY * (1.0 / hours)
    keyword_count = len(item.get("categories", []))
    keyword = W_KEYWORD * keyword_count
    sent_mag = W_SENT_MAG * abs(item.get("sentiment_score", 0.0))
    return recency + keyword + sent_mag


@st.cache_data(ttl=900, show_spinner=False)  # 15 min, per spec
def fetch_top_news(active_tickers: tuple[str, ...], limit: int = 30) -> list[dict]:
    """Aggregate across the active watchlist over the last 7 days."""
    if not active_tickers:
        return []
    cutoff = datetime.now(timezone.utc) - timedelta(days=7)
    pool: list[dict] = []
    for tk in active_tickers:
        try:
            items = fetch_news_for_ticker(tk, days=7)
        except Exception:
            continue
        for it in items:
            ts = it["timestamp"]
            if ts.tzinfo is None:
                ts = ts.replace(tzinfo=timezone.utc)
            if ts < cutoff:
                continue
            pool.append(it)
    if not pool:
        return []
    pool.sort(key=_composite_score, reverse=True)
    # De-dupe by headline so the same cross-posted story doesn't fill the list.
    seen = set()
    out = []
    for it in pool:
        key = it["headline"].strip().lower()[:120]
        if key in seen:
            continue
        seen.add(key)
        out.append(it)
        if len(out) == limit:
            break
    return out


def sentiment_engine_label() -> str:
    """For the UI footer — tells the analyst which sentiment path is active."""
    pipe = _try_finbert()
    return "FinBERT" if pipe is not None else "credit-keyword (FinBERT unavailable)"
