"""Credit metric calculations.

All math is point-in-time net debt against trailing-four-quarter (TTM) flow
metrics, per the spec's data contract. Missing fields stay missing — never
interpolated.

The Reported vs. Adjusted toggle applies a documented set of adjustments and
returns the list of what was applied so the UI can surface it.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Optional

import numpy as np
import pandas as pd


@dataclass
class CreditMetricsResult:
    df: pd.DataFrame  # one row per quarter, ascending by date for charting
    adjustments_applied: list[str] = field(default_factory=list)
    estimated_fields: list[str] = field(default_factory=list)  # tooltip flags


# ---------- Field reconstructions ----------


def _reconstruct_interest_expense(df: pd.DataFrame, est_flags: list[str]) -> pd.Series:
    """If interestExpense is missing, reconstruct as ebit − pretaxIncome."""
    ie = pd.to_numeric(df.get("interestExpense"), errors="coerce")
    if ie is None or ie.isna().all():
        ebit = pd.to_numeric(df.get("ebit"), errors="coerce")
        ptx = pd.to_numeric(df.get("pretaxIncome"), errors="coerce")
        if ebit is not None and ptx is not None:
            est_flags.append("interestExpense reconstructed as EBIT − Pretax Income")
            return ebit - ptx
    return ie


def _ebitda(df: pd.DataFrame, est_flags: list[str]) -> pd.Series:
    """Operating income + D&A — spec doesn't take reported EBITDA from FMP."""
    oi = pd.to_numeric(df.get("operatingIncome"), errors="coerce")
    da = pd.to_numeric(df.get("depreciationAndAmortization"), errors="coerce").fillna(0)
    if oi is None:
        return pd.Series(np.nan, index=df.index)
    return oi + da


# ---------- Adjustments ----------

ADJ_LEASE_MULTIPLIER = 8.0
ADJ_HYBRID_DEBT_FRACTION = 0.5


def _apply_adjustments(df: pd.DataFrame, adjustments_log: list[str]) -> pd.DataFrame:
    """Returns a copy of df with adjustment columns folded in.

    Real adjustment data (rent expense, pension underfunding, hybrid balances)
    is rarely in the standard fundamentals feed. We apply them only when the
    inputs are present and log every one we apply.
    """
    out = df.copy()

    rent = pd.to_numeric(out.get("operatingLeaseRentExpense", pd.Series(np.nan, index=out.index)), errors="coerce")
    if not rent.isna().all():
        capitalized_leases = rent * ADJ_LEASE_MULTIPLIER
        out["__adj_lease_debt"] = capitalized_leases.fillna(0)
        adjustments_log.append(
            f"Operating leases capitalized at {ADJ_LEASE_MULTIPLIER:.0f}x rent expense"
        )
    else:
        out["__adj_lease_debt"] = 0
        adjustments_log.append(
            "Operating lease capitalization skipped — rent expense not available in feed; capital lease line already on balance sheet"
        )

    pension = pd.to_numeric(out.get("unfundedPensionObligations", pd.Series(np.nan, index=out.index)), errors="coerce")
    if not pension.isna().all():
        out["__adj_pension_debt"] = pension.fillna(0)
        adjustments_log.append("Unfunded pension obligations added to debt")
    else:
        out["__adj_pension_debt"] = 0

    hybrid = pd.to_numeric(out.get("hybridSecurities", pd.Series(np.nan, index=out.index)), errors="coerce")
    if not hybrid.isna().all():
        out["__adj_hybrid_debt"] = hybrid.fillna(0) * ADJ_HYBRID_DEBT_FRACTION
        adjustments_log.append(
            f"{int(ADJ_HYBRID_DEBT_FRACTION * 100)}% of hybrid securities treated as debt"
        )
    else:
        out["__adj_hybrid_debt"] = 0

    return out


# ---------- Main computation ----------


