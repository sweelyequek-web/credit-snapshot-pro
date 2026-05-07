"""Credit One-Pager PDF export.

Layout: cover header, AI summary, four-quadrant chart images, ratings table,
triggers with headroom, top 5 news headlines.

Charts are rendered to PNG bytes by the caller (Plotly's `to_image` requires
kaleido, which isn't always available). If a chart can't be rendered, the
section is replaced with a brief textual fallback rather than crashing the export.
"""
from __future__ import annotations

import io
from datetime import datetime
from typing import Optional

from reportlab.lib import colors
from reportlab.lib.pagesizes import letter
from reportlab.lib.styles import ParagraphStyle, getSampleStyleSheet
from reportlab.lib.units import inch
from reportlab.platypus import (
    Image, PageBreak, Paragraph, SimpleDocTemplate, Spacer, Table, TableStyle,
)


def _style_for_pdf():
    base = getSampleStyleSheet()
    title = ParagraphStyle(
        "Title", parent=base["Heading1"], fontSize=18, textColor=colors.HexColor("#0a0a0a"),
        spaceAfter=6,
    )
    h2 = ParagraphStyle(
        "H2", parent=base["Heading2"], fontSize=12, textColor=colors.HexColor("#0a0a0a"),
        spaceBefore=14, spaceAfter=6,
    )
    body = ParagraphStyle(
        "Body", parent=base["BodyText"], fontSize=9, leading=12,
        textColor=colors.HexColor("#222222"),
    )
    muted = ParagraphStyle(
        "Muted", parent=body, textColor=colors.HexColor("#666666"), fontSize=8,
    )
    return title, h2, body, muted


def build_one_pager(
    *,
    ticker: str,
    issuer_name: str,
    summary_text: str,
    quadrant_pngs: list[bytes],   # 4 chart PNGs in order
    ratings_df,                   # DataFrame
    triggers: list[dict],
    headlines: list[dict],
) -> bytes:
    buf = io.BytesIO()
    doc = SimpleDocTemplate(
        buf, pagesize=letter,
        rightMargin=0.5 * inch, leftMargin=0.5 * inch,
        topMargin=0.5 * inch, bottomMargin=0.5 * inch,
        title=f"Credit One-Pager — {ticker}",
    )
    title_style, h2, body, muted = _style_for_pdf()

    elements = []
    elements.append(Paragraph(f"Credit One-Pager — {ticker}", title_style))
    if issuer_name:
        elements.append(Paragraph(issuer_name, body))
    elements.append(Paragraph(
        f"Generated {datetime.utcnow().strftime('%Y-%m-%d %H:%M UTC')}", muted,
    ))
    elements.append(Spacer(1, 0.15 * inch))

    elements.append(Paragraph("AI Credit Summary", h2))
    elements.append(Paragraph(summary_text or "—", body))

    elements.append(Paragraph("Credit Metrics", h2))
    if quadrant_pngs and len(quadrant_pngs) >= 4 and all(quadrant_pngs):
        rows = []
        try:
            rows.append([
                Image(io.BytesIO(quadrant_pngs[0]), width=3.5 * inch, height=2.0 * inch),
                Image(io.BytesIO(quadrant_pngs[1]), width=3.5 * inch, height=2.0 * inch),
            ])
            rows.append([
                Image(io.BytesIO(quadrant_pngs[2]), width=3.5 * inch, height=2.0 * inch),
                Image(io.BytesIO(quadrant_pngs[3]), width=3.5 * inch, height=2.0 * inch),
            ])
            t = Table(rows, colWidths=[3.6 * inch, 3.6 * inch])
            t.setStyle(TableStyle([("VALIGN", (0, 0), (-1, -1), "TOP")]))
            elements.append(t)
        except Exception:
            elements.append(Paragraph("[Charts could not be embedded — kaleido missing]", muted))
    else:
        elements.append(Paragraph(
            "[Charts not embedded — install kaleido (`pip install kaleido`) to enable]", muted,
        ))

    elements.append(Paragraph("Agency Ratings", h2))
    if ratings_df is not None and not ratings_df.empty:
        data = [list(ratings_df.columns)] + ratings_df.fillna("").astype(str).values.tolist()
        rt = Table(data, colWidths=[1.0 * inch, 1.5 * inch, 1.5 * inch, 1.5 * inch])
        rt.setStyle(TableStyle([
            ("BACKGROUND", (0, 0), (-1, 0), colors.HexColor("#222222")),
            ("TEXTCOLOR", (0, 0), (-1, 0), colors.white),
            ("FONTSIZE", (0, 0), (-1, -1), 9),
            ("GRID", (0, 0), (-1, -1), 0.25, colors.HexColor("#bbbbbb")),
            ("VALIGN", (0, 0), (-1, -1), "MIDDLE"),
        ]))
        elements.append(rt)
    else:
        elements.append(Paragraph("No ratings on file.", muted))

    elements.append(Paragraph("Rating Triggers", h2))
    if triggers:
        rows = [["Agency", "Direction", "Metric", "Op", "Threshold", "Current", "Headroom"]]
        for t in triggers:
            rows.append([
                t.get("agency", ""),
                t.get("direction", ""),
                t.get("metric", ""),
                t.get("operator", ""),
                _fmt_num(t.get("threshold")),
                _fmt_num(t.get("current")),
                _fmt_pct(t.get("headroom")),
            ])
        tt = Table(rows, repeatRows=1, colWidths=[
            0.7 * inch, 0.8 * inch, 1.4 * inch, 0.4 * inch, 0.8 * inch, 0.8 * inch, 0.9 * inch,
        ])
        tt.setStyle(TableStyle([
            ("BACKGROUND", (0, 0), (-1, 0), colors.HexColor("#222222")),
            ("TEXTCOLOR", (0, 0), (-1, 0), colors.white),
            ("FONTSIZE", (0, 0), (-1, -1), 8),
            ("GRID", (0, 0), (-1, -1), 0.25, colors.HexColor("#bbbbbb")),
            ("VALIGN", (0, 0), (-1, -1), "MIDDLE"),
        ]))
        elements.append(tt)
    else:
        elements.append(Paragraph("No triggers extracted.", muted))

    elements.append(Paragraph("Top Headlines", h2))
    if headlines:
        for h in headlines[:5]:
            ts = h.get("timestamp")
            ts_str = ts.strftime("%Y-%m-%d") if ts else ""
            line = f"<b>{ts_str}</b> · {h.get('source', '')} · {h.get('headline', '')}"
            elements.append(Paragraph(line, body))
            elements.append(Spacer(1, 0.05 * inch))
    else:
        elements.append(Paragraph("No recent headlines.", muted))

    doc.build(elements)
    return buf.getvalue()


def _fmt_num(v: Optional[float]) -> str:
    if v is None:
        return "—"
    try:
        return f"{float(v):.2f}"
    except (ValueError, TypeError):
        return "—"


def _fmt_pct(v: Optional[float]) -> str:
    if v is None:
        return "—"
    try:
        return f"{float(v):.1f}%"
    except (ValueError, TypeError):
        return "—"
