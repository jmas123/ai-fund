"""LangGraph DAG — parallel agent execution with fan-in to alpha engine."""

import operator
import logging
from typing import Annotated, TypedDict
from concurrent.futures import ThreadPoolExecutor, as_completed

from memory.working_memory import is_system_halted, clear_stale_signals, get_all_signals, get_portfolio_state
from agents import macro_agent, pharma_agent, tech_agent, energy_agent
from agents import political_agent, science_agent, quant_agent
from execution.alpha_engine import run_engine
from execution.scenario_engine import run_scenarios
from execution.risk_check import risk_check
from execution import audit_log
from execution.order_router import route
from orchestration.event_bus import publish_event

logger = logging.getLogger(__name__)

# 6 agents run in parallel, quant runs after (needs their signals)
PARALLEL_AGENTS = [
    ("macro", macro_agent),
    ("pharma", pharma_agent),
    ("tech", tech_agent),
    ("energy", energy_agent),
    ("political", political_agent),
    ("science", science_agent),
]

SEQUENTIAL_AGENTS = [
    ("quant", quant_agent),
]


class HedgeFundState(TypedDict):
    signals: Annotated[list[dict], operator.add]
    decisions: list[dict]
    executed: list[dict]


def _run_agent(name: str, agent) -> list[dict]:
    """Run a single agent, return its signal(s) as a list."""
    try:
        result = agent.run()
        if isinstance(result, list):
            return result
        return [result]
    except Exception as e:
        logger.error("%s agent crashed: %s", name, e)
        return []


def run_parallel_agents() -> list[dict]:
    """Run the 6 parallel domain agents using a thread pool."""
    all_signals = []

    with ThreadPoolExecutor(max_workers=6) as pool:
        futures = {
            pool.submit(_run_agent, name, agent): name
            for name, agent in PARALLEL_AGENTS
        }
        for future in as_completed(futures):
            name = futures[future]
            try:
                signals = future.result()
                for sig in signals:
                    logger.info(
                        "  %s %s: %s (confidence=%.2f)",
                        name, sig.get("ticker", "?"),
                        sig.get("signal", "?"), sig.get("confidence", 0),
                    )
                all_signals.extend(signals)
            except Exception as e:
                logger.error("%s agent future failed: %s", name, e)

    return all_signals


def run_sequential_agents() -> list[dict]:
    """Run agents that depend on other agents' signals (quant)."""
    all_signals = []
    for name, agent in SEQUENTIAL_AGENTS:
        logger.info("Running %s agent (post fan-in)...", name)
        signals = _run_agent(name, agent)
        for sig in signals:
            logger.info(
                "  %s %s: %s (confidence=%.2f)",
                name, sig.get("ticker", "?"),
                sig.get("signal", "?"), sig.get("confidence", 0),
            )
        all_signals.extend(signals)
    return all_signals


def construct_portfolio(state: HedgeFundState) -> HedgeFundState:
    """Scenario simulation + deterministic portfolio construction."""
    signals = get_all_signals()
    portfolio = get_portfolio_state()
    price_data = quant_agent._get_price_summaries()

    # Phase 3a: Run Monte Carlo scenarios (no API call, pure math)
    from memory.working_memory import get_regime
    regime = get_regime().get("regime", "transition")
    scenarios = run_scenarios(signals, price_data, regime)

    # Phase 3b: Alpha engine with scenario enrichment
    logger.info("Running alpha engine (scenario-enriched)...")
    decisions = run_engine(signals, portfolio, price_data, scenarios=scenarios)
    logger.info("Alpha engine produced %d decision(s)", len(decisions))
    state["decisions"] = decisions
    return state


def execute(state: HedgeFundState) -> HedgeFundState:
    """Risk check → audit → order routing for each decision."""
    executed = []
    for decision in state["decisions"]:
        ticker = decision.get("ticker", "UNKNOWN")
        action = decision.get("action", "HOLD")
        logger.info("Processing: %s %s @ %.1f%%", action, ticker, decision.get("weight_pct", 0))

        approved = risk_check(decision)
        decision["approved"] = approved

        if not approved:
            audit_log.write(decision, "BLOCKED")
            executed.append({"decision": decision, "status": "BLOCKED"})
            continue

        if action == "HOLD":
            audit_log.write(decision, "HOLD")
            executed.append({"decision": decision, "status": "HOLD"})
            continue

        audit_log.write(decision, "PRE_SUBMIT")
        result = route(decision)
        status = result.get("status", "ERROR")
        order_id = result.get("order_id")
        error = result.get("reason")
        audit_log.write(decision, status, error=error, order_id=order_id)
        logger.info("Order result: %s (order_id=%s)", status, order_id)
        executed.append({"decision": decision, "status": status, "order_id": order_id})

    state["executed"] = executed
    return state


def run_cycle() -> HedgeFundState:
    """Run one full cycle using the parallel DAG.

    Flow:
      check halt → clear signals → 6 agents parallel → quant (fan-in)
      → scenario engine (Monte Carlo) → alpha engine (deterministic) → risk check → execute
    """
    logger.info("=== CYCLE START (parallel DAG) ===")
    publish_event("cycle_start")

    if is_system_halted():
        logger.warning("System is HALTED. Skipping cycle.")
        publish_event("cycle_skipped", {"reason": "system_halted"})
        return {"signals": [], "decisions": [], "executed": []}

    cleared = clear_stale_signals()
    if cleared:
        logger.info("Cleared %d stale signals", cleared)

    state: HedgeFundState = {"signals": [], "decisions": [], "executed": []}

    # Phase 1: Run 6 agents in parallel
    logger.info("Running 6 domain agents in parallel...")
    parallel_signals = run_parallel_agents()
    state["signals"].extend(parallel_signals)

    # Phase 2: Run quant after all others (needs their signals)
    sequential_signals = run_sequential_agents()
    state["signals"].extend(sequential_signals)

    logger.info("Total signals collected: %d", len(state["signals"]))

    # Phase 3: Alpha engine constructs portfolio (deterministic)
    state = construct_portfolio(state)

    # Phase 4: Execute decisions
    state = execute(state)

    publish_event("cycle_end", {"n_decisions": len(state["decisions"]), "n_executed": len(state["executed"])})
    logger.info("=== CYCLE END ===")

    return state
