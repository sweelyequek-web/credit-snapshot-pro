"""Tab 3 — Agency Watch.

Editable ratings table + PDF-driven trigger extraction with direction-aware
headroom and RAG coloring.
"""
from __future__ import annotations

from typing import Optional

import numpy as np
import pandas as pd
import streamlit as st

from app import data, db, metrics, theme, triggers as trig


def render(active_ticker: str, uploaded_pdf, adjusted: bool) -> None:
    if not active_ticker:
        st.warning("Pick a ticker from the sidebar.")
        return

    st.subheader(f"Agency Watch — {active_ticker}")

    # ---------- Ratings table ----------
    st.markdown("#### Current Ratings")
    st.caption("No reliable free API for live ratings. Maintain manually below — values persist.")
    ratings = db.load_ratings(active_ticker)

    if ratings.empty or ratings[["Rating", "Outlook", "Last Action Date"]].fillna("").eq("").all().all():
        st.info(
            "No rated debt on file for this issuer. "
            "Add ratings manually if applicable."
        )

    edited = st.data_editor(
        ratings,
        key=f"ratings_editor_{active_ticker}",
        use_container_width=True,
        num_rows="dynamic",
        column_config={
            "Outlook": st.column_config.SelectboxColumn(
                "Outlook",
                options=["", "Stable", "Positive", "Negative", "Developing", "Watch Pos", "Watch Neg"],
            ),
        },
    )
    if st.button("Save ratings"):
        db.save_ratings(active_ticker, edited)
        st.success("Ratings saved.")

    # ---------- Triggers ----------
    st.markdown("#### Rating Triggers")

    if uploaded_pdf is not None:
        if st.button("Extract triggers from uploaded PDF", type="primary"):
            with st.spinner("Locating sensitivities section and extracting..."):
                pdf_bytes = uploaded_pdf.getvalue()
                extracted, err = trig.extract_triggers_from_pdf(pdf_bytes)
            if err:
                st.error(err)
            elif not extracted:
                st.warning(
                    "Sensitivities section located but no structured triggers extracted. "
                    "The section may be entirely qualitative, or the LLM key may not be set."
                )
            else:
                db.save_triggers(active_ticker, extracted)
                st.success(f"Extracted {len(extracted)} trigger(s).")
                st.rerun()
    else:
        st.caption("Upload an agency PDF in the sidebar to extract triggers.")

    cached = db.load_triggers(active_ticker)
    if not cached:
        st.info("No triggers cached for this ticker yet.")
        return

    # Compute current values for each trigger.
    latest_metrics = _latest_metrics(active_ticker, adjusted)

    rows = []
    for t in cached:
        current = trig.map_metric_to_current(t["metric"], latest_metrics)
        if t.get("qualitative") or t.get("threshold") is None:
            headroom = None
            color = "amber"
        else:
            headroom = trig.headroom_pct(current, t["threshold"], t["operator"])
            color = trig.rag_color(headroom)
        rows.append({**t, "current": current, "headroom": headroom, "color": color})

    _render_triggers_table(rows)


# ---------- Helpers ----------


def _latest_metrics(ticker: str, adjusted: bool) -> dict:
    fund_df, _, _ = data.fetch_fundamentals(ticker, quarters=12)
    if fund_df.empty:
        return {}
    res = metrics.compute(fund_df, adjusted=adjusted)
    if res.df.empty:
        return {}
    last = res.df.iloc[-1]
    return {
        "leverage": _safe_float(last.get("leverage")),
        "coverage": _safe_float(last.get("coverage")),
        "net_gearing": _safe_float(last.get("net_gearing")),
    }


def _render_triggers_table(rows: list[dict]) -> None:
    """Custom row-by-row rendering so each row gets a 'View source' expander."""
    widths = [1.0, 1.1, 2.0, 0.5, 0.9, 0.9, 1.0, 0.5]
    header_cols = st.columns(widths)
    headers = ["Agency", "Direction", "Metric", "Op", "Threshold", "Current", "Headroom", "RAG"]
    for col, h in zip(header_cols, headers):
        col.markdown(f"**{h}**")

    for r in rows:
        st.markdown('<div class="triggers-row">', unsafe_allow_html=True)
        cols = st.columns(widths)
        cols[0].write(r["agency"])
        cols[1].write(r["direction"])
        cols[2].write(r["metric"])
        cols[3].write(r["operator"])
        cols[4].write(_fmt_threshold(r["threshold"], r.get("unit", "x")))
        cols[5].write(_fmt_value(r["current"], r.get("unit", "x")))
        cols[6].write(_fmt_pct(r["headroom"]))
        cols[7].markdown(_rag_dot(r["color"]), unsafe_allow_html=True)
        with st.expander(f"View source · page {r.get('page_number') or '?'}"):
            st.markdown(f"> {r.get('verbatim_quote', '—')}")
            if r.get("sustained_period"):
                st.caption(f"Sustained period: {r['sustained_period']}")
            if r.get("qualitative"):
                st.caption("Qualitative trigger — no numeric headroom computed.")
            st.caption(f"Confidence: {r.get('confidence', 0.0):.2f}")
        st.markdown('</div>', unsafe_allow_html=True)


def _rag_dot(color: str) -> str:
    color_map = {"green": theme.POS, "amber": theme.AMBER, "red": theme.NEG}
    c = color_map.get(color, theme.AMBER)
    return f"<span style='color:{c}; font-size:20px;'>●</span>"


def _fmt_threshold(v: Optional[float], unit: str) -> str:
    if v is None:
        return "qual."
    return f"{float(v):.2f}{unit}"


def _fmt_value(v: Optional[float], unit: str) -> str:
    if v is None or (isinstance(v, float) and (np.isnan(v) or np.isinf(v))):
        return "—"
    return f"{float(v):.2f}{unit}"


def _fmt_pct(v: Optional[float]) -> str:
    if v is None:
        return "—"
    return f"{float(v):+.1f}%"


def _safe_float(v) -> Optional[float]:
    try:
        f = float(v)
        if np.isnan(f) or np.isinf(f):
            return None
        return f
    except (TypeError, ValueError):
        return None
