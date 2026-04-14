# Data Layer

## Two categories — know which is which

### Free REST APIs (direct calls, no browser)
- FRED:          https://api.stlouisfed.org/fred/  (free key at fred.stlouisfed.org)
- SEC EDGAR:     https://data.sec.gov/submissions/ (no key)
- FDA:           https://api.fda.gov/drug/         (free, 1000 req/day)
- ClinicalTrials: https://clinicaltrials.gov/api/  (free)
- EIA:           https://api.eia.gov/              (free key)
- ArXiv:         https://export.arxiv.org/api/     (free)
- Alpaca bars:   use alpaca-trade-api SDK           (free with account)

### Browser agent targets (no good free API)
- polygon_scraper.py  → polygon.io/stocks/{ticker}   (price + news)
- news_scraper.py     → reuters.com, ft.com headlines
- fda_scraper.py      → clinicaltrials.gov search UI (richer than API)
- congress scraper    → congress.gov/search

## macro_feeds.py
- Cache FRED responses with @lru_cache — they update daily, not per-minute
- Key series: FEDFUNDS, CPIAUCSL, T10Y2Y, BAMLH0A0HYM2, UNRATE, DGS10
- Return format: list of {"date": str, "value": str} dicts

## polygon_scraper.py
- Do NOT create a new browser page per ticker — reuse via get_browser()
- Rate limit yourself: asyncio.sleep(2) between ticker scrapes
- If selector not found: return None, do not raise — agent handles None gracefully
- This is the fragile part of the stack — build retry logic

## General rules
- All data fetches are async (async def)
- Timeout every external call: httpx timeout=10, playwright timeout=15000
- On failure: log the error, return None or empty dict
- Never block the cycle on a single data source failure
