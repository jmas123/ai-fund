# Execution Layer

## Order of operations — never change this
1. Boss agent produces decision dict
2. risk_check(decision, portfolio) → bool
3. If False: log as BLOCKED, return, do not route
4. If True: audit_log.write(decision, "PRE_SUBMIT")
5. order_router.route(decision) → submit to Alpaca
6. audit_log.write(decision, "SUBMITTED", order_id=...)

## risk_check.py — these are hard limits, not suggestions
MAX_SINGLE_POSITION = 0.10
MAX_DRAWDOWN_KILL   = 0.15   ← triggers full system halt, not just block
MAX_PORTFOLIO_VAR   = 0.05
MAX_SECTOR_EXPOSURE = 0.30

If drawdown >= MAX_DRAWDOWN_KILL:
  - Block the trade
  - Set Redis key "system:halted" = "1"
  - scheduler.py checks this key before every cycle

## order_router.py
- Always use market orders during market hours
- Translate weight_pct to share quantity using current equity + live price
- If qty rounds to 0: log as SKIPPED, do not submit
- Paper mode: base_url = "https://paper-api.alpaca.markets"
- Live mode:  base_url = "https://api.alpaca.markets"
- Mode controlled by ALPACA_PAPER env var — never hardcode

## audit_log.py
- SQLite file: audit_log.db
- Every record must have: timestamp, ticker, action, weight_pct,
  full decision JSON, status, error (nullable), order_id (nullable)
- This is your debugging lifeline — log everything, be verbose
