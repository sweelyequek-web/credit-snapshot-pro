"""Fundamentals data layer.

Primary: Financial Modeling Prep (better field coverage for credit work).
Fallback: yfinance — same shape, translated from yfinance's column names.

Returns a long-form DataFrame with one row per quarter, columns matching the
FMP field names listed in the spec. `metrics.py` consumes this.
"""
from __future__ import annotations

import os
from datetime import datetime
from typing import Optional

import pandas as pd
import requests
import streamlit as st

FMP_BASE = "https://financialmodelingprep.com/api/v3"

REQUIRED_FIELDS = [
    "shortTermDebt",
    "longTermDebt",
    "capitalLeaseObligations",
    "cashAndCashEquivalents",
    "shortTermInvestments",
    "totalEquity",
    "operatingIncome",
    "depreciationAndAmortization",
    "interestExpense",
    "ebit",
    "pretaxIncome",
]


def _fmp_key() -> Optional[str]:
    return os.environ.get("FMP_API_KEY") or None


@st.cache_data(ttl=3600, show_spinner=False)
def fetch_fundamentals(ticker: str, quarters: int = 12) -> tuple[pd.DataFrame, str]:
    """Return (df, source) where source ∈ {"fmp", "yfinance", "none"}.

    df is indexed by period-end date (descending), columns include every entry
    from REQUIRED_FIELDS plus a `revenue` column when available. Missing fields
    are NaN — never interpolated.
    """
    df = _try_fmp(ticker, quarters)
    if df is not None and not df.empty:
        return df, "fmp"
    df = _try_yfinance(ticker, quarters)
    if df is not None and not df.empty:
        return df, "yfinance"
    return pd.DataFrame(), "none"


def _try_fmp(ticker: str, quarters: int) -> Optional[pd.DataFrame]:
    key = _fmp_key()
    if not key:
        return None
    try:
        bs_url = f"{FMP_BASE}/balance-sheet-statement/{ticker}?period=quarter&limit={quarters}&apikey={key}"
        is_url = f"{FMP_BASE}/income-statement/{ticker}?period=quarter&limit={quarters}&apikey={key}"
        bs = requests.get(bs_url, timeout=20).json()
        is_ = requests.get(is_url, timeout=20).json()
        if not isinstance(bs, list) or not isinstance(is_, list) or not bs or not is_:
            return None
        bs_df = pd.DataFrame(bs).set_index("date")
        is_df = pd.DataFrame(is_).set_index("date")
        df = bs_df.join(is_df, how="outer", lsuffix="_bs", rsuffix="_is")
        df.index = pd.to_datetime(df.index)
        df = df.sort_index(ascending=False)
        # Ensure every required field exists, even if NaN-filled.
        for f in REQUIRED_FIELDS:
            if f not in df.columns:
                df[f] = pd.NA
        if "revenue" not in df.columns:
            df["revenue"] = pd.NA
        return df
    except Exception:
        return None


def _try_yfinance(ticker: str, quarters: int) -> Optional[pd.DataFrame]:
    """yfinance translation. Column names differ; we map onto FMP-style names."""
    try:
        import yfinance as yf
    except ImportError:
        return None
    try:
        t = yf.Ticker(ticker)
        bs = t.quarterly_balance_sheet
        is_ = t.quarterly_financials
        if bs is None or is_ is None or bs.empty or is_.empty:
            return None
        # yfinance returns rows = items, cols = dates. Transpose.
        bs_t = bs.T
        is_t = is_.T

        def col(df: pd.DataFrame, *candidates: str) -> pd.Series:
            for c in candidates:
                if c in df.columns:
                    return df[c]
            return pd.Series(pd.NA, index=df.index)

        out = pd.DataFrame(index=bs_t.index)
        out["shortTermDebt"] = col(bs_t, "Current Debt", "Short Long Term Debt")
        out["longTermDebt"] = col(bs_t, "Long Term Debt", "Long Term Debt And Capital Lease Obligation")
        out["capitalLeaseObligations"] = col(
            bs_t, "Capital Lease Obligations", "Long Term Capital Lease Obligation"
        ).fillna(0)
        out["cashAndCashEquivalents"] = col(bs_t, "Cash And Cash Equivalents", "Cash")
        out["shortTermInvestments"] = col(bs_t, "Other Short Term Investments", "Short Term Investments").fillna(0)
        out["totalEquity"] = col(bs_t, "Stockholders Equity", "Total Equity Gross Minority Interest")

        is_aligned = is_t.reindex(bs_t.index)
        out["operatingIncome"] = col(is_aligned, "Operating Income", "Operating Revenue")
        out["depreciationAndAmortization"] = col(
            is_aligned, "Reconciled Depreciation", "Depreciation And Amortization In Income Statement"
        ).fillna(0)
        out["interestExpense"] = col(is_aligned, "Interest Expense", "Interest Expense Non Operating")
        out["ebit"] = col(is_aligned, "EBIT", "Operating Income")
        out["pretaxIncome"] = col(is_aligned, "Pretax Income", "Income Before Tax")
        out["revenue"] = col(is_aligned, "Total Revenue", "Operating Revenue")
        out.index = pd.to_datetime(out.index)
        out = out.sort_index(ascending=False).head(quarters)
        # Coerce to numeric — yfinance occasionally returns objects.
        for c in out.columns:
            out[c] = pd.to_numeric(out[c], errors="coerce")
        return out
    except Exception:
        return None


def latest_period_end(df: pd.DataFrame) -> str:
    if df.empty:
        return ""
    return df.index[0].strftime("%Y-%m-%d")


def now_iso() -> str:
    return datetime.utcnow().strftime("%Y-%m-%d %H:%M UTC")
