"""Persistence: watchlist, agency ratings, cached extracted triggers.

Single SQLite file (`app.db`) in the working directory. Created and seeded on
first run.
"""
from __future__ import annotations

from datetime import datetime
from pathlib import Path
from typing import Iterable

import pandas as pd
from sqlalchemy import (
    Boolean,
    Column,
    DateTime,
    Float,
    Integer,
    String,
    Text,
    create_engine,
    select,
)
from sqlalchemy.orm import DeclarativeBase, Session

DB_PATH = Path("app.db")
ENGINE = create_engine(f"sqlite:///{DB_PATH}", future=True)


class Base(DeclarativeBase):
    pass


class WatchlistRow(Base):
    __tablename__ = "watchlist"
    ticker = Column(String, primary_key=True)
    issuer_name = Column(String, default="")
    sector = Column(String, default="")
    region = Column(String, default="")
    internal_rating = Column(String, default="")
    notes = Column(Text, default="")
    active = Column(Boolean, default=True)
    data_ok = Column(Boolean, default=True)  # set False if FMP/yfinance returned nothing
    updated_at = Column(DateTime, default=datetime.utcnow)


class AgencyRating(Base):
    __tablename__ = "ratings"
    id = Column(Integer, primary_key=True, autoincrement=True)
    ticker = Column(String, index=True)
    agency = Column(String)  # S&P | Moody's | Fitch
    rating = Column(String, default="")
    outlook = Column(String, default="")
    last_action_date = Column(String, default="")
    updated_at = Column(DateTime, default=datetime.utcnow)


class CachedTrigger(Base):
    """Persists extracted triggers per ticker so the user doesn't re-upload after a refresh."""
    __tablename__ = "triggers"
    id = Column(Integer, primary_key=True, autoincrement=True)
    ticker = Column(String, index=True)
    agency = Column(String)
    direction = Column(String)
    metric = Column(String)
    operator = Column(String)
    threshold = Column(Float, nullable=True)
    unit = Column(String, default="x")
    sustained_period = Column(String, default="")
    qualitative = Column(Boolean, default=False)
    verbatim_quote = Column(Text, default="")
    page_number = Column(Integer, nullable=True)
    confidence = Column(Float, default=0.0)
    extracted_at = Column(DateTime, default=datetime.utcnow)


# Default seed list — mix of sectors per spec.
SEED = [
    ("AAPL", "Apple Inc.", "Technology", "US", "A1"),
    ("MSFT", "Microsoft Corp.", "Technology", "US", "A1"),
    ("GOOGL", "Alphabet Inc.", "Technology", "US", "A1"),
    ("JPM", "JPMorgan Chase & Co.", "Financials", "US", "A2"),
    ("BAC", "Bank of America Corp.", "Financials", "US", "A3"),
    ("XOM", "Exxon Mobil Corp.", "Energy", "US", "A2"),
    ("CVX", "Chevron Corp.", "Energy", "US", "A2"),
    ("BMY", "Bristol-Myers Squibb Co.", "Healthcare", "US", "A2"),
    ("PFE", "Pfizer Inc.", "Healthcare", "US", "A1"),
    ("T", "AT&T Inc.", "Telecoms", "US", "BBB+"),
]


def init_db() -> None:
    Base.metadata.create_all(ENGINE)
    with Session(ENGINE) as s:
        existing = s.execute(select(WatchlistRow)).first()
        if existing is None:
            for tk, name, sector, region, rating in SEED:
                s.add(
                    WatchlistRow(
                        ticker=tk,
                        issuer_name=name,
                        sector=sector,
                        region=region,
                        internal_rating=rating,
                        notes="",
                        active=True,
                    )
                )
            s.commit()


# ---------- Watchlist ----------


def load_watchlist() -> pd.DataFrame:
    with Session(ENGINE) as s:
        rows = s.execute(select(WatchlistRow)).scalars().all()
    return pd.DataFrame(
        [
            {
                "Ticker": r.ticker,
                "Issuer Name": r.issuer_name,
                "Sector": r.sector,
                "Region": r.region,
                "Internal Rating": r.internal_rating,
                "Notes": r.notes or "",
                "Active": bool(r.active),
                "Data OK": bool(r.data_ok),
            }
            for r in rows
        ]
    )


