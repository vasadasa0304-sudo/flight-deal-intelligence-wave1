"""Run backtest placeholder."""

from __future__ import annotations

from src.baselines.backtest import run_backtest
from src.logging_config import configure_logging


def main() -> None:
    """Run the placeholder backtest."""
    configure_logging()
    run_backtest()


if __name__ == "__main__":
    main()

