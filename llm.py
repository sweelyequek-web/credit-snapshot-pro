"""Thin LLM wrapper.

When ANTHROPIC_API_KEY is set, calls Claude. When it isn't, returns a clearly
labeled placeholder. Never raises into the UI. Triggers extraction and the AI
summary card both go through here.
"""
from __future__ import annotations

import json
import os
from typing import Optional


def _has_key() -> bool:
    return bool(os.environ.get("ANTHROPIC_API_KEY"))


def call_claude(prompt: str, system: str = "", max_tokens: int = 2048) -> str:
    """Returns Claude's text response or a clearly-labeled placeholder."""
    if not _has_key():
        return "[no LLM key — placeholder]"
    try:
        import anthropic
        client = anthropic.Anthropic()
        msg = client.messages.create(
            model="claude-sonnet-4-5",
            max_tokens=max_tokens,
            system=system or "You are a credit analyst assistant. Be precise and brief.",
            messages=[{"role": "user", "content": prompt}],
        )
        # Concatenate any text blocks Claude returned.
        chunks = []
        for block in msg.content:
            text = getattr(block, "text", None)
            if text:
                chunks.append(text)
        return "\n".join(chunks).strip() or "[empty LLM response]"
    except Exception as e:
        return f"[LLM error: {e}]"


def extract_triggers_json(narrowed_text: str, agency_hint: str = "") -> list[dict]:
    """Force structured trigger extraction. Returns a list of trigger dicts.

    `narrowed_text` is the regex-located sensitivities section — never the full
    PDF. The model is asked to return JSON only, but we tolerate stray prose
    around it.
    """
    if not narrowed_text.strip():
        return []
    if not _has_key():
        return _placeholder_triggers(agency_hint)

    schema_hint = """
Return ONLY a JSON array (no prose, no code fences) where each element is:
{
  "agency": "S&P" | "Moody's" | "Fitch",
  "direction": "downgrade" | "upgrade",
  "metric": "Debt/EBITDA | FFO/Debt | EBITDA/Interest | Net Debt/EBITDA | ...",
  "operator": ">" | "<" | ">=" | "<=",
  "threshold": <number or null if qualitative>,
  "unit": "x" | "%" | "bps",
  "sustained_period": "sustained basis" | "12 months" | null,
  "qualitative": <true if non-numeric, else false>,
  "verbatim_quote": "<exact short quote from the text>",
  "page_number": <integer or null>,
  "confidence": <0.0 to 1.0>
}
""".strip()
    system = (
        "You extract rating triggers from credit rating agency reports. "
        "You return only valid JSON. Do not invent thresholds. "
        "If a trigger is qualitative, set qualitative=true and threshold=null."
    )
    prompt = (
        f"Agency hint (may be wrong, verify from text): {agency_hint or 'unknown'}\n\n"
        f"{schema_hint}\n\n"
        f"--- TEXT ---\n{narrowed_text[:12000]}"
    )
    raw = call_claude(prompt, system=system, max_tokens=2000)
    return _parse_json_list(raw)


def summarize_credit_metrics(metrics_summary: str) -> str:
    """One-sentence AI Credit Summary. Inputs are the computed metrics only —
    never news, per the spec. That separation is deliberate: feeding free-form
    news into a metrics summarizer is what produces hallucinated narrative.
    """
    if not _has_key():
        return "[no LLM key — placeholder] " + metrics_summary
    system = (
        "You write one-sentence credit summaries for buy-side analysts. "
        "Use ONLY the numbers given. No speculation. No news context. "
        "Match the tone of: 'Leverage rose from 2.1x to 2.8x over the last four "
        "quarters as Net Debt grew faster than EBITDA, but coverage remains robust at 9.4x.'"
    )
    return call_claude(metrics_summary, system=system, max_tokens=200)


def summarize_liquidity_section(liquidity_text: str) -> str:
    """3-bullet summary grounded only in the supplied MD&A text."""
    if not liquidity_text.strip():
        return ""
    if not _has_key():
        return "[no LLM key — placeholder]\n- Liquidity narrative not summarized\n- Set ANTHROPIC_API_KEY to enable\n- Raw text remains visible above"
    system = (
        "Summarize the supplied 'Liquidity and Capital Resources' section in "
        "exactly 3 bullets. Use only facts present in the text. No speculation."
    )
    return call_claude(liquidity_text[:8000], system=system, max_tokens=400)


def summarize_news_headline(headline: str, summary: str = "") -> str:
    """One-line summary of a single news item for the Top-10 cards."""
    if not _has_key():
        return summary[:140] if summary else headline[:140]
    system = "Summarize this news item in one short sentence for a credit analyst."
    return call_claude(f"{headline}\n\n{summary}", system=system, max_tokens=120)


# ---------- Helpers ----------


def _parse_json_list(raw: str) -> list[dict]:
    """Extract a JSON array from raw LLM output, tolerating fences and prose."""
    if not raw:
        return []
    # Strip code fences.
    s = raw.strip()
    if s.startswith("```"):
        s = s.split("```", 2)[-2] if s.count("```") >= 2 else s.strip("`")
        if s.startswith("json"):
            s = s[4:]
    # Find the first '[' and matching ']'.
    start = s.find("[")
    end = s.rfind("]")
    if start == -1 or end == -1 or end <= start:
        return []
    try:
        data = json.loads(s[start : end + 1])
        if isinstance(data, list):
            # Sanity-filter — drop entries missing the required fields.
            return [
                item for item in data
                if isinstance(item, dict)
                and item.get("agency") and item.get("direction") and item.get("metric")
            ]
    except json.JSONDecodeError:
        return []
    return []


def _placeholder_triggers(agency_hint: str) -> list[dict]:
    """Used when no API key is set, so the UI flow remains demonstrable."""
    agency = agency_hint or "Moody's"
    return [
        {
            "agency": agency,
            "direction": "downgrade",
            "metric": "Debt/EBITDA",
            "operator": ">",
            "threshold": 4.0,
            "unit": "x",
            "sustained_period": "sustained basis",
            "qualitative": False,
            "verbatim_quote": "[no LLM key — placeholder] Debt/EBITDA sustained above 4.0x could lead to a downgrade",
            "page_number": None,
            "confidence": 0.0,
        },
        {
            "agency": agency,
            "direction": "downgrade",
            "metric": "EBITDA/Interest",
            "operator": "<",
            "threshold": 5.0,
            "unit": "x",
            "sustained_period": None,
            "qualitative": False,
            "verbatim_quote": "[no LLM key — placeholder] EBITDA/Interest below 5.0x",
            "page_number": None,
            "confidence": 0.0,
        },
    ]
