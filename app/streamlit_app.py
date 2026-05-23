"""Streamlit entrypoint for Wave1 internal operations."""

from __future__ import annotations

import streamlit as st

from src.config import load_settings


def main() -> None:
    """Render the Wave1 operations home page."""
    settings = load_settings()
    st.set_page_config(page_title="Flight Deal Intelligence - Wave1", layout="wide")
    st.title("Flight Deal Intelligence - Wave1")
    st.caption("Internal operations dashboard. Wave1 scope only.")

    st.subheader("Locked Scope")
    col1, col2, col3 = st.columns(3)
    col1.metric("Geography", "Middle East + Turkey")
    col2.metric("Hubs", len(settings.wave1_hubs))
    col3.metric("Airlines", len(settings.wave1_airlines))

    st.write("Use the pages in the sidebar for watchlist, observations, QA, exports, and API usage.")
    st.dataframe(
        {
            "Scope item": ["Hubs", "Airlines", "Booking windows", "MVP cabins"],
            "Values": [
                ", ".join(settings.wave1_hubs),
                ", ".join(settings.wave1_airlines),
                ", ".join(str(value) for value in settings.wave1_booking_windows_days),
                ", ".join(settings.wave1_mvp_cabins),
            ],
        },
        width="stretch",
        hide_index=True,
    )


if __name__ == "__main__":
    main()
