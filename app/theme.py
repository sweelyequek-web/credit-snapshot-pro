"""Theme tokens. Concrete values from the spec, no creative license here."""
from __future__ import annotations

import plotly.graph_objects as go
import plotly.io as pio

BG = "#0a0a0a"
PANEL = "#141414"
BORDER = "#2a2a2a"
TEXT = "#e8e8e8"
TEXT_MUTED = "#888888"
POS = "#00ff41"
NEG = "#ff3b30"
AMBER = "#ffb800"

FONT_STACK = "JetBrains Mono, IBM Plex Mono, monospace"


def install_plotly_template() -> None:
    """Register a 'credit_dark' Plotly template and make it the default."""
    template = go.layout.Template()
    template.layout = go.Layout(
        paper_bgcolor=PANEL,
        plot_bgcolor=PANEL,
        font=dict(family=FONT_STACK, color=TEXT, size=12),
        xaxis=dict(
            gridcolor=BORDER,
            linecolor=BORDER,
            zerolinecolor=BORDER,
            tickfont=dict(color=TEXT_MUTED),
        ),
        yaxis=dict(
            gridcolor=BORDER,
            linecolor=BORDER,
            zerolinecolor=BORDER,
            tickfont=dict(color=TEXT_MUTED),
        ),
        margin=dict(l=40, r=20, t=40, b=40),
        colorway=[POS, AMBER, NEG, "#4a90e2", "#9b59b6", TEXT_MUTED],
        legend=dict(font=dict(color=TEXT, size=10), bgcolor="rgba(0,0,0,0)"),
    )
    pio.templates["credit_dark"] = template
    pio.templates.default = "credit_dark"


SANS_STACK = (
    "-apple-system, BlinkMacSystemFont, 'Segoe UI', Roboto, 'Helvetica Neue', "
    "Arial, sans-serif"
)


CSS = f"""
<style>
    .stApp {{ background-color: {BG}; color: {TEXT}; font-family: {SANS_STACK}; }}
    .stApp p, .stApp li, .stApp span, .stApp div[data-testid="stMarkdownContainer"] {{
        font-family: {SANS_STACK};
    }}
    .stApp code, .stApp pre, .stApp kbd, .stApp samp {{ font-family: {FONT_STACK}; }}
    section[data-testid="stSidebar"] {{ background-color: {PANEL}; border-right: 1px solid {BORDER}; }}
    .stTabs [data-baseweb="tab-list"] {{ gap: 0; border-bottom: 1px solid {BORDER}; }}
    .stTabs [data-baseweb="tab"] {{
        background-color: transparent; color: {TEXT_MUTED}; border-radius: 0;
        padding: 8px 16px; font-family: {FONT_STACK};
    }}
    .stTabs [aria-selected="true"] {{ color: {TEXT}; border-bottom: 2px solid {POS}; }}
    div[data-testid="stMetric"] {{
        background-color: {PANEL}; border: 1px solid {BORDER}; border-radius: 4px;
        padding: 12px; font-family: {FONT_STACK};
    }}
    div[data-testid="stMetricValue"] {{ color: {TEXT}; font-size: 22px; font-family: {FONT_STACK}; }}
    div[data-testid="stMetricLabel"] {{
        color: {TEXT_MUTED}; font-size: 11px; text-transform: uppercase;
        letter-spacing: 0.05em; font-family: {FONT_STACK};
    }}
    .stButton button {{
        background-color: {PANEL}; color: {TEXT}; border: 1px solid {BORDER}; border-radius: 4px;
        font-family: {SANS_STACK};
    }}
    .stButton button:hover {{ border-color: {POS}; color: {POS}; }}
    h1, h2, h3, h4 {{ color: {TEXT}; font-family: {SANS_STACK}; font-weight: 500; }}
    .rag-green {{ color: {POS}; font-weight: bold; }}
    .rag-amber {{ color: {AMBER}; font-weight: bold; }}
    .rag-red {{ color: {NEG}; font-weight: bold; }}
    .stale-badge {{
        background-color: {AMBER}; color: {BG}; padding: 2px 6px; border-radius: 2px;
        font-size: 10px; text-transform: uppercase; letter-spacing: 0.05em;
    }}
    .timestamp {{ color: {TEXT_MUTED}; font-size: 10px; }}
    .news-card {{
        background-color: {PANEL}; border: 1px solid {BORDER}; border-radius: 4px;
        padding: 12px; margin-bottom: 8px;
    }}
    .ticker-badge {{
        background-color: {BORDER}; color: {TEXT}; padding: 2px 8px; border-radius: 2px;
        font-size: 11px; font-family: {FONT_STACK};
    }}
    .liquidity-summary {{
        background-color: {PANEL}; border: 1px solid {BORDER}; border-left: 3px solid {POS};
        border-radius: 4px; padding: 16px 20px; margin: 8px 0 12px 0;
        font-family: {SANS_STACK}; font-size: 15px; line-height: 1.65;
        color: {TEXT}; max-width: 900px;
    }}
    .liquidity-summary p {{ margin: 0 0 8px 0; font-family: {SANS_STACK}; }}
    .liquidity-summary ul, .liquidity-summary ol {{
        margin: 4px 0 0 0; padding-left: 22px; font-family: {SANS_STACK};
    }}
    .liquidity-summary li {{ margin-bottom: 8px; font-family: {SANS_STACK}; }}
    .liquidity-summary li:last-child {{ margin-bottom: 0; }}
</style>
"""