def compute(df_raw: pd.DataFrame, adjusted: bool = False) -> CreditMetricsResult:
    """Build the per-quarter metrics frame.

    Output columns:
        period_end, net_debt, total_debt, cash, total_equity, ebitda_q,
        interest_q, ebitda_ttm, interest_ttm, leverage, coverage, net_gearing,
        ebitda_qoq_growth, revenue
    """
    if df_raw.empty:
        return CreditMetricsResult(df=pd.DataFrame())

    df = df_raw.sort_index(ascending=True).copy()  # ascending for rolling
    est_flags: list[str] = []
    adj_log: list[str] = []

    if adjusted:
        df = _apply_adjustments(df, adj_log)
    else:
        df["__adj_lease_debt"] = 0
        df["__adj_pension_debt"] = 0
        df["__adj_hybrid_debt"] = 0

    short_debt = pd.to_numeric(df.get("shortTermDebt"), errors="coerce").fillna(0)
    long_debt = pd.to_numeric(df.get("longTermDebt"), errors="coerce").fillna(0)
    cap_lease = pd.to_numeric(df.get("capitalLeaseObligations"), errors="coerce").fillna(0)
    cash = pd.to_numeric(df.get("cashAndCashEquivalents"), errors="coerce").fillna(0)
    sti = pd.to_numeric(df.get("shortTermInvestments"), errors="coerce").fillna(0)
    equity = pd.to_numeric(df.get("totalEquity"), errors="coerce")

    total_debt = (
        short_debt + long_debt + cap_lease
        + df["__adj_lease_debt"] + df["__adj_pension_debt"] + df["__adj_hybrid_debt"]
    )
    net_debt = total_debt - cash - sti

    ebitda_q = _ebitda(df, est_flags)
    interest_q = _reconstruct_interest_expense(df, est_flags)

    # TTM = trailing 4 quarters. min_periods=4 so we don't show TTM until we have a full year.
    ebitda_ttm = ebitda_q.rolling(window=4, min_periods=4).sum()
    interest_ttm = interest_q.rolling(window=4, min_periods=4).sum() if interest_q is not None else None

    leverage = net_debt / ebitda_ttm.replace(0, np.nan)
    if interest_ttm is not None:
        coverage = ebitda_ttm / interest_ttm.replace(0, np.nan).abs()
    else:
        coverage = pd.Series(np.nan, index=df.index)

    denom = (net_debt + equity).replace(0, np.nan)
    net_gearing = net_debt / denom * 100.0  # %

    ebitda_qoq = ebitda_q.pct_change() * 100.0

    out = pd.DataFrame({
        "period_end": df.index,
        "net_debt": net_debt.values,
        "total_debt": total_debt.values,
        "cash": (cash + sti).values,
        "total_equity": equity.values,
        "ebitda_q": ebitda_q.values,
        "interest_q": interest_q.values if interest_q is not None else np.nan,
        "ebitda_ttm": ebitda_ttm.values,
        "interest_ttm": interest_ttm.values if interest_ttm is not None else np.nan,
        "leverage": leverage.values,
        "coverage": coverage.values,
        "net_gearing": net_gearing.values,
        "ebitda_qoq_growth": ebitda_qoq.values,
        "revenue": pd.to_numeric(df.get("revenue", pd.Series(np.nan, index=df.index)), errors="coerce").values,
    })
    return CreditMetricsResult(df=out, adjustments_applied=adj_log, estimated_fields=est_flags)


