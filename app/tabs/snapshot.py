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

    fund_df, source, fmp_error = data.fetch_fundamentals(active_ticker, quarters=16)
    annual_df = data.fetch_fundamentals_annual(active_ticker, years=3)

    if fund_df.empty and annual_df.empty:
        st.error(
            f"No fundamentals returned for {active_ticker}. "
            "Set FMP_API_KEY for full coverage, or rely on yfinance fallback. "
            "If the ticker is correct, the data feed may be down."
        )
        return

    result = metrics.compute(fund_df, adjusted=adjusted) if not fund_df.empty else metrics.CreditMetricsResult(df=pd.DataFrame())
    m = result.df
    annual_m = metrics.compute_annual(annual_df, quarterly_result=result, adjusted=adjusted, years=2)

    if m.empty and annual_m.empty:
        st.warning(
            "Not enough data yet to compute credit metrics. "
            "yfinance typically returns ~5 quarters; quarterly TTM needs 4 of those to be fully populated."
        )
        if not fund_df.empty:
            st.dataframe(fund_df.head(8))
        return

    # Header strip
    _render_header(active_ticker, issuer_row, source, adjusted, fmp_error)

    # AI Credit Summary card
    if not m.empty:
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
    if not m.empty:
        _render_kpi_row(m)

    # Per-ticker red-line overrides
    notes = db.get_notes(active_ticker)
    leverage_redline = metrics.parse_redline(notes, "leverage_redline", 3.0)
    coverage_redline = metrics.parse_redline(notes, "coverage_redline", 5.0)

    # Quarterly snapshot — last 5 raw quarters
    quadrant_figs: list[go.Figure] = []
    if not m.empty:
        st.markdown("### Quarterly Snapshot — Last 5 Quarters")
        q_fig = _build_quarterly_chart(m.tail(5))
        st.plotly_chart(q_fig, use_container_width=True, config={"displayModeBar": True})

    # Annual TTM — current TTM + 2 prior fiscal years
    if not annual_m.empty:
        st.markdown("### Annual TTM — Current + 2 Prior Years")
        a_fig, quadrant_figs = _build_annual_chart(annual_m, leverage_redline, coverage_redline)
        st.plotly_chart(a_fig, use_container_width=True, config={"displayModeBar": True})
    else:
        st.caption("Annual statements not available from yfinance for this ticker.")

    # Spread snapshot
    st.markdown("### Spread Snapshot")
    _render_spread_snapshot(active_ticker)

    # Peer overlay
    st.markdown("### Peer Overlay")
    _render_peer_overlay(active_ticker, m, adjusted)

    # MD&A liquidity pull
    st.markdown("### MD&A — Liquidity and Capital Resources")
    _render_liquidity_section(active_ticker)

    # PDF one-pager export
    if quadrant_figs:
        st.markdown("---")
        _render_pdf_export(
            active_ticker,
            issuer_row,
            m,
            annual_m,
            quadrant_figs,
        )


# ---------- Helpers ----------


def _issuer_row(ticker: str) -> dict:
    df = db.load_watchlist()
    row = df[df["Ticker"] == ticker]
    if row.empty:
        return {}
    return row.iloc[0].to_dict()


def _render_header(
    ticker: str, issuer_row: dict, source: str, adjusted: bool,
    fmp_error: Optional[str] = None,
) -> None:
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
    import html as _html
    st.markdown(
        f'<div class="summary-card"><p>{_html.escape(summary)}</p></div>',
        unsafe_allow_html=True,
    )


def _render_kpi_row(m: pd.DataFrame) -> None:
    last = m.iloc[-1]
    cols = st.columns(4)
    with cols[0]:
        st.metric("Leverage", _fmt(last["leverage"], "x"), help="Net Debt / TTM EBITDA")
    with cols[1]:
        st.metric("Coverage", _fmt(last["coverage"], "x"), help="TTM EBITDA / TTM Interest")
    with cols[2]:
        st.metric("Net Gearing", _fmt(last["net_gearing"], "%"), help="Net Debt / (Net Debt + Equity)")
    with cols[3]:
        st.metric("Net Debt", _fmt_money(last["net_debt"]), help="Total Debt − Cash − ST Investments")


