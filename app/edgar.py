"""SEC EDGAR pull for the MD&A 'Liquidity and Capital Resources' section.

Best-effort extraction from the most recent 10-Q / 10-K. EDGAR is free but
requires a User-Agent header. Returns the verbatim section text.
"""
from __future__ import annotations

import re
from typing import Optional

import requests
import streamlit as st

USER_AGENT = "Credit Snapshot Pro research@example.com"
EDGAR_HEADERS = {"User-Agent": USER_AGENT, "Accept-Encoding": "gzip, deflate"}


@st.cache_data(ttl=86400, show_spinner=False)
def fetch_liquidity_section(ticker: str) -> tuple[str, str]:
    """Returns (section_text, filing_url). Empty strings on failure."""
    cik = _resolve_cik(ticker)
    if not cik:
        return "", ""
    accession_url = _latest_filing_doc_url(cik)
    if not accession_url:
        return "", ""
    try:
        r = requests.get(accession_url, headers=EDGAR_HEADERS, timeout=30)
        if r.status_code != 200:
            return "", accession_url
        text = _strip_html(r.text)
        section = _slice_liquidity(text)
        return section, accession_url
    except Exception:
        return "", ""


def _resolve_cik(ticker: str) -> Optional[str]:
    try:
        r = requests.get(
            "https://www.sec.gov/files/company_tickers.json",
            headers=EDGAR_HEADERS,
            timeout=20,
        )
        if r.status_code != 200:
            return None
        for _, row in r.json().items():
            if row.get("ticker", "").upper() == ticker.upper():
                return f"{int(row['cik_str']):010d}"
    except Exception:
        return None
    return None


def _latest_filing_doc_url(cik: str) -> Optional[str]:
    try:
        r = requests.get(
            f"https://data.sec.gov/submissions/CIK{cik}.json",
            headers=EDGAR_HEADERS,
            timeout=20,
        )
        if r.status_code != 200:
            return None
        recent = r.json().get("filings", {}).get("recent", {})
        forms = recent.get("form", [])
        accessions = recent.get("accessionNumber", [])
        primaries = recent.get("primaryDocument", [])
        for form, acc, primary in zip(forms, accessions, primaries):
            if form in ("10-Q", "10-K"):
                acc_clean = acc.replace("-", "")
                return (
                    f"https://www.sec.gov/Archives/edgar/data/{int(cik)}/"
                    f"{acc_clean}/{primary}"
                )
    except Exception:
        return None
    return None


def _strip_html(html: str) -> str:
    no_script = re.sub(r"<script[^>]*>.*?</script>", " ", html, flags=re.DOTALL | re.IGNORECASE)
    no_style = re.sub(r"<style[^>]*>.*?</style>", " ", no_script, flags=re.DOTALL | re.IGNORECASE)
    text = re.sub(r"<[^>]+>", " ", no_style)
    text = re.sub(r"&nbsp;", " ", text)
    text = re.sub(r"&amp;", "&", text)
    text = re.sub(r"\s+", " ", text)
    return text.strip()


def _slice_liquidity(text: str) -> str:
    """Find the 'Liquidity and Capital Resources' header and grab ~6000 chars after."""
    m = re.search(r"liquidity\s+and\s+capital\s+resources", text, re.IGNORECASE)
    if not m:
        return ""
    start = m.start()
    # End at next major MD&A header or 6000 chars, whichever comes first.
    tail = text[start + 100 : start + 8000]
    end_match = re.search(
        r"(critical accounting|off[- ]?balance sheet|recently issued|item\s+\d|quantitative and qualitative)",
        tail,
        re.IGNORECASE,
    )
    if end_match:
        return text[start : start + 100 + end_match.start()].strip()
    return text[start : start + 6000].strip()
