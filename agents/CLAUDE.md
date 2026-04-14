# Agents

## Pattern every agent must follow
1. Read working memory first (get_portfolio_state, get_regime)
2. Fetch data (FRED / browser agent / free API)
3. Query episodic memory for similar past setups
4. Call Claude API with structured JSON-only system prompt
5. Parse response — if not valid JSON, retry once then return NEUTRAL signal
6. Write signal to working memory via set_signal(agent_name, signal)
7. Return signal dict

## System prompt pattern for all domain agents
```python
SYSTEM = """You are a [domain] specialist for an autonomous hedge fund.
Analyze the provided data and return ONLY a JSON object.
No prose, no markdown, no explanation outside the JSON.
Schema: { "agent": "...", "ticker": "...", "signal": "BULLISH|BEARISH|NEUTRAL",
          "confidence": 0.0-1.0, "time_horizon": "30d|90d|180d",
          "catalyst": "...", "risk_flags": [], "suggested_weight": 0.0-0.10,
          "rationale": "..." }"""
```

## Error handling
- Wrap all Claude calls in try/except
- On JSON parse failure: retry with "Return only raw JSON, no markdown" appended
- On second failure: return neutral signal, log error
- Never let one agent failure crash the cycle

## browser_agent.py
- Single persistent Playwright browser instance — do not create new instances per call
- Use get_browser() which returns the singleton
- Always close pages (not the browser) in finally blocks
- Targets that use browser agent: pharma (clinicaltrials.gov), political (congress.gov),
  science (arxiv.org), news scraper

## Domain → ticker watchlists
- pharma:    ["NVO", "LLY", "MRNA", "PFE", "ABBV"]
- tech:      ["NVDA", "MSFT", "AAPL", "GOOGL", "META"]
- energy:    ["XOM", "CVX", "COP", "SLB"]
- political: no ticker — returns regime/risk scores only
- science:   no ticker — returns sector impact scores
- macro:     no ticker — returns regime + sector tilts
- quant:     reads portfolio state, returns sizing recommendations