def _build_quarterly_chart(m: pd.DataFrame) -> go.Figure:
    """Four-panel chart of raw quarterly metrics for the last 5 quarters.

    All values are point-in-time / single-period — no TTM rolling — so every
    quarter has populated data even when only ~5 quarters of history exist.
    """
    x_dates = pd.to_datetime(m["period_end"])
    x_labels = [d.strftime("%b %Y") for d in x_dates]

    fig = make_subplots(
        rows=2, cols=2,
        subplot_titles=(
            "Net Debt",
            "Quarterly EBITDA",
            "Net Gearing %",
            "Cash + ST Investments",
        ),
        vertical_spacing=0.20, horizontal_spacing=0.10,
    )

    fig.add_trace(go.Bar(
        x=x_labels, y=m["net_debt"], name="Net Debt",
        marker_color=theme.AMBER, opacity=0.85,
    ), row=1, col=1)

    fig.add_trace(go.Bar(
        x=x_labels, y=m["ebitda_q"], name="Q EBITDA",
        marker_color=theme.POS, opacity=0.85,
    ), row=1, col=2)

    fig.add_trace(go.Scatter(
        x=x_labels, y=m["net_gearing"], mode="lines+markers", name="Net Gearing",
        line=dict(color=theme.AMBER, width=2), marker=dict(size=8),
    ), row=2, col=1)

    fig.add_trace(go.Bar(
        x=x_labels, y=m["cash"], name="Cash + STI",
        marker_color="#4a90e2", opacity=0.85,
    ), row=2, col=2)

    fig.update_yaxes(title_text="$", row=1, col=1)
    fig.update_yaxes(title_text="$", row=1, col=2)
    fig.update_yaxes(title_text="%", row=2, col=1)
    fig.update_yaxes(title_text="$", row=2, col=2)

    fig.update_layout(
        height=550, showlegend=False,
        margin=dict(l=40, r=40, t=60, b=40),
    )
    return fig


