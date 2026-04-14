# AI Hedge Fund — APEX/fund

## What this is
Autonomous multi-agent hedge fund. 7 specialist agents feed signals to a boss agent 
(Capital Allocator) which makes final trade decisions. Executed via Alpaca brokerage.

## Architecture
data layer → agents (parallel) → working memory → boss agent → risk check → order router
↕
memory layer (episodic + semantic + working)

## Stack
- LLM: Anthropic API (Opus for boss, Sonnet for domain agents)
- Orchestration: LangGraph
- Memory: Redis (working), Pinecone (episodic), SQLite (semantic rules)
- Broker: Alpaca (paper first, then live)
- Browser automation: Playwright (replaces paid data APIs)
- Config: Pydantic settings from .env

## Agent signal schema — every agent must return this exact shape
```python
{
  "agent": str,           # agent name
  "ticker": str,          # e.g. "NVO"
  "signal": str,          # "BULLISH" | "BEARISH" | "NEUTRAL"
  "confidence": float,    # 0.0 - 1.0
  "time_horizon": str,    # "30d" | "90d" | "180d"
  "catalyst": str,
  "risk_flags": list[str],
  "suggested_weight": float,  # 0.0 - 0.10 (max 10%)
  "rationale": str
}
```

## Boss decision schema
```python
{
  "action": str,          # "BUY" | "SELL" | "HOLD" | "REDUCE"
  "ticker": str,
  "weight_pct": float,    # 0 - 10
  "conviction": float,    # 0.0 - 1.0
  "rationale": str,
  "stop_loss_pct": float,
  "approved": bool        # set by risk_check, not boss
}
```

## Absolute rules — never break these
1. risk_check.py runs between EVERY boss decision and EVERY order. No exceptions.
2. ALPACA_PAPER=true until explicitly changed in .env
3. Every order written to audit_log.db before submission
4. Never commit .env — secrets in .env only
5. Quality gate before writing to episodic memory: confidence >= 0.70

## Hard risk limits (config/settings.py)
- MAX_SINGLE_POSITION = 0.10   (10%)
- MAX_DRAWDOWN_KILL   = 0.15   (15% → full halt)
- MAX_PORTFOLIO_VAR   = 0.05   (5% daily VaR)
- MAX_SECTOR_EXPOSURE = 0.30   (30% per sector)

## Models
- Boss agent:    claude-opus-4-6
- Domain agents: claude-sonnet-4-6
- All agents: max_tokens=1000, response must be valid JSON only

## Build order (do not skip steps)
1. config/settings.py
2. memory/working_memory.py
3. execution/risk_check.py
4. data/macro_feeds.py + agents/macro_agent.py
5. agents/boss_agent.py (wired to macro only first)
6. execution/order_router.py (paper mode)
7. Remaining domain agents one by one
8. memory/episodic.py + memory/distill_job.py
9. orchestration/agent_graph.py (LangGraph DAG)
10. orchestration/scheduler.py

## Running
```bash
python main.py cycle        # run one full cycle now
python main.py scheduler    # start hourly market-hours scheduler
python main.py distill      # run nightly distillation manually
```

## Env vars required
ANTHROPIC_API_KEY, ALPACA_KEY, ALPACA_SECRET, ALPACA_PAPER,
FRED_API_KEY, PINECONE_API_KEY, REDIS_HOST, REDIS_PORT
