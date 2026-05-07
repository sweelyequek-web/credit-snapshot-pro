"""Tab 2 — Credit Snapshot."""
from __future__ import annotations

from datetime import datetime
from typing import Optional

import numpy as np
import pandas as pd
import plotly.graph_objects as go
import streamlit as st
from plotly.subplots import make_subplots

from app import data, db, edgar, llm, metrics, pdf_export, theme


def render(active_ticker: str, adjusted: bool) -> None:
    if not active_ticker:
        st.warning("Pick a ticker from the sidebar to load a snapshot.")
        return

    issuer_row = _issuer_row(active_ticker)

    fund_df, source = data.fetch_fundamentals(active_ticker, quarters=12)

    if fund_df.empty:
        st.error(
            f"No fundamentals returned for {active_ticker}. "
            "Set FMP_API_KEY for full coverage, or rely on yfinance fallback. "
            "If the ticker is correct, the data feed may be down."
        )
        return

    result = metrics.compute(fund_df, adjusted=adjusted)
    m = result.df

    if m.empty or m["leverage"].dropna().empty:
        st.warning(
            "Not enough quarterly data to compute TTM metrics yet "
            "(need at least four quarters of EBITDA history)."
        )
        st.dataframe(fund_df.head(8))
        return

    # Header strip
    _render_header(active_ticker, issuer_row, source, adjusted)

    # AI Credit Summary card
    _render_summary_card(m)

    # Adjustments expander
    if adjusted and result.adjustments_applied:
        with st.expander("View adjustments applied (Reported → Adjusted)"):
            for line in result.adjustments_applied:
                st.markdown(f"- {line}")
    if result.estimated_fields:
        with st.expander("Estimated fields (data feed gaps reconstructed)"):
            for line in result.estimated_fields:
                st.markdown(f"- {line}")

    # Latest metrics row
    _render_kpi_row(m)

    # Per-ticker red-line overrides
    notes = db.get_notes(active_ticker)
    leverage_redline = metrics.parse_redline(notes, "leverage_redline", 3.0)
    coverage_redline = metrics.parse_redline(notes, "coverage_redline", 5.0)

    # Four-quadrant dashboard
    fig, quadrant_figs = _build_four_quadrant(m, leverage_redline, coverage_redline)
    st.plotly_chart(fig, use_container_width=True, config={"displayModeBar": True})

    # Maturity wall
    st.markdown("### Maturity Wall")
    _render_maturity_wall(active_ticker, m)

    # Spread snapshot
    st.markdown("### Spread Snapshot")
    _render_spread_snapshot(active_ticker)

    # Peer overlay
    st.markdown("### Peer Overlay")
    _render_peer_overlay(active_ticker, m, leverage_redline, coverage_redline, adjusted)

    # MD&A liquidity pull
    st.markdown("### MD&A — Liquidity and Capital Resources")
    _render_liquidity_section(active_ticker)

    # PDF one-pager export
    st.markdown("---")
    _render_pdf_export(
        active_ticker,
        issuer_row,
        m,
        quadrant_figs,
    )


# ---------- Helpers ----------


def _issuer_row(ticker: str) -> dict:
    df = db.load_watchlist()
    row = df[df["Ticker"] == ticker]
    if row.empty:
        return {}
    return row.iloc[0].to_dict()


def _render_header(ticker: str, issuer_row: dict, source: str, adjusted: bool) -> None:
    cols = st.columns([3, 1, 1, 1])
    with cols[0]:
        name = issuer_row.get("Issuer Name", "")
        sector = issuer_row.get("Sector", "")
        st.markdown(f"#### {ticker} — {name}")
        st.caption(
            f"{sector or '—'} · Source: {source.upper()} · "
            f"View: {'Adjusted' if adjusted else 'Reported'}"
        )
    with cols[1]:
        st.metric("Internal Rating", issuer_row.get("Internal Rating", "—") or "—")
    with cols[2]:
        st.metric("Region", issuer_row.get("Region", "—") or "—")
    with cols[3]:
        st.metric("Last Updated", datetime.utcnow().strftime("%H:%M UTC"))