def _build_annual_chart(
    annual_m: pd.DataFrame, leverage_redline: float, coverage_redline: float
) -> tuple[go.Figure, list[go.Figure]]:
    """Four-panel chart of TTM-style metrics across 3 fiscal periods (2 prior
    FYs + Current TTM). Returns the combined figure and a list of 4 standalone
    figures used for PDF export.
    """
    x = annual_m["period_label"].tolist()
    bar_colors = [
        theme.POS if str(lbl).startswith("Current") else theme.TEXT_MUTED
        for lbl in x
    ]

    fig = make_subplots(
        rows=2, cols=2,
        subplot_titles=(
            "Leverage (Net Debt / EBITDA)",
            "Coverage (EBITDA / Interest)",
            "Net Gearing %",
            "EBITDA",
        ),
        vertical_spacing=0.20, horizontal_spacing=0.10,
    )

    fig.add_trace(go.Bar(
        x=x, y=annual_m["leverage"], name="Leverage",
        marker_color=bar_colors,
        text=[_fmt(v, "x") for v in annual_m["leverage"]],
        textposition="outside",
    ), row=1, col=1)
    fig.add_hline(
        y=leverage_redline, line_dash="dash", line_color=theme.NEG,
        annotation_text=f"Redline {leverage_redline:.1f}x",
        annotation_position="top right",
        row=1, col=1,
    )

    fig.add_trace(go.Bar(
        x=x, y=annual_m["coverage"], name="Coverage",
        marker_color=bar_colors,
        text=[_fmt(v, "x") for v in annual_m["coverage"]],
        textposition="outside",
    ), row=1, col=2)
    fig.add_hline(
        y=coverage_redline, line_dash="dash", line_color=theme.NEG,
        annotation_text=f"Redline {coverage_redline:.1f}x",
        annotation_position="top right",
        row=1, col=2,
    )

    fig.add_trace(go.Bar(
        x=x, y=annual_m["net_gearing"], name="Net Gearing",
        marker_color=bar_colors,
        text=[_fmt(v, "%") for v in annual_m["net_gearing"]],
        textposition="outside",
    ), row=2, col=1)

    fig.add_trace(go.Bar(
        x=x, y=annual_m["ebitda_ttm"], name="EBITDA",
        marker_color=bar_colors,
        text=[_fmt_money(v) for v in annual_m["ebitda_ttm"]],
        textposition="outside",
    ), row=2, col=2)

    fig.update_yaxes(title_text="x", row=1, col=1)
    fig.update_yaxes(title_text="x", row=1, col=2)
    fig.update_yaxes(title_text="%", row=2, col=1)
    fig.update_yaxes(title_text="$", row=2, col=2)
    fig.update_layout(
        height=550, showlegend=False,
        margin=dict(l=40, r=40, t=60, b=40),
    )

    quadrant_figs: list[go.Figure] = []
    q1 = go.Figure(go.Bar(x=x, y=annual_m["leverage"], marker_color=bar_colors))
    q1.add_hline(y=leverage_redline, line_dash="dash", line_color=theme.NEG)
    q1.update_layout(title="Leverage", height=250)
    quadrant_figs.append(q1)

    q2 = go.Figure(go.Bar(x=x, y=annual_m["coverage"], marker_color=bar_colors))
    q2.add_hline(y=coverage_redline, line_dash="dash", line_color=theme.NEG)
    q2.update_layout(title="Coverage", height=250)
    quadrant_figs.append(q2)

    q3 = go.Figure(go.Bar(x=x, y=annual_m["net_gearing"], marker_color=bar_colors))
    q3.update_layout(title="Net Gearing %", height=250)
    quadrant_figs.append(q3)

    q4 = go.Figure(go.Bar(x=x, y=annual_m["ebitda_ttm"], marker_color=bar_colors))
    q4.update_layout(title="EBITDA", height=250)
    quadrant_figs.append(q4)

    return fig, quadrant_figs


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
    ticker: str, base_m: pd.DataFrame, adjusted: bool,
) -> None:
    wl = db.load_watchlist()
    candidates = [t for t in wl["Ticker"].tolist() if t and t != ticker]
    selected = st.multiselect(
        "Select up to 5 peers (or type any ticker)", candidates, default=[],
        max_selections=5, key=f"peers_{ticker}",
        accept_new_options=True,
        placeholder="Pick from watchlist or type any ticker",
    )
    selected = [t.strip().upper() for t in selected if t and t.strip()]
    selected = [t for t in selected if t != ticker]
    if not selected:
        return

    fig = make_subplots(
        rows=2, cols=2,
        subplot_titles=(
            "Net Debt", "Quarterly EBITDA",
            "Net Gearing %", "Cash + ST Investments",
        ),
        vertical_spacing=0.20, horizontal_spacing=0.10,
    )

    def _add_series(pm_: pd.DataFrame, name: str, color: str, width: int, dash: str) -> None:
        m_tail = pm_.tail(5)
        x_dates = pd.to_datetime(m_tail["period_end"])
        x_labels = [d.strftime("%b %Y") for d in x_dates]
        line = dict(color=color, width=width)
        if dash:
            line["dash"] = dash
        marker = dict(size=7 if width > 1 else 5)
        for col_name, row, col in (
            ("net_debt", 1, 1),
            ("ebitda_q", 1, 2),
            ("net_gearing", 2, 1),
            ("cash", 2, 2),
        ):
            fig.add_trace(
                go.Scatter(
                    x=x_labels, y=m_tail[col_name],
                    name=name, mode="lines+markers",
                    line=line, marker=marker,
                    legendgroup=name,
                    showlegend=(row == 1 and col == 1),
                ),
                row=row, col=col,
            )

    _add_series(base_m, ticker, theme.POS, 3, "")

    muted_palette = ["#9b9b9b", "#7aa6ff", "#c3a5ff", "#ffb088", "#88e0c5"]
    for i, peer in enumerate(selected):
        try:
            df_peer, _, _ = data.fetch_fundamentals(peer, quarters=16)
            if df_peer.empty:
                continue
            res = metrics.compute(df_peer, adjusted=adjusted)
            pm = res.df
            if pm.empty:
                continue
            color = muted_palette[i % len(muted_palette)]
            _add_series(pm, peer, color, 1, "dot")
        except Exception as e:
            st.warning(f"Could not load peer {peer}: {e}")

    fig.update_yaxes(title_text="$", row=1, col=1)
    fig.update_yaxes(title_text="$", row=1, col=2)
    fig.update_yaxes(title_text="%", row=2, col=1)
    fig.update_yaxes(title_text="$", row=2, col=2)

    fig.update_layout(
        height=560, showlegend=True,
        legend=dict(orientation="h", yanchor="bottom", y=-0.15, xanchor="center", x=0.5),
        margin=dict(l=40, r=40, t=60, b=70),
    )
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
        # Fixed-height scrollable box keeps the text contained — st.text expands
        # to fit content and can overflow into siblings on long sections.
        st.markdown('<div class="verbatim-box">', unsafe_allow_html=True)
        st.text_area(
            "Verbatim",
            value=section[:3000],
            height=320,
            disabled=True,
            label_visibility="collapsed",
            key=f"verbatim_{ticker}",
        )
        st.markdown('</div>', unsafe_allow_html=True)
        if len(section) > 3000:
            cols = st.columns([3, 1])
            with cols[0]:
                st.caption(f"({len(section) - 3000} more chars truncated)")
            with cols[1]:
                st.download_button(
                    "Download full section",
                    section.encode("utf-8"),
                    file_name=f"{ticker}_liquidity.txt",
                    mime="text/plain",
                    key=f"liq_dl_{ticker}",
                )
    st.markdown("**3-bullet AI summary** (grounded only in the text above):")
    summary_md = llm.summarize_liquidity_section(section)
    summary_html = _markdown_to_html(summary_md)
    st.markdown(
        f'<div class="liquidity-summary">{summary_html}</div>',
        unsafe_allow_html=True,
    )


