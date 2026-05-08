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

    /* ---------- Sidebar ---------- */
    section[data-testid="stSidebar"] {{
        background-color: {PANEL}; border-right: 1px solid {BORDER};
    }}
    section[data-testid="stSidebar"] *,
    section[data-testid="stSidebar"] p,
    section[data-testid="stSidebar"] label,
    section[data-testid="stSidebar"] div[data-testid="stMarkdownContainer"],
    section[data-testid="stSidebar"] div[data-testid="stMarkdownContainer"] p,
    section[data-testid="stSidebar"] div[data-testid="stMarkdownContainer"] strong {{
        color: {TEXT};
    }}
    section[data-testid="stSidebar"] small,
    section[data-testid="stSidebar"] [data-testid="stCaptionContainer"],
    section[data-testid="stSidebar"] [data-testid="stCaptionContainer"] *,
    section[data-testid="stSidebar"] .st-emotion-cache-10trblm + div,
    section[data-testid="stSidebar"] .stCaption {{
        color: #b8b8b8 !important;
    }}
    section[data-testid="stSidebar"] hr {{
        margin: 18px 0; border: 0; border-top: 1px solid {BORDER};
    }}
    section[data-testid="stSidebar"] [data-testid="stRadio"] label,
    section[data-testid="stSidebar"] [data-testid="stSelectbox"] label,
    section[data-testid="stSidebar"] [data-testid="stFileUploader"] label {{
        color: {TEXT} !important; font-weight: 500;
    }}

    /* File uploader: give it room to breathe */
    section[data-testid="stSidebar"] [data-testid="stFileUploader"] {{
        margin-top: 4px; margin-bottom: 4px;
    }}
    [data-testid="stFileUploaderDropzone"] {{
        background-color: {BG}; border: 1px dashed {BORDER};
        padding: 14px 12px; border-radius: 4px;
    }}
    [data-testid="stFileUploaderDropzone"]:hover {{ border-color: {POS}; }}
    [data-testid="stFileUploaderDropzone"] small,
    [data-testid="stFileUploaderDropzone"] span {{ color: #b8b8b8 !important; }}
    [data-testid="stFileUploaderDropzone"] button {{
        background-color: {PANEL}; color: {TEXT};
        border: 1px solid {BORDER}; border-radius: 4px;
        padding: 4px 12px; margin-top: 6px;
    }}
    [data-testid="stFileUploaderDropzone"] button:hover {{
        border-color: {POS}; color: {POS};
    }}

    /* ---------- Tabs ---------- */
    .stTabs [data-baseweb="tab-list"] {{ gap: 0; border-bottom: 1px solid {BORDER}; }}
    .stTabs [data-baseweb="tab"] {{
        background-color: transparent; color: {TEXT_MUTED}; border-radius: 0;
        padding: 8px 16px; font-family: {FONT_STACK};
    }}
    .stTabs [aria-selected="true"] {{ color: {TEXT}; border-bottom: 2px solid {POS}; }}

    /* ---------- Metrics ---------- */
    div[data-testid="stMetric"] {{
        background-color: {PANEL}; border: 1px solid {BORDER}; border-radius: 4px;
        padding: 12px; font-family: {FONT_STACK};
    }}
    div[data-testid="stMetricValue"] {{ color: {TEXT}; font-size: 22px; font-family: {FONT_STACK}; }}
    div[data-testid="stMetricLabel"] {{
        color: {TEXT_MUTED}; font-size: 11px; text-transform: uppercase;
        letter-spacing: 0.05em; font-family: {FONT_STACK};
    }}

    /* ---------- Buttons ---------- */
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
    .timestamp {{ color: #a8a8a8; font-size: 11px; }}

    /* ---------- News cards ---------- */
    .news-card {{
        background-color: {PANEL}; border: 1px solid {BORDER}; border-radius: 4px;
        padding: 12px; margin-bottom: 8px;
    }}
    .ticker-badge {{
        background-color: {BORDER}; color: {TEXT}; padding: 2px 8px; border-radius: 2px;
        font-size: 11px; font-family: {FONT_STACK};
    }}

    /* ---------- AI Credit Summary card ---------- */
    .summary-card {{
        background-color: {PANEL}; border: 1px solid {BORDER}; border-left: 3px solid {POS};
        border-radius: 4px; padding: 14px 18px; margin: 8px 0 12px 0;
        font-family: {SANS_STACK}; font-size: 14px; line-height: 1.6;
        color: {TEXT}; max-width: 1100px;
    }}
    .summary-card p {{ margin: 0; font-family: {SANS_STACK}; }}

    /* ---------- Liquidity summary ---------- */
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

    /* ---------- Verbatim text box ---------- */
    .verbatim-box textarea {{
        background-color: {BG} !important; color: {TEXT} !important;
        font-family: {FONT_STACK} !important; font-size: 12px !important;
        line-height: 1.55 !important; border: 1px solid {BORDER} !important;
    }}

    /* ---------- Triggers table row separation + hover ---------- */
    .triggers-row {{
        border-bottom: 1px solid {BORDER}; padding: 6px 0;
        transition: background-color 0.15s ease;
    }}
    .triggers-row:hover {{ background-color: rgba(0,255,65,0.04); }}
</style>
"""
