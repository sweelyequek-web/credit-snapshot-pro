"""Tab 4 — News (Single Name)."""
from __future__ import annotations

import streamlit as st

from app import news, theme


def render(active_ticker: str) -> None:
    if not active_ticker:
        st.warning("Pick a ticker from the sidebar.")
        return

    st.subheader(f"News — {active_ticker}")
    st.caption(f"Sentiment engine: {news.sentiment_engine_label()} · 30-day window")

    items = []
    try:
        items = news.fetch_news_for_ticker(active_ticker, days=30)
    except Exception as e:
        st.error(f"News fetch failed: {e}")
        return

    if not items:
        st.info(
            "No news returned. Set FINNHUB_API_KEY (preferred) or NEWSAPI_KEY "
            "to enable news fetch."
        )
        return

    cols = st.columns([2, 2, 2])
    with cols[0]:
        bucket_filter = st.multiselect(
            "Category filters", list(news.BUCKETS.keys()), default=[],
            key=f"news_buckets_{active_ticker}",
        )
    with cols[1]:
        sentiment_filter = st.multiselect(
            "Sentiment", ["Positive", "Negative", "Neutral"], default=[],
            key=f"news_sentiment_{active_ticker}",
        )
    with cols[2]:
        search = st.text_input("Search headlines", key=f"news_search_{active_ticker}")

    filtered = items
    if bucket_filter:
        filtered = [
            it for it in filtered
            if any(b in it.get("categories", []) for b in bucket_filter)
        ]
    if sentiment_filter:
        filtered = [it for it in filtered if it["sentiment"] in sentiment_filter]
    if search:
        s = search.lower()
        filtered = [
            it for it in filtered
            if s in it["headline"].lower() or s in it.get("summary", "").lower()
        ]

    st.caption(f"Showing {len(filtered)} of {len(items)} headlines")

    for it in filtered:
        _render_news_card(it)


def _render_news_card(it: dict) -> None:
    sent = it.get("sentiment", "Neutral")
    sent_color = {
        "Positive": theme.POS, "Negative": theme.NEG, "Neutral": theme.TEXT_MUTED,
    }.get(sent, theme.TEXT_MUTED)
    cats = " · ".join(it.get("categories", [])) or "—"
    ts = it["timestamp"].strftime("%Y-%m-%d %H:%M") if it.get("timestamp") else ""
    headline = it.get("headline", "")
    url = it.get("url", "#")
    source = it.get("source", "")
    st.markdown(
        f"""
        <div class='news-card'>
            <div style='display:flex; justify-content:space-between; gap:8px;'>
                <span class='timestamp'>{ts} · {source}</span>
                <span style='color:{sent_color}; font-size:11px; font-weight:bold;'>{sent}</span>
            </div>
            <div style='margin-top:6px;'>
                <a href='{url}' target='_blank' style='color:{theme.TEXT}; text-decoration:none;'>
                    {headline}
                </a>
            </div>
            <div class='timestamp' style='margin-top:4px;'>Categories: {cats}</div>
        </div>
        """,
        unsafe_allow_html=True,
    )
