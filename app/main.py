"""Credit Snapshot Pro — entry point.

Sidebar (persistent across tabs):
    - Active Ticker dropdown (driven by Active=True watchlist rows)
    - PDF upload (agency report ingestion for the active ticker)
    - View toggle: Reported vs. Adjusted
    - Last-Updated timestamps per data source

Five tabs in spec order: Watchlist · Snapshot · Agency · News (Single) · News (Top 30).
"""
from __future__ import annotations

import os
import sys
from datetime import datetime
from pathlib import Path

# Allow `python -m streamlit run app/main.py` from project root.
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

import streamlit as st  # noqa: E402

from app import db, llm, theme  # noqa: E402
from app.tabs import agency, news_single, news_top10, snapshot, watchlist  # noqa: E402


def _llm_configured() -> bool:
    """Sidebar status — same key resolution as app.llm._has_key()."""
    return llm._has_key()


def main() -> None:
    st.set_page_config(
        page_title="Credit Snapshot Pro",
        layout="wide",
        initial_sidebar_state="expanded",
    )
    theme.install_plotly_template()
    st.markdown(theme.CSS, unsafe_allow_html=True)

    db.init_db()

    # ---------- Sidebar ----------
    with st.sidebar:
        st.markdown("### Credit Snapshot Pro")
        st.caption("Buy-side credit dashboard")

        active_list = db.active_tickers()
        # Honor ?ticker=... query param from Top-10 click-throughs.
        qp_ticker = st.query_params.get("ticker", "")
        if isinstance(qp_ticker, list):
            qp_ticker = qp_ticker[0] if qp_ticker else ""
        default_idx = (
            active_list.index(qp_ticker) if qp_ticker in active_list else (0 if active_list else None)
        )
        active_ticker = st.selectbox(
            "Active Ticker",
            active_list,
            index=default_idx,
            accept_new_options=True,
            placeholder="Pick from watchlist or type any ticker",
            help="Type any symbol (e.g. NVDA) to spot-check a non-watchlist name.",
        )
        active_ticker = (active_ticker or "").strip().upper()
        if not active_list:
            st.caption("Watchlist is empty — type a ticker above or add some in the Watchlist tab.")

        st.markdown("---")
        uploaded_pdf = st.file_uploader(
            "Agency report PDF",
            type=["pdf"],
            help="Upload to extract rating triggers in Agency Watch",
        )
        if uploaded_pdf is not None and active_ticker:
            st.caption(f"PDF ready for {active_ticker} · go to Agency Watch")

        st.markdown("---")
        view = st.radio("View", ["Reported", "Adjusted"], horizontal=True)
        adjusted = view == "Adjusted"

        st.markdown("---")
        st.markdown("**Last Updated**")
        st.caption(f"Session start: {datetime.utcnow().strftime('%Y-%m-%d %H:%M UTC')}")
        st.caption(f"FMP: {'on' if os.environ.get('FMP_API_KEY') else 'unset → yfinance'}")
        st.caption(f"Finnhub: {'on' if os.environ.get('FINNHUB_API_KEY') else 'unset'}")
        st.caption(f"NewsAPI: {'on' if os.environ.get('NEWSAPI_KEY') else 'unset'}")
        st.caption(f"LLM: {'Gemini' if _llm_configured() else 'unset → placeholders'}")

    # ---------- Tabs ----------
    tabs = st.tabs([
        "Watchlist Manager",
        "Credit Snapshot",
        "Agency Watch",
        "News — Single Name",
        "News — Watchlist Top 30",
    ])

    with tabs[0]:
        watchlist.render()
    with tabs[1]:
        snapshot.render(active_ticker, adjusted)
    with tabs[2]:
        agency.render(active_ticker, uploaded_pdf, adjusted)
    with tabs[3]:
        news_single.render(active_ticker)
    with tabs[4]:
        news_top10.render()


if __name__ == "__main__":
    main()