def _render_summary_card(m: pd.DataFrame) -> None:
    """One-sentence AI summary built from computed metrics only.

    Important per spec: do NOT feed news or freeform context here. That's what
    introduces hallucinated narrative.
    """
    last4 = m.tail(4)
    if last4.empty:
        return
    lev_first = last4["leverage"].dropna().iloc[0] if not last4["leverage"].dropna().empty else None
    lev_last = last4["leverage"].dropna().iloc[-1] if not last4["leverage"].dropna().empty else None
    cov_last = last4["coverage"].dropna().iloc[-1] if not last4["coverage"].dropna().empty else None
    geo_first = last4["net_gearing"].dropna().iloc[0] if not last4["net_gearing"].dropna().empty else None
    geo_last = last4["net_gearing"].dropna().iloc[-1] if not last4["net_gearing"].dropna().empty else None

    fact_block = (
        f"Leverage (Net Debt / TTM EBITDA): "
        f"{_fmt(lev_first, 'x')} -> {_fmt(lev_last, 'x')} over last 4 quarters. "
        f"Coverage (TTM EBITDA / TTM Interest): {_fmt(cov_last, 'x')}. "
        f"Net gearing: {_fmt(geo_first, '%')} -> {_fmt(geo_last, '%')}. "
        f"EBITDA TTM trajectory: {', '.join(_fmt(v, '') for v in last4['ebitda_ttm'].tolist())}."
    )
    summary = llm.summarize_credit_metrics(fact_block)
    st.info(summary)


def _render_kpi_row(m: pd.DataFrame) -> None:
    last = m.iloc[-1]
    cols = st.columns(4)
    with cols[0]:
        st.metric("Leverage (Net Debt / TTM EBITDA)", _fmt(last["leverage"], "x"))
    with cols[1]:
        st.metric("Coverage (TTM EBITDA / TTM Int.)", _fmt(last["coverage"], "x"))
    with cols[2]:
        st.metric("Net Gearing", _fmt(last["net_gearing"], "%"))
    with cols[3]:
        st.metric("Net Debt", _fmt_money(last["net_debt"]))


