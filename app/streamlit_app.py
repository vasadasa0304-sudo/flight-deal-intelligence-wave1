"""Streamlit entrypoint for Wave1 operations."""

from __future__ import annotations

import streamlit as st

from src.config import load_settings


def main() -> None:
    """Render the Wave1 operations home page."""
    settings = load_settings()
    st.set_page_config(page_title="Flight Deal Intelligence - Wave1", layout="wide")
    st.title("Flight Deal Intelligence - Wave1")
    st.caption("Internal operations app. Wave1 scope only.")
    st.write("Geography: Middle East + Turkey")
    st.write(f"Hubs: {', '.join(settings.wave1_hubs)}")
    st.write(f"Airlines: {', '.join(settings.wave1_airlines)}")


if __name__ == "__main__":
    main()

