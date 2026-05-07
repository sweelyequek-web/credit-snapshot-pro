"""Agency trigger extraction.

Pipeline:
    1. Locate sensitivities section(s) in the PDF via header regex
    2. Pass narrowed text to LLM with strict JSON schema
    3. Compute direction-aware headroom against current metric values
    4. RAG color the result

The narrowing step is non-negotiable. Passing the whole report to the model is
both expensive and a hallucination factory.
"""
from __future__ import annotations

import io
import re
from dataclasses import dataclass
from typing import BinaryIO, Optional

from pypdf import PdfReader

from app import llm

# Section-header patterns from the spec.
SECTION_HEADERS = [
    r"factors that could lead to (an? )?downgrade",
    r"factors that could lead to (an? )?upgrade",
    r"what could change the rating",
    r"rating sensitivities",
    r"upside scenario",
    r"downside scenario",
]
SECTION_REGEX = re.compile("|".join(f"({p})" for p in SECTION_HEADERS), re.IGNORECASE)


@dataclass
class LocatedSection:
    text: str
    page_number: int  # 1-indexed
    matched_header: str


def extract_pdf_pages(file_or_bytes) -> list[tuple[int, str]]:
    """Returns [(page_number_1_indexed, text), ...]."""
    if isinstance(file_or_bytes, (bytes, bytearray)):
        reader = PdfReader(io.BytesIO(file_or_bytes))
    elif isinstance(file_or_bytes, (str,)):
        reader = PdfReader(file_or_bytes)
    else:
        reader = PdfReader(file_or_bytes)
    out = []
    for i, page in enumerate(reader.pages, start=1):
        try:
            out.append((i, page.extract_text() or ""))
        except Exception:
            out.append((i, ""))
    return out


def locate_sections(pages: list[tuple[int, str]]) -> list[LocatedSection]:
    """Find all matching headers and grab the chunk that follows each.

    We grab from the matched header to the start of the next blank-line block
    or the next matched header on the same page, whichever comes first. Limit
    each section to ~2000 chars to stay tight for the LLM.
    """
    located: list[LocatedSection] = []
    for page_no, text in pages:
        if not text:
            continue
        # Walk all matches on this page.
        for m in SECTION_REGEX.finditer(text):
            start = m.start()
            # Cap at 2000 chars or the start of the next matching header on
            # the same page, whichever is shorter.
            next_match = None
            for n in SECTION_REGEX.finditer(text, m.end()):
                next_match = n.start()
                break
            end = min(start + 2000, next_match if next_match else len(text))
            chunk = text[start:end].strip()
            located.append(
                LocatedSection(
                    text=chunk,
                    page_number=page_no,
                    matched_header=m.group(0),
                )
            )
    return located


def detect_agency(pages: list[tuple[int, str]]) -> str:
    """First-page agency detection — purely a hint to the LLM."""
    head = " ".join(t for _, t in pages[:2]).lower()
    if "moody" in head:
        return "Moody's"
    if "s&p" in head or "standard & poor" in head:
        return "S&P"
    if "fitch" in head:
        return "Fitch"
    return ""


def extract_triggers_from_pdf(file_bytes: bytes) -> tuple[list[dict], str]:
    """Top-level extraction. Returns (triggers, error_message).

    `error_message` is empty on success. When set, the UI surfaces the
    spec's required wording: 'Could not locate rating sensitivities section.
    Confirm this is an agency report and try again.'
    """
    pages = extract_pdf_pages(file_bytes)
    if not pages or all(not t for _, t in pages):
        return [], "PDF appears empty or could not be parsed."

    sections = locate_sections(pages)
    if not sections:
        return [], (
            "Could not locate rating sensitivities section. "
            "Confirm this is an agency report and try again."
        )

    agency = detect_agency(pages)
    # Concatenate matched sections, page-tagged so the LLM can echo back page numbers.
    narrowed = "\n\n".join(
        f"[Page {s.page_number}] {s.text}" for s in sections
    )
    triggers = llm.extract_triggers_json(narrowed, agency_hint=agency)
    # Backfill missing page_numbers from our located sections (best-effort).
    for t in triggers:
        if not t.get("page_number") and sections:
            t["page_number"] = sections[0].page_number
    return triggers, ""


# ---------- Headroom & RAG ----------


def headroom_pct(current: Optional[float], threshold: Optional[float], operator: str) -> Optional[float]:
    """Direction-aware headroom.

    For 'higher = worse' triggers (operator '>' or '>='):
        headroom = (threshold - current) / threshold
    For 'lower = worse' triggers ('<' or '<='):
        headroom = (current - threshold) / threshold

    Always positive when in compliance, negative when breached. Uses absolute
    threshold in the denominator to keep sign coming from the numerator
    direction (otherwise a negative threshold would flip the sign incorrectly).
    """
    if current is None or threshold is None or threshold == 0:
        return None
    op = operator.strip()
    if op in (">", ">="):
        return (threshold - current) / abs(threshold) * 100.0
    if op in ("<", "<="):
        return (current - threshold) / abs(threshold) * 100.0
    return None


def rag_color(headroom: Optional[float]) -> str:
    """Spec: green > 25%, amber 10-25%, red < 10% (or breached)."""
    if headroom is None:
        return "amber"
    if headroom > 25.0:
        return "green"
    if headroom >= 10.0:
        return "amber"
    return "red"


def map_metric_to_current(metric: str, latest_metrics: dict) -> Optional[float]:
    """Best-effort mapping from an LLM-returned metric name to a computed value.

    Supports the metric names called out in the spec. Anything else returns
    None and the UI shows '—' for current value.
    """
    if not metric:
        return None
    m = metric.lower().replace(" ", "")
    leverage = latest_metrics.get("leverage")
    coverage = latest_metrics.get("coverage")
    gearing = latest_metrics.get("net_gearing")
    if any(k in m for k in ["debt/ebitda", "netdebt/ebitda", "leverage"]):
        return leverage
    if any(k in m for k in ["ebitda/interest", "interestcoverage", "coverage"]):
        return coverage
    if "gearing" in m or "debttoequity" in m or "debt/equity" in m:
        return gearing
    if "ffo/debt" in m:
        return None  # FFO not in our standard feed; surface as "—"
    return None