def _build_four_quadrant(
    m: pd.DataFrame, leverage_redline: float, coverage_redline: float
) -> tuple[go.Figure, list[go.Figure]]:
    """Returns the combined four-quadrant subplot AND a list of 4 standalone
    figures (used for PDF export).
    """
    x = pd.to_datetime(m["period_end"])

    fig = make_subplots(
        rows=2, cols=2,
        subplot_titles=(
            "TTM Leverage (Net Debt / EBITDA)",
            "TTM Coverage (EBITDA / Interest)",
            "Net Gearing %",
            "TTM EBITDA + QoQ Growth",
        ),
        vertical_spacing=0.16, horizontal_spacing=0.08,
    )

    fig.add_trace(go.Scatter(
        x=x, y=m["leverage"], mode="lines+markers", name="Leverage",
        line=dict(color=theme.POS, width=2),
    ), row=1, col=1)
    fig.add_hline(
        y=leverage_redline, line_dash="dash", line_color=theme.NEG,
        annotation_text=f"Redline {leverage_redline:.1f}x",
        annotation_position="top right",
        row=1, col=1,
    )

    fig.add_trace(go.Scatter(
        x=x, y=m["coverage"], mode="lines+markers", name="Coverage",
        line=dict(color=theme.POS, width=2),
    ), row=1, col=2)
    fig.add_hline(
        y=coverage_redline, line_dash="dash", line_color=theme.NEG,
        annotation_text=f"Redline {coverage_redline:.1f}x",
        annotation_position="top right",
        row=1, col=2,
    )

    fig.add_trace(go.Scatter(
        x=x, y=m["net_gearing"], mode="lines", name="Net Gearing",
        line=dict(color=theme.AMBER, width=1.5),
        fill="tozeroy", fillcolor="rgba(255,184,0,0.2)",
    ), row=2, col=1)

    fig.add_trace(go.Bar(
        x=x, y=m["ebitda_ttm"], name="TTM EBITDA",
        marker_color=theme.POS, opacity=0.7,
    ), row=2, col=2)
    fig.add_trace(go.Scatter(
        x=x, y=m["ebitda_qoq_growth"], name="QoQ Growth %",
        mode="lines+markers", line=dict(color=theme.AMBER, width=1.5),
        yaxis="y5",
    ), row=2, col=2)
    fig.update_layout(
        yaxis5=dict(
            overlaying="y4", side="right", showgrid=False,
            title=dict(text="QoQ %", font=dict(color=theme.AMBER)),
            tickfont=dict(color=theme.AMBER),
        ),
    )

    fig.update_yaxes(title_text="x", row=1, col=1)
    fig.update_yaxes(title_text="x", row=1, col=2)
    fig.update_yaxes(title_text="%", row=2, col=1)
    fig.update_yaxes(title_text="$", row=2, col=2)

    fig.update_layout(
        height=600, showlegend=False,
        margin=dict(l=40, r=40, t=50, b=40),
    )

    # Standalone figures for PDF embedding (kept simpler).
    quadrant_figs = []
    q1 = go.Figure(go.Scatter(x=x, y=m["leverage"], mode="lines+markers", line=dict(color=theme.POS)))
    q1.add_hline(y=leverage_redline, line_dash="dash", line_color=theme.NEG)
    q1.update_layout(title="TTM Leverage", height=250)
    quadrant_figs.append(q1)

    q2 = go.Figure(go.Scatter(x=x, y=m["coverage"], mode="lines+markers", line=dict(color=theme.POS)))
    q2.add_hline(y=coverage_redline, line_dash="dash", line_color=theme.NEG)
    q2.update_layout(title="TTM Coverage", height=250)
    quadrant_figs.append(q2)

    q3 = go.Figure(go.Scatter(x=x, y=m["net_gearing"], fill="tozeroy", line=dict(color=theme.AMBER)))
    q3.update_layout(title="Net Gearing %", height=250)
    quadrant_figs.append(q3)

    q4 = go.Figure(go.Bar(x=x, y=m["ebitda_ttm"], marker_color=theme.POS))
    q4.update_layout(title="TTM EBITDA", height=250)
    quadrant_figs.append(q4)

    return fig, quadrant_figs


def _render_maturity_wall(ticker: str, m: pd.DataFrame) -> None:
    """Maturity wall — debt by year with cash and revolver capacity overlays.

    The standard fundamentals feed doesn't include the per-year debt schedule
    (that's in the 10-K debt note). We surface a clean empty-state with a
    manual entry path rather than fabricating a schedule.
    """
    state_key = f"maturity_schedule_{ticker}"
    if state_key not in st.session_state:
        st.session_state[state_key] = pd.DataFrame({
            "Year": [datetime.utcnow().year + i for i in range(10)],
            "Maturing Debt": [0.0] * 10,
        })

    last_cash = float(m["cash"].iloc[-1]) if "cash" in m.columns and not m["cash"].isna().all() else 0.0

    cols = st.columns([3, 1])
    with cols[0]:
        st.caption(
            "Maturity schedules aren't returned by standard fundamentals feeds — they live in "
            "the 10-K debt note. Enter manually below if needed."
        )
        edited = st.data_editor(
            st.session_state[state_key],
            key=f"maturity_editor_{ticker}",
            use_container_width=True,
            num_rows="fixed",
        )
        st.session_state[state_key] = edited
    with cols[1]:
        revolver = st.number_input(
            "Undrawn revolver ($)", min_value=0.0, value=0.0, step=1e8,
            key=f"revolver_{ticker}",
        )
        st.metric("Last Cash + STI", _fmt_money(last_cash))

    fig = go.Figure()
    fig.add_trace(go.Bar(
        x=edited["Year"], y=edited["Maturing Debt"], name="Maturing Debt",
        marker_color=theme.AMBER,
    ))
    if last_cash > 0:
        fig.add_hline(
            y=last_cash, line_dash="dot", line_color=theme.POS,
            annotation_text=f"Cash {_fmt_money(last_cash)}",
            annotation_position="top right",
        )
    if revolver > 0:
        fig.add_hline(
            y=last_cash + revolver, line_dash="dot", line_color="#4a90e2",
            annotation_text=f"Cash + Revolver {_fmt_money(last_cash + revolver)}",
            annotation_position="top left",
        )
    fig.update_layout(height=300, xaxis_title="Year", yaxis_title="USD")
    st.plotly_chart(fig, use_container_width=True)