def _render_pdf_export(
    ticker: str, issuer_row: dict, m: pd.DataFrame,
    annual_m: pd.DataFrame, quadrant_figs: list[go.Figure],
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

        # Prefer Current TTM row from annual frame; fall back to last quarterly row.
        if not annual_m.empty:
            ttm = annual_m[annual_m["is_ttm"]]
            last = ttm.iloc[-1] if not ttm.empty else annual_m.iloc[-1]
        elif not m.empty:
            last = m.iloc[-1]
        else:
            last = pd.Series({"leverage": np.nan, "coverage": np.nan, "net_gearing": np.nan})

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


def _markdown_to_html(md: str) -> str:
    """Tiny renderer: bullet lists + **bold** + paragraph breaks. Anything more
    elaborate isn't expected from the 3-bullet summary prompt."""
    import html
    import re

    lines = (md or "").splitlines()
    out: list[str] = []
    in_list = False
    for raw in lines:
        line = raw.rstrip()
        stripped = line.lstrip()
        if stripped.startswith(("- ", "* ", "• ")):
            if not in_list:
                out.append("<ul>")
                in_list = True
            item = html.escape(stripped[2:].strip())
            item = re.sub(r"\*\*(.+?)\*\*", r"<strong>\1</strong>", item)
            out.append(f"<li>{item}</li>")
        elif not stripped:
            if in_list:
                out.append("</ul>")
                in_list = False
        else:
            if in_list:
                out.append("</ul>")
                in_list = False
            para = html.escape(stripped)
            para = re.sub(r"\*\*(.+?)\*\*", r"<strong>\1</strong>", para)
            out.append(f"<p>{para}</p>")
    if in_list:
        out.append("</ul>")
    return "\n".join(out)


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
