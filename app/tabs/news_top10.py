"""Tab 5 — News (Watchlist Top 30).

Aggregates across all Active=True tickers from the last 7 days. Composite
score = recency + credit-keyword count + sentiment magnitude. 15-min cache.
"""
from __future__ import annotations

import streamlit as st

from app import db, llm, news, theme

TOP_N = 30


def render() -> None:
    st.subheader(f"Watchlist Top {TOP_N}")
    active = db.active_tickers()
    if not active:
        st.warning("No active tickers in the watchlist.")
        return

    st.caption(
        f"Aggregating across {len(active)} tickers · "
        f"7-day window · 15-minute cache · "
        f"Sentiment: {news.sentiment_engine_label()}"
    )

    if st.button("Force refresh"):
        news.fetch_top_news.clear()
        st.rerun()

    try:
        top = news.fetch_top_news(tuple(active), limit=TOP_N)
    except Exception as e:
        st.error(f"Aggregation failed: {e}")
        return

    if not top:
        st.info(
            "No news available. Set FINNHUB_API_KEY (preferred) or NEWSAPI_KEY "
            "to enable. Empty cache will retry on next refresh."
        )
        return

    for it in top:
        _render_top_card(it)


def _render_top_card(it: dict) -> None:
    sent = it.get("sentiment", "Neutral")
    sent_color = {
        "Positive": theme.POS, "Negative": theme.NEG, "Neutral": theme.TEXT_MUTED,
    }.get(sent, theme.TEXT_MUTED)
    cats = " · ".join(it.get("categories", [])) or "—"
    ts = it["timestamp"].strftime("%Y-%m-%d %H:%M") if it.get("timestamp") else ""
    summary = llm.summarize_news_headline(
        it.get("headline", ""), it.get("summary", ""),
    )
    cols = st.columns([1, 9])
    with cols[0]:
        st.markdown(
            f"<div class='ticker-badge' style='display:inline-block;'>"
            f"<a href='?ticker={it['ticker']}' style='color:{theme.TEXT}; text-decoration:none;'>"
            f"{it['ticker']}</a></div>",
            unsafe_allow_html=True,
        )
    with cols[1]:
        st.markdown(
            f"""
            <div class='news-card'>
                <div style='display:flex; justify-content:space-between; gap:8px;'>
                    <span class='timestamp'>{ts} · {it.get('source', '')} · {cats}</span>
                    <span style='color:{sent_color}; font-size:11px; font-weight:bold;'>{sent}</span>
                </div>
                <div style='margin-top:6px;'>
                    <a href='{it.get('url', '#')}' target='_blank'
                       style='color:{theme.TEXT}; text-decoration:none; font-weight:500;'>
                       {it.get('headline', '')}
                    </a>
                </div>
                <div class='timestamp' style='margin-top:4px;'>{summary}</div>
            </div>
            """,
            unsafe_allow_html=True,
        )