def _render_spread_snapshot(ticker: str) -> None:
    state_key = f"spread_{ticker}"
    if state_key not in st.session_state:
        st.session_state[state_key] = {"bond_spread": None, "index_level": None, "bond_label": ""}

    cols = st.columns(4)
    with cols[0]:
        bond_label = st.text_input(
            "Bond identifier", value=st.session_state[state_key]["bond_label"],
            key=f"bond_label_{ticker}",
        )
    with cols[1]:
        bond = st.number_input(
            "G-spread / Z-spread (bps)", min_value=0, max_value=5000, step=5,
            value=st.session_state[state_key]["bond_spread"] or 0,
            key=f"bond_spread_{ticker}",
        )
    with cols[2]:
        index_level = st.number_input(
            "Sector index level (bps)", min_value=0, max_value=5000, step=5,
            value=st.session_state[state_key]["index_level"] or 0,
            key=f"index_level_{ticker}",
        )
    with cols[3]:
        if bond > 0 and index_level > 0:
            diff = bond - index_level
            colorcls = "rag-red" if diff > 50 else "rag-green" if diff < -10 else "rag-amber"
            st.markdown(
                f"**Differential**<br/><span class='{colorcls}'>{diff:+d} bps</span>",
                unsafe_allow_html=True,
            )

    if bond > 0 or index_level > 0 or bond_label:
        st.session_state[state_key] = {
            "bond_spread": bond, "index_level": index_level, "bond_label": bond_label,
        }


def _render_peer_overlay(
    ticker: str, base_m: pd.DataFrame,
    leverage_redline: float, coverage_redline: float, adjusted: bool,
) -> None:
    wl = db.load_watchlist()
    candidates = [t for t in wl["Ticker"].tolist() if t and t != ticker]
    if not candidates:
        st.caption("Add more tickers to the watchlist to enable peer overlay.")
        return
    selected = st.multiselect(
        "Select up to 5 peers", candidates, default=[],
        max_selections=5, key=f"peers_{ticker}",
    )
    if not selected:
        return

    fig = make_subplots(rows=1, cols=2, subplot_titles=("Leverage", "Coverage"))
    x = pd.to_datetime(base_m["period_end"])
    fig.add_trace(
        go.Scatter(x=x, y=base_m["leverage"], name=ticker, line=dict(color=theme.POS, width=2)),
        row=1, col=1,
    )
    fig.add_trace(
        go.Scatter(x=x, y=base_m["coverage"], name=ticker,
                   line=dict(color=theme.POS, width=2), showlegend=False),
        row=1, col=2,
    )
    fig.add_hline(y=leverage_redline, line_dash="dash", line_color=theme.NEG, row=1, col=1)
    fig.add_hline(y=coverage_redline, line_dash="dash", line_color=theme.NEG, row=1, col=2)

    muted_palette = ["#666", "#888", "#aaa", "#999", "#777"]
    for i, peer in enumerate(selected):
        try:
            df_peer, _ = data.fetch_fundamentals(peer, quarters=12)
            if df_peer.empty:
                continue
            res = metrics.compute(df_peer, adjusted=adjusted)
            pm = res.df
            if pm.empty:
                continue
            color = muted_palette[i % len(muted_palette)]
            xp = pd.to_datetime(pm["period_end"])
            fig.add_trace(
                go.Scatter(x=xp, y=pm["leverage"], name=peer,
                           line=dict(color=color, width=1, dash="dot")),
                row=1, col=1,
            )
            fig.add_trace(
                go.Scatter(x=xp, y=pm["coverage"], name=peer,
                           line=dict(color=color, width=1, dash="dot"), showlegend=False),
                row=1, col=2,
            )
        except Exception as e:
            st.warning(f"Could not load peer {peer}: {e}")

    fig.update_layout(height=350, margin=dict(l=40, r=20, t=40, b=40))
    st.plotly_chart(fig, use_container_width=True)


