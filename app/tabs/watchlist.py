"""Tab 1 — Watchlist Manager.

The watchlist is the source of truth for the ticker dropdown everywhere else.
Replace-on-save semantics for simplicity. Validation hits the data provider
once per ticker on save and flags rows red without blocking the save.
"""
from __future__ import annotations

import io

import pandas as pd
import streamlit as st

from app import data, db


def render() -> None:
    st.subheader("Watchlist Manager")
    st.caption("Edit, add, and import tickers. Only Active rows populate the sidebar dropdown.")

    df = db.load_watchlist()

    edited = st.data_editor(
        df,
        key="watchlist_editor",
        num_rows="dynamic",
        use_container_width=True,
        column_config={
            "Ticker": st.column_config.TextColumn("Ticker", required=True),
            "Issuer Name": st.column_config.TextColumn("Issuer Name"),
            "Sector": st.column_config.TextColumn("Sector"),
            "Region": st.column_config.TextColumn("Region"),
            "Internal Rating": st.column_config.TextColumn("Internal Rating"),
            "Notes": st.column_config.TextColumn(
                "Notes",
                help="Per-ticker overrides. Example: leverage_redline=4.5; coverage_redline=4.0",
            ),
            "Active": st.column_config.CheckboxColumn("Active"),
            "Data OK": st.column_config.CheckboxColumn("Data OK", disabled=True),
        },
    )

    col1, col2, col3 = st.columns([1, 1, 2])
    with col1:
        if st.button("Save & Validate", type="primary"):
            _save_and_validate(edited)
            st.success("Watchlist saved.")
            st.rerun()
    with col2:
        csv_bytes = edited.to_csv(index=False).encode("utf-8")
        st.download_button(
            "Export CSV", data=csv_bytes, file_name="watchlist.csv", mime="text/csv",
        )
    with col3:
        with st.expander("Bulk import from CSV"):
            pasted = st.text_area("Paste CSV contents", height=120)
            if st.button("Import"):
                if pasted.strip():
                    try:
                        new_df = pd.read_csv(io.StringIO(pasted))
                        db.save_watchlist(new_df)
                        st.success(f"Imported {len(new_df)} rows.")
                        st.rerun()
                    except Exception as e:
                        st.error(f"Could not parse CSV: {e}")

    flagged = edited[edited["Data OK"] == False]  # noqa: E712
    if not flagged.empty:
        st.warning(
            "These tickers returned no fundamentals on last validation: "
            + ", ".join(flagged["Ticker"].astype(str).tolist())
        )


def _save_and_validate(df: pd.DataFrame) -> None:
    """Persist, then probe each ticker and mark Data OK."""
    db.save_watchlist(df)
    saved = db.load_watchlist()
    for tk in saved["Ticker"]:
        if not tk:
            continue
        try:
            fund_df, source, _ = data.fetch_fundamentals(str(tk).upper(), quarters=2)
            ok = source != "none" and not fund_df.empty
        except Exception:
            ok = False
        db.set_data_ok(str(tk).upper(), ok)
