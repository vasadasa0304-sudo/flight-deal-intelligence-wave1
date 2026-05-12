"""Build baseline placeholders."""

from __future__ import annotations

import pandas as pd

from src.baselines.baseline_job import compute_rolling_median_baselines
from src.logging_config import configure_logging


def main() -> None:
    """Run the baseline placeholder on an empty frame."""
    configure_logging()
    compute_rolling_median_baselines(pd.DataFrame())


if __name__ == "__main__":
    main()

