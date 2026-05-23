"""Tests for confirmed alert Markdown formatting."""

from __future__ import annotations

from decimal import Decimal

from src.reporting.alert_formatter import format_alert_markdown


def test_markdown_block_contains_all_required_lines() -> None:
    alert = {
        "tier": "FLASH_DEAL",
        "origin": "IST",
        "destination": "DXB",
        "airline_code": "TK",
        "cabin": "ECONOMY",
        "fare_native": Decimal("420.00"),
        "native_currency": "AED",
        "fare_display": Decimal("114.00"),
        "display_currency": "USD",
        "baseline_price": Decimal("1050.00"),
        "percent_saving": Decimal("60.00"),
        "absolute_saving": Decimal("630.00"),
        "booking_link": "https://example.test/book",
        "valid_window": "typically 24-72h",
        "verification_notes": "fare verified",
    }

    block = format_alert_markdown(alert)

    assert "Flash Deal: IST -> DXB on TK, ECONOMY" in block
    assert "Fare: AED 420 (~USD 114)" in block
    assert "Baseline: AED 1,050 (~USD 285)" in block
    assert "Saving: 60% / USD 171" in block
    assert "Booking: https://example.test/book" in block
    assert "Valid: typically 24-72h" in block
    assert "Notes: fare verified" in block


def test_phantom_fare_markdown_is_member_only_prefixed() -> None:
    alert = {
        "tier": "PHANTOM_FARE",
        "origin": "IST",
        "destination": "DXB",
        "airline_code": "TK",
        "cabin": "BUSINESS",
        "fare_native": Decimal("100.00"),
        "native_currency": "USD",
        "fare_display": Decimal("100.00"),
        "display_currency": "USD",
        "baseline_price": Decimal("400.00"),
        "percent_saving": Decimal("75.00"),
        "absolute_saving": Decimal("300.00"),
        "booking_link": None,
        "valid_window": None,
        "verification_notes": "manual override documented",
    }

    block = format_alert_markdown(alert)

    assert block.startswith("(MEMBER ONLY) Phantom Fare:")
    assert "Booking: via TK direct" in block