def _render_liquidity_section(ticker: str) -> None:
    with st.spinner("Fetching latest 10-Q/10-K from SEC EDGAR..."):
        section, url = edgar.fetch_liquidity_section(ticker)
    if not section:
        st.caption(
            "Could not pull a Liquidity & Capital Resources section from EDGAR. "
            "Issuer may be a foreign filer (F-1/20-F) or filing format unparseable."
        )
        return
    if url:
        st.caption(f"Source: {url}")
    with st.expander("Verbatim section text", expanded=False):
        # Truncate display for sanity; spec says verbatim, but a 6000-char wall of
        # text in Streamlit is unreadable. Show first ~3000, offer download.
        st.text(section[:3000])
        if len(section) > 3000:
            st.caption(f"({len(section) - 3000} more chars truncated)")
            st.download_button(
                "Download full section", section.encode("utf-8"),
                file_name=f"{ticker}_liquidity.txt", mime="text/plain",
            )
    st.markdown("**3-bullet AI summary** (grounded only in the text above):")
    st.markdown(llm.summarize_liquidity_section(section))


def _render_pdf_export(
    ticker: str, issuer_row: dict, m: pd.DataFrame, quadrant_figs: list[go.Figure],
) -> None:
    if st.button("Download Credit One-Pager (PDF)"):
        # Try to render charts to PNG; if kaleido is missing this returns []
        # and pdf_export degrades gracefully.
        chart_pngs = []
        try:
            for f in quadrant_figs:
                chart_pngs.append(f.to_image(format="png", width=600, height=300, scale=1.5))
        except Exception:
            chart_pngs = []

        last = m.iloc[-1]
        summary = (
            f"Leverage {_fmt(last['leverage'], 'x')} · "
            f"Coverage {_fmt(last['coverage'], 'x')} · "
            f"Net Gearing {_fmt(last['net_gearing'], '%')}"
        )
        ratings_df = db.load_ratings(ticker)
        triggers = db.load_triggers(ticker)
        # Compute headroom for export.
        from app import news as news_mod
        from app import triggers as triggers_mod
        latest_metrics = {
            "leverage": _safe_float(last["leverage"]),
            "coverage": _safe_float(last["coverage"]),
            "net_gearing": _safe_float(last["net_gearing"]),
        }
        for t in triggers:
            cur = triggers_mod.map_metric_to_current(t["metric"], latest_metrics)
            t["current"] = cur
            t["headroom"] = triggers_mod.headroom_pct(cur, t["threshold"], t["operator"])
        try:
            headlines = news_mod.fetch_news_for_ticker(ticker, days=14)
        except Exception:
            headlines = []
        pdf_bytes = pdf_export.build_one_pager(
            ticker=ticker,
            issuer_name=issuer_row.get("Issuer Name", ""),
            summary_text=summary,
            quadrant_pngs=chart_pngs,
            ratings_df=ratings_df,
            triggers=triggers,
            headlines=headlines,
        )
        st.download_button(
            "Save PDF",
            data=pdf_bytes,
            file_name=f"{ticker}_credit_one_pager.pdf",
            mime="application/pdf",
        )


# ---------- Formatters ----------


def _fmt(v, suffix: str) -> str:
    if v is None or (isinstance(v, float) and (np.isnan(v) or np.isinf(v))):
        return "—"
    try:
        return f"{float(v):.2f}{suffix}"
    except (ValueError, TypeError):
        return "—"


def _fmt_money(v: Optional[float]) -> str:
    if v is None or (isinstance(v, float) and (np.isnan(v) or np.isinf(v))):
        return "—"
    v = float(v)
    if abs(v) >= 1e9:
        return f"${v / 1e9:.2f}B"
    if abs(v) >= 1e6:
        return f"${v / 1e6:.2f}M"
    return f"${v:,.0f}"


def _safe_float(v) -> Optional[float]:
    try:
        f = float(v)
        if np.isnan(f) or np.isinf(f):
            return None
        return f
    except (TypeError, ValueError):
        return None
