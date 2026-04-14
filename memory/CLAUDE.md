# Memory Layer

## Three distinct stores — do not mix them up

### working_memory.py → Redis
- Live shared state readable by ALL agents every cycle
- Keys: portfolio:state, signals:today, macro:regime
- Signals expire after 24h automatically
- Use get_portfolio_state() and get_all_signals() — these are the primary reads
- Never store secrets or PII here

### episodic.py → Pinecone
- Past trades with full context and outcomes
- Written AFTER trade closes, not when opened
- Quality gate: only write if confidence >= 0.70 AND not stopped by circuit breaker
- Retrieval: embedding similarity search — query_similar_setups(signal) returns top-5
- Embedding model: text-embedding-3-small (cheap, fast, good enough)

### semantic.py → SQLite (semantic_memory.db)
- Distilled rules extracted from episodic by distill_job.py
- Written nightly, read by agents at start of each cycle
- Schema: (id, domain, rule, confidence, n_trades, created_at)
- Agents call get_rules(domain) to pull relevant priors

## distill_job.py
- Runs nightly via APScheduler (2am UTC)
- Reads last 30 days of episodic memory
- Calls claude-sonnet-4-6 to extract 5-10 rules
- Replaces old rules for that domain (not appends)
- Log how many rules were extracted each run

## Memory read order in agents
1. get_regime() from working memory
2. get_rules(domain) from semantic
3. query_similar_setups(signal) from episodic
All three enrichments happen BEFORE the Claude API call.