def compute_annual(
    annual_df: pd.DataFrame,
    quarterly_result: Optional[CreditMetricsResult] = None,
    adjusted: bool = False,
    years: int = 2,
) -> pd.DataFrame:
    """Build annual-period metrics. Returns up to `years` prior fiscal years
    plus a synthesized 'Current TTM' row stitched from the latest quarterly
    rolling window when quarterly_result is provided and has TTM data.

    Each row's full-year EBITDA / interest already represent 12 months, so no
    rolling is needed for the prior-year rows. The TTM row uses
    quarterly_result.df's last fully-populated row.

    Output columns mirror the quarterly compute(): leverage, coverage,
    net_gearing, ebitda_ttm, interest_ttm, net_debt, period_label.
    """
    rows: list[dict] = []

    if not annual_df.empty:
        df = annual_df.sort_index(ascending=True).copy()
        if adjusted:
            df = _apply_adjustments(df, [])
        else:
            df["__adj_lease_debt"] = 0
            df["__adj_pension_debt"] = 0
            df["__adj_hybrid_debt"] = 0

        short_debt = pd.to_numeric(df.get("shortTermDebt"), errors="coerce").fillna(0)
        long_debt = pd.to_numeric(df.get("longTermDebt"), errors="coerce").fillna(0)
        cap_lease = pd.to_numeric(df.get("capitalLeaseObligations"), errors="coerce").fillna(0)
        cash = pd.to_numeric(df.get("cashAndCashEquivalents"), errors="coerce").fillna(0)
        sti = pd.to_numeric(df.get("shortTermInvestments"), errors="coerce").fillna(0)
        equity = pd.to_numeric(df.get("totalEquity"), errors="coerce")
        total_debt = (
            short_debt + long_debt + cap_lease
            + df["__adj_lease_debt"] + df["__adj_pension_debt"] + df["__adj_hybrid_debt"]
        )
        net_debt = total_debt - cash - sti

        ebitda_y = _ebitda(df, [])
        interest_y = _reconstruct_interest_expense(df, [])

        leverage = net_debt / ebitda_y.replace(0, np.nan)
        coverage = (
            ebitda_y / interest_y.replace(0, np.nan).abs()
            if interest_y is not None else pd.Series(np.nan, index=df.index)
        )
        denom = (net_debt + equity).replace(0, np.nan)
        net_gearing = net_debt / denom * 100.0

        for idx in df.index:
            rows.append({
                "period_label": idx.strftime("FY%Y"),
                "period_end": idx,
                "is_ttm": False,
                "net_debt": float(net_debt.loc[idx]) if pd.notna(net_debt.loc[idx]) else np.nan,
                "ebitda_ttm": float(ebitda_y.loc[idx]) if pd.notna(ebitda_y.loc[idx]) else np.nan,
                "interest_ttm": float(interest_y.loc[idx]) if interest_y is not None and pd.notna(interest_y.loc[idx]) else np.nan,
                "leverage": float(leverage.loc[idx]) if pd.notna(leverage.loc[idx]) else np.nan,
                "coverage": float(coverage.loc[idx]) if pd.notna(coverage.loc[idx]) else np.nan,
                "net_gearing": float(net_gearing.loc[idx]) if pd.notna(net_gearing.loc[idx]) else np.nan,
            })

    rows = rows[-years:] if years > 0 else rows

    if quarterly_result is not None and not quarterly_result.df.empty:
        qm = quarterly_result.df
        valid = qm.dropna(subset=["leverage"])
        if not valid.empty:
            last = valid.iloc[-1]
            rows.append({
                "period_label": "Current TTM",
                "period_end": pd.to_datetime(last["period_end"]),
                "is_ttm": True,
                "net_debt": _safe_float(last.get("net_debt")),
                "ebitda_ttm": _safe_float(last.get("ebitda_ttm")),
                "interest_ttm": _safe_float(last.get("interest_ttm")),
                "leverage": _safe_float(last.get("leverage")),
                "coverage": _safe_float(last.get("coverage")),
                "net_gearing": _safe_float(last.get("net_gearing")),
            })

    return pd.DataFrame(rows)


def _safe_float(v) -> float:
    try:
        f = float(v)
        if np.isnan(f) or np.isinf(f):
            return np.nan
        return f
    except (TypeError, ValueError):
        return np.nan


def parse_redline(notes: str, key: str, default: float) -> float:
    """Parse `key=value` tokens out of the watchlist Notes field.

    Example: notes='leverage_redline=4.5; coverage_redline=4.0' → 4.5 for
    'leverage_redline'.
    """
    if not notes:
        return default
    for token in notes.replace(",", ";").split(";"):
        if "=" in token:
            k, v = token.split("=", 1)
            if k.strip().lower() == key.lower():
                try:
                    return float(v.strip())
                except ValueError:
                    return default
    return default


def latest_value(df: pd.DataFrame, col: str) -> Optional[float]:
    if df.empty or col not in df.columns:
        return None
    s = pd.to_numeric(df[col], errors="coerce").dropna()
    return float(s.iloc[-1]) if not s.empty else None
