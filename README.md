# Credit Snapshot Pro

A Streamlit credit-analyst dashboard — leverage, coverage, gearing, agency triggers,
and credit-keyworded news for a managed watchlist.

This is a credit tool, not an equity dashboard. No DCF, no options, no ESG scores,
no chat UI. The four things that matter are: how levered, how covered, what the
agencies are watching, and what just happened in the news.

## Quick start

```bash
python -m venv .venv && source .venv/bin/activate
pip install -r requirements.txt
streamlit run app/main.py
```

On first run a SQLite file (`app.db`) is created in the working directory and
seeded with 10 default tickers. The watchlist persists between restarts.

## API keys

Set whichever of these you have. The app degrades gracefully when keys are missing
— FMP falls back to yfinance, news APIs show an empty state, and LLM calls return
clearly-labeled placeholder output rather than failing.

```bash
export FMP_API_KEY=...           # primary fundamentals provider
export FINNHUB_API_KEY=...       # primary news provider
export NEWSAPI_KEY=...           # news fallback
export ANTHROPIC_API_KEY=...     # LLM extraction + summaries
# or
export OPENAI_API_KEY=...
```

## Layout

```
app/
  main.py              # entry point, sidebar, tab routing
  db.py                # SQLAlchemy models + persistence (watchlist, ratings, triggers cache)
  data.py              # FMP / yfinance fundamentals fetcher with fallback chain
  metrics.py           # leverage / coverage / gearing / TTM math + adjusted-vs-reported
  news.py              # Finnhub / NewsAPI fetch, keyword bucketing, sentiment
  triggers.py          # PDF section locator + LLM trigger extraction + headroom math
  llm.py               # thin Anthropic/OpenAI wrapper with no-key fallback
  pdf_export.py        # one-pager PDF via reportlab
  edgar.py             # SEC EDGAR MD&A liquidity puller
  theme.py             # color tokens + Plotly template
  tabs/
    watchlist.py
    snapshot.py
    agency.py
    news_single.py
    news_top10.py
```

## Acceptance criteria coverage

- Watchlist persists in `app.db` (SQLite).
- AAPL loads under 5s on warm cache; first call may be slower while FMP/yfinance round-trips.
- Four-quadrant Plotly dashboard with per-ticker configurable red lines (Watchlist `Notes` → `leverage_redline=4.5`).
- Reported / Adjusted toggle in sidebar — adjusted view documents every adjustment in an expander.
- Trigger extraction is regex-narrowed to sensitivities sections before any LLM call.
- RAG headroom is direction-aware (works for both `>` and `<` triggers).
- News tab buckets headlines into Rating Actions / Capital Activity / Management & Macro.
- Top-10 aggregator caches for 15 min and re-ranks across the active watchlist.
- One-pager PDF export via reportlab.
- No silent failures — every error path has a visible message.
