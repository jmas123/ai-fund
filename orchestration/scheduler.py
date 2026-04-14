"""Scheduler — APScheduler for market-hours cycles and nightly distillation."""

import logging
from datetime import datetime

from apscheduler.schedulers.blocking import BlockingScheduler
from apscheduler.triggers.cron import CronTrigger
from apscheduler.triggers.interval import IntervalTrigger

from memory.working_memory import is_system_halted
from orchestration.agent_graph import run_cycle
from orchestration.event_bus import publish_event

logger = logging.getLogger(__name__)


def _market_hours_cycle():
    """Wrapper that checks halt status before running a cycle."""
    now = datetime.now()
    logger.info("Scheduler tick at %s", now.strftime("%Y-%m-%d %H:%M:%S %Z"))

    if is_system_halted():
        logger.warning("System is HALTED — skipping cycle. Manual reset required.")
        publish_event("cycle_skipped", {"reason": "system_halted"})
        return

    try:
        run_cycle()
    except Exception as e:
        logger.error("Cycle failed: %s", e)
        publish_event("cycle_error", {"error": str(e)})


def _run_distillation():
    """Nightly distillation job."""
    logger.info("Running nightly distillation...")
    try:
        from memory.distill_job import run_distillation
        result = run_distillation()
        logger.info("Distillation complete: %d rules", result["total_rules"])
        publish_event("distillation_complete", result)
    except Exception as e:
        logger.error("Distillation failed: %s", e)
        publish_event("distillation_error", {"error": str(e)})


def start(interval_minutes: int = 90):
    """Start the scheduler with market-hours cycles and nightly distillation.

    - Cycles: Mon-Fri, every `interval_minutes` minutes, 09:30-16:00 ET
    - Distillation: Every day at 02:00 UTC
    """
    scheduler = BlockingScheduler(timezone="US/Eastern")

    # Market hours cycle: Mon-Fri 10:00-15:00 ET (every interval_minutes)
    # Note: minute step must be < 60; for 60-min interval use minute=0
    minute_expr = "0" if interval_minutes >= 60 else f"*/{interval_minutes}"
    scheduler.add_job(
        _market_hours_cycle,
        trigger=CronTrigger(
            day_of_week="mon-fri",
            hour="10-15",
            minute=minute_expr,
            timezone="US/Eastern",
        ),
        id="market_cycle",
        name="Market Hours Trading Cycle",
        misfire_grace_time=300,
    )

    # Also run at market open (9:30)
    scheduler.add_job(
        _market_hours_cycle,
        trigger=CronTrigger(
            day_of_week="mon-fri",
            hour=9,
            minute=30,
            timezone="US/Eastern",
        ),
        id="market_open_cycle",
        name="Market Open Cycle",
        misfire_grace_time=300,
    )

    # Nightly distillation: 02:00 UTC every day
    scheduler.add_job(
        _run_distillation,
        trigger=CronTrigger(
            hour=2,
            minute=0,
            timezone="UTC",
        ),
        id="nightly_distill",
        name="Nightly Distillation",
        misfire_grace_time=600,
    )

    logger.info("Scheduler started:")
    logger.info("  Cycles: Mon-Fri every %dm, 09:30-16:00 ET", interval_minutes)
    logger.info("  Distillation: daily at 02:00 UTC")
    logger.info("  System halt check: before every cycle")

    for job in scheduler.get_jobs():
        logger.info("  Job: %s → trigger: %s", job.name, job.trigger)

    try:
        scheduler.start()
    except (KeyboardInterrupt, SystemExit):
        logger.info("Scheduler shut down")