def save_watchlist(df: pd.DataFrame) -> None:
    """Replace-on-save semantics. Simpler than diffing for a small table."""
    with Session(ENGINE) as s:
        s.query(WatchlistRow).delete()
        for _, row in df.iterrows():
            tk = str(row.get("Ticker", "")).strip().upper()
            if not tk:
                continue
            s.add(
                WatchlistRow(
                    ticker=tk,
                    issuer_name=str(row.get("Issuer Name", "") or ""),
                    sector=str(row.get("Sector", "") or ""),
                    region=str(row.get("Region", "") or ""),
                    internal_rating=str(row.get("Internal Rating", "") or ""),
                    notes=str(row.get("Notes", "") or ""),
                    active=bool(row.get("Active", True)),
                    data_ok=bool(row.get("Data OK", True)),
                )
            )
        s.commit()


def active_tickers() -> list[str]:
    with Session(ENGINE) as s:
        rows = s.execute(
            select(WatchlistRow).where(WatchlistRow.active == True)  # noqa: E712
        ).scalars().all()
    return [r.ticker for r in rows]


def get_notes(ticker: str) -> str:
    with Session(ENGINE) as s:
        row = s.get(WatchlistRow, ticker)
        return row.notes if row else ""


def set_data_ok(ticker: str, ok: bool) -> None:
    with Session(ENGINE) as s:
        row = s.get(WatchlistRow, ticker)
        if row:
            row.data_ok = ok
            s.commit()


# ---------- Ratings ----------


def load_ratings(ticker: str) -> pd.DataFrame:
    with Session(ENGINE) as s:
        rows = s.execute(
            select(AgencyRating).where(AgencyRating.ticker == ticker)
        ).scalars().all()
    if not rows:
        return pd.DataFrame(
            {
                "Agency": ["S&P", "Moody's", "Fitch"],
                "Rating": ["", "", ""],
                "Outlook": ["", "", ""],
                "Last Action Date": ["", "", ""],
            }
        )
    return pd.DataFrame(
        [
            {
                "Agency": r.agency,
                "Rating": r.rating or "",
                "Outlook": r.outlook or "",
                "Last Action Date": r.last_action_date or "",
            }
            for r in rows
        ]
    )


def save_ratings(ticker: str, df: pd.DataFrame) -> None:
    with Session(ENGINE) as s:
        s.query(AgencyRating).filter(AgencyRating.ticker == ticker).delete()
        for _, row in df.iterrows():
            agency = str(row.get("Agency", "")).strip()
            if not agency:
                continue
            s.add(
                AgencyRating(
                    ticker=ticker,
                    agency=agency,
                    rating=str(row.get("Rating", "") or ""),
                    outlook=str(row.get("Outlook", "") or ""),
                    last_action_date=str(row.get("Last Action Date", "") or ""),
                )
            )
        s.commit()


# ---------- Triggers ----------


def save_triggers(ticker: str, triggers: Iterable[dict]) -> None:
    with Session(ENGINE) as s:
        s.query(CachedTrigger).filter(CachedTrigger.ticker == ticker).delete()
        for t in triggers:
            s.add(
                CachedTrigger(
                    ticker=ticker,
                    agency=t.get("agency", ""),
                    direction=t.get("direction", ""),
                    metric=t.get("metric", ""),
                    operator=t.get("operator", ""),
                    threshold=t.get("threshold"),
                    unit=t.get("unit", "x"),
                    sustained_period=t.get("sustained_period") or "",
                    qualitative=bool(t.get("qualitative", False)),
                    verbatim_quote=t.get("verbatim_quote", ""),
                    page_number=t.get("page_number"),
                    confidence=float(t.get("confidence", 0.0) or 0.0),
                )
            )
        s.commit()


def load_triggers(ticker: str) -> list[dict]:
    with Session(ENGINE) as s:
        rows = s.execute(
            select(CachedTrigger).where(CachedTrigger.ticker == ticker)
        ).scalars().all()
    return [
        {
            "agency": r.agency,
            "direction": r.direction,
            "metric": r.metric,
            "operator": r.operator,
            "threshold": r.threshold,
            "unit": r.unit,
            "sustained_period": r.sustained_period,
            "qualitative": r.qualitative,
            "verbatim_quote": r.verbatim_quote,
            "page_number": r.page_number,
            "confidence": r.confidence,
        }
        for r in rows
    ]
