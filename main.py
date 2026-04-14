"""APEX Fund — entry point."""

import logging
import sys

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
)
logger = logging.getLogger("apex")


def main():
    if len(sys.argv) < 2:
        print("Usage: python main.py [cycle|scheduler|distill|perf|signals]")
        sys.exit(1)

    command = sys.argv[1]

    if command == "cycle":
        from orchestration.agent_graph import run_cycle
        run_cycle()

    elif command == "scheduler":
        from orchestration.scheduler import start
        interval = int(sys.argv[2]) if len(sys.argv) > 2 else 60
        start(interval_minutes=interval)

    elif command == "distill":
        from memory.distill_job import run_distillation
        result = run_distillation()
        print(f"Distillation complete: {result['total_rules']} rules across {len(result['domains'])} domains")

    elif command == "perf":
        from execution.performance import run_report
        days = int(sys.argv[2]) if len(sys.argv) > 2 else 30
        print(run_report(days=days))

    elif command == "signals":
        from execution.signal_analysis import run_report
        print(run_report())

    else:
        print(f"Unknown command: {command}")
        sys.exit(1)


if __name__ == "__main__":
    main()
