# APEX Fund — Roadmap

## Phase 0: Environment Setup
> Nothing works until the runtime is clean. Do this first, no exceptions.

- [ ] `pip install -r requirements.txt`
- [ ] `playwright install chromium`
- [ ] `docker-compose up -d` — Redis running and reachable
- [ ] `.env` populated with all required keys (copy from `.env.example`)
- [ ] Verify: `python -c "from config.settings import settings; print(settings)"` runs clean

**Gate:** All dependencies installed. Redis responds to ping. Settings load without error.

---

## Phase 1: Foundation
> Get the core config, memory, and risk layer working before any agent touches an LLM.

- [ ] **config/settings.py** — Pydantic settings loaded from `.env`, all hard risk limits defined
- [ ] **docker-compose.yml** — Redis + SQLite services for local dev
- [ ] **.env setup** — All required keys: `ANTHROPIC_API_KEY`, `ALPACA_KEY`, `ALPACA_SECRET`, `ALPACA_PAPER=true`, `FRED_API_KEY`, `PINECONE_API_KEY`, `REDIS_HOST`, `REDIS_PORT`
- [ ] **memory/working_memory.py** — Redis read/write helpers: `get_portfolio_state()`, `get_all_signals()`, `set_signal()`, `get_regime()`
- [ ] **execution/risk_check.py** — Enforce all four hard limits, drawdown kill switch sets `system:halted`
- [ ] **execution/audit_log.py** — SQLite logger, create table on first run

**Gate:** `risk_check` blocks a fake trade that exceeds 10% position size. Audit log has a row. Redis read/write round-trips.

---

## Phase 2: First Agent + Boss (Macro Only)
> Prove the full cycle end-to-end with one agent before scaling to seven.

- [ ] **data/macro_feeds.py** — FRED fetcher with `@lru_cache`, returns key series (FEDFUNDS, T10Y2Y, CPIAUCSL, etc.)
- [ ] **agents/macro_agent.py** — Follows the agent pattern: read memory → fetch FRED → call Claude Sonnet → return signal dict
- [ ] **agents/boss_agent.py** — Reads signals from working memory, calls Claude Opus, produces decision dict
- [ ] **data/price_feeds.py** — Alpaca bars API for live/recent prices (order_router needs this to convert weight_pct → share qty)
- [ ] **execution/order_router.py** — Translates decision to Alpaca paper order, respects `ALPACA_PAPER` env var
- [ ] **main.py `cycle` command** — Wires macro_agent → boss → risk_check → audit_log → order_router

**Gate:** Run `python main.py cycle`. Macro agent returns valid JSON signal. Boss produces a decision. Risk check passes/blocks. Audit log records it. Paper order submitted (or skipped if qty=0). Cycle completes gracefully with a NEUTRAL signal when macro agent throws an exception.

---

## Phase 3: Browser Agent + Data Scrapers
> Stand up Playwright and the scraping layer before adding agents that depend on it.

- [ ] **data/browser_agent.py** — Singleton Playwright instance via `get_browser()`, page lifecycle management
- [ ] **data/polygon_scraper.py** — Price + news scraper with 2s rate limit, retry logic
- [ ] **data/news_scraper.py** — Reuters/FT headline scraper
- [ ] **data/fda_scraper.py** — ClinicalTrials.gov UI scraper (richer than API)
- [ ] **data/congress_scraper.py** — Congress.gov bill/vote scraper

**Gate:** Each scraper returns structured data for at least one target. Browser doesn't leak pages.

---

## Phase 4: Remaining Domain Agents
> Add one at a time. Each must pass the agent pattern checklist before moving to the next.

- [ ] **agents/pharma_agent.py** — Tickers: NVO, LLY, MRNA, PFE, ABBV. Uses FDA scraper + ClinicalTrials API.
- [ ] **agents/tech_agent.py** — Tickers: NVDA, MSFT, AAPL, GOOGL, META. Uses polygon scraper + SEC EDGAR.
- [ ] **agents/energy_agent.py** — Tickers: XOM, CVX, COP, SLB. Uses EIA API + polygon scraper.
- [ ] **agents/political_agent.py** — No tickers. Returns regime/risk scores from congress scraper.
- [ ] **agents/science_agent.py** — No tickers. Returns sector impact scores from ArXiv API.
- [ ] **agents/quant_agent.py** — Reads portfolio state, returns sizing recommendations.
- [ ] **Update boss_agent.py** — Wire all 7 signals into boss decision logic.

**Gate:** Each agent returns a valid signal dict. Boss processes all 7 signals and produces coherent decisions.

---

## Phase 5: Memory Layer (Episodic + Semantic)
> Only needed once trades are flowing and there's history to learn from.

- [ ] **memory/episodic.py** — Pinecone store, write closed trades (confidence >= 0.70), `query_similar_setups()` returns top-5
- [ ] **memory/semantic.py** — SQLite rule store, `get_rules(domain)` for agent priors
- [ ] **memory/distill_job.py** — Nightly job: read 30d episodic → Claude Sonnet extracts 5-10 rules → replace old rules
- [ ] **Wire memory reads into all agents** — `get_regime()` → `get_rules()` → `query_similar_setups()` before every Claude call
- [ ] **main.py `distill` command** — Manual trigger for distillation

**Gate:** After a few cycles, episodic has entries. Distill job extracts rules. Agents read those rules and include them in context.

---

## Phase 6: Orchestration
> Replace the simple sequential `main.py cycle` with the real parallel DAG.

- [ ] **orchestration/agent_graph.py** — LangGraph DAG: 7 agents parallel → fan-in → boss → execute → END
- [ ] **orchestration/event_bus.py** — Redis pub/sub on `agent:signals` and `system:events`
- [ ] **orchestration/scheduler.py** — APScheduler: hourly during market hours (Mon-Fri 09:30-16:00 ET), checks `system:halted`, distill at 02:00 UTC
- [ ] **Update main.py** — `scheduler` command starts APScheduler, `cycle` uses the graph

**Gate:** `python main.py scheduler` runs a full cycle during market hours. Halted key blocks the next cycle. Distill fires at 2am UTC.

---

## Phase 7: Hardening
> Paper trade for at least 2 weeks before touching this phase.

- [ ] Structured logging (JSON) across all modules
- [ ] Alerting — email/Slack on: system halt, risk block, agent failure
- [ ] Dashboard — simple Streamlit showing portfolio state, recent signals, audit log
- [ ] Backtest harness — replay historical data through agents, compare to actual
- [ ] Performance tracking — Sharpe, max drawdown, win rate written to semantic memory
- [ ] Rate limit monitoring — track API usage for FRED, Anthropic, Alpaca

---

## Key Milestones

| Milestone | Definition of Done |
|---|---|
| **First signal** | Macro agent returns valid JSON from Claude |
| **First paper trade** | Order hits Alpaca paper account |
| **Full cycle** | All 7 agents → boss → risk → order in one run |
| **Memory loop closed** | Agent reads a rule that was distilled from its own past trades |
| **Graceful degradation** | Cycle completes with a NEUTRAL signal when one agent fails |
| **Parallel DAG** | LangGraph runs all agents concurrently, wall time < 5 min |
| **2-week paper run** | Scheduler runs unattended, no crashes, audit log complete |
