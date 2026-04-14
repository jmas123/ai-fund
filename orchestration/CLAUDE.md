# Orchestration

## agent_graph.py — LangGraph DAG
- All 7 domain agents run in PARALLEL (asyncio)
- They all write to Redis working memory independently
- Boss agent runs AFTER all 7 complete (fan-in)
- State type: HedgeFundState with signals list (Annotated with operator.add)
- Entry point fans out to all agents simultaneously
- All agent edges point to "synthesize" node (boss)
- "synthesize" → "execute" → END

## scheduler.py — APScheduler
- Only run cycles during market hours: Mon-Fri 09:30-16:00 ET
- Default interval: every 60 minutes
- Before each cycle: check Redis "system:halted" key
  - If "1": skip cycle, log warning, do NOT reset automatically
  - Manual reset required: delete the key or restart
- Distillation job: every day at 02:00 UTC (always runs, not market-hours gated)

## event_bus.py — Redis pub/sub
- Channel: "agent:signals" — agents publish when signal is ready
- Channel: "system:events" — halt, resume, cycle start/end
- boss_agent subscribes to "agent:signals" and waits for all 7
- Keep it simple at first — Redis pub/sub is enough, no Kafka needed

## Agent ordering constraints
- **Quant agent MUST run after all other domain agents.** It calls get_all_signals()
  to read signals written by other agents in the same cycle. In the sequential main.py
  loop this works because quant is last in the AGENTS list. When wiring the LangGraph
  DAG, quant must be gated behind a fan-in of the other 6 agents — do NOT include it
  in the parallel fan-out.

## Cycle flow
```
scheduler fires
  → check system:halted
  → refresh working memory (clear stale signals)
  → dispatch all agents in parallel
  → each agent: read memory → fetch data → call Claude → write signal
  → boss: read all signals → call Claude → produce decision
  → risk_check → audit_log → order_router
  → write outcome to episodic (if trade closes this cycle)
```
