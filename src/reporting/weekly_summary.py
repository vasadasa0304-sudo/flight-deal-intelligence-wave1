"""Weekly operational summary exports for Wave1."""

from __future__ import annotations

import csv
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from decimal import Decimal, ROUND_HALF_UP
from pathlib import Path
from typing import Any

from sqlalchemy import text
from sqlalchemy.orm import Session


@dataclass(frozen=True)
class WeeklySummary:
    """Wave1 weekly reporting metrics."""

    routes_monitored: int
    observations_collected: int
    anomalies_detected_by_tier: dict[str, int]
    anomalies_confirmed_by_tier: dict[str, int]
    rejection_rate: Decimal
    top_3_deals: list[dict[str, Any]]


@dataclass(frozen=True)
class WeeklySummaryExport:
    """Paths written for one weekly summary export."""

    markdown_path: Path
    csv_path: Path
    summary: WeeklySummary


def build_weekly_summary(
    session: Session | None = None,
    generated_at: datetime | None = None,
) -> WeeklySummary:
    """Build the last-7-days Wave1 operational summary."""
    if session is None:
        return WeeklySummary(
            routes_monitored=0,
            observations_collected=0,
            anomalies_detected_by_tier={},
            anomalies_confirmed_by_tier={},
            rejection_rate=Decimal("0.000"),
            top_3_deals=[],
        )

    generated_at = generated_at or datetime.now(UTC)
    since = generated_at - timedelta(days=7)
    return WeeklySummary(
        routes_monitored=_routes_monitored(session, since),
        observations_collected=_observations_collected(session, since),
        anomalies_detected_by_tier=_anomalies_by_tier(session, since, confirmed=False),
        anomalies_confirmed_by_tier=_anomalies_by_tier(session, since, confirmed=True),
        rejection_rate=_rejection_rate(session, since),
        top_3_deals=_top_3_deals(session, since),
    )


def write_weekly_summary(
    session: Session,
    export_dir: Path = Path("data/exports"),
    generated_at: datetime | None = None,
) -> WeeklySummaryExport:
    """Write weekly summary Markdown and CSV files."""
    generated_at = generated_at or datetime.now(UTC)
    export_dir.mkdir(parents=True, exist_ok=True)
    summary = build_weekly_summary(session, generated_at)
    markdown_path = export_dir / f"weekly_summary_{generated_at:%Y%m%d}.md"
    csv_path = export_dir / f"weekly_summary_{generated_at:%Y%m%d}.csv"
    markdown_path.write_text(render_weekly_summary_markdown(summary, generated_at), encoding="utf-8")
    _write_summary_csv(csv_path, summary)
    return WeeklySummaryExport(markdown_path=markdown_path, csv_path=csv_path, summary=summary)


def render_weekly_summary_markdown(summary: WeeklySummary, generated_at: datetime) -> str:
    """Render a weekly summary as Markdown."""
    lines = [
        f"# Wave1 Weekly Summary - {generated_at:%Y-%m-%d}",
        "",
        f"- Routes monitored: {summary.routes_monitored}",
        f"- Observations collected: {summary.observations_collected}",
        f"- Rejection rate: {_format_percent(summary.rejection_rate)}",
        "",
        "## Anomalies Detected By Tier",
    ]
    lines.extend(_tier_lines(summary.anomalies_detected_by_tier))
    lines.extend(["", "## Anomalies Confirmed By Tier"])
    lines.extend(_tier_lines(summary.anomalies_confirmed_by_tier))
    lines.extend(["", "## Top 3 Deals"])
    if summary.top_3_deals:
        for deal in summary.top_3_deals:
            lines.append(
                "- "
                f"{deal['tier']} {deal['origin']}->{deal['destination']} "
                f"{deal['airline_code']} {deal['cabin']}: "
                f"USD {_format_money(Decimal(str(deal['absolute_saving_usd'])))}"
            )
    else:
        lines.append("- None")
    lines.append("")
    return "\n".join(lines)


def _write_summary_csv(path: Path, summary: WeeklySummary) -> None:
    with path.open("w", encoding="utf-8", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=["metric", "key", "value"])
        writer.writeheader()
        writer.writerow({"metric": "routes_monitored", "key": "", "value": summary.routes_monitored})
        writer.writerow(
            {
                "metric": "observations_collected",
                "key": "",
                "value": summary.observations_collected,
            }
        )
        writer.writerow({"metric": "rejection_rate", "key": "", "value": summary.rejection_rate})
        for tier, count in sorted(summary.anomalies_detected_by_tier.items()):
            writer.writerow({"metric": "anomalies_detected", "key": tier, "value": count})
        for tier, count in sorted(summary.anomalies_confirmed_by_tier.items()):
            writer.writerow({"metric": "anomalies_confirmed", "key": tier, "value": count})
        for index, deal in enumerate(summary.top_3_deals, start=1):
            writer.writerow(
                {
                    "metric": "top_deal",
                    "key": str(index),
                    "value": (
                        f"{deal['tier']} {deal['origin']}->{deal['destination']} "
                        f"{deal['airline_code']} USD {deal['absolute_saving_usd']}"
                    ),
                }
            )


def _routes_monitored(session: Session, since: datetime) -> int:
    return int(
        session.execute(
            text("SELECT count(DISTINCT route_id) FROM price_observations WHERE observed_at >= :since"),
            {"since": since},
        ).scalar_one()
    )


def _observations_collected(session: Session, since: datetime) -> int:
    return int(
        session.execute(
            text("SELECT count(*) FROM price_observations WHERE observed_at >= :since"),
            {"since": since},
        ).scalar_one()
    )


def _anomalies_by_tier(session: Session, since: datetime, *, confirmed: bool) -> dict[str, int]:
    status_clause = "AND status IN ('VERIFIED', 'EXPORTED')" if confirmed else ""
    result = session.execute(
        text(
            f"""
            SELECT tier, count(*) AS count
            FROM detected_anomalies
            WHERE detected_at >= :since
            {status_clause}
            GROUP BY tier
            ORDER BY tier
            """
        ),
        {"since": since},
    )
    return {
        str(row._mapping["tier"]): int(row._mapping["count"])
        for row in result
    }


def _rejection_rate(session: Session, since: datetime) -> Decimal:
    row = session.execute(
        text(
            """
            SELECT
                count(*) FILTER (WHERE result = 'REJECTED') AS rejected,
                count(*) FILTER (WHERE result IN ('CONFIRMED', 'REJECTED')) AS denominator
            FROM qa_checks
            WHERE checked_at >= :since
            """
        ),
        {"since": since},
    ).one()
    denominator = int(row.denominator or 0)
    if denominator == 0:
        return Decimal("0.000")
    return (Decimal(int(row.rejected or 0)) / Decimal(denominator)).quantize(
        Decimal("0.001"),
        rounding=ROUND_HALF_UP,
    )


def _top_3_deals(session: Session, since: datetime) -> list[dict[str, Any]]:
    result = session.execute(
        text(
            """
            SELECT
                da.tier,
                po.origin,
                po.destination,
                po.airline_code,
                po.cabin,
                CASE
                    WHEN da.currency = 'USD' THEN da.absolute_saving
                    WHEN po.display_currency = 'USD' AND po.fx_rate_used IS NOT NULL
                        THEN da.absolute_saving * po.fx_rate_used
                    ELSE da.absolute_saving
                END AS absolute_saving_usd
            FROM detected_anomalies da
            JOIN price_observations po
              ON po.id = da.price_observation_id
            WHERE da.detected_at >= :since
            ORDER BY absolute_saving_usd DESC, da.id ASC
            LIMIT 3
            """
        ),
        {"since": since},
    )
    return [
        {
            "tier": row.tier,
            "origin": row.origin,
            "destination": row.destination,
            "airline_code": row.airline_code,
            "cabin": row.cabin,
            "absolute_saving_usd": Decimal(str(row.absolute_saving_usd)).quantize(
                Decimal("0.01"),
                rounding=ROUND_HALF_UP,
            ),
        }
        for row in result
    ]


def _tier_lines(counts: dict[str, int]) -> list[str]:
    if not counts:
        return ["- None"]
    return [f"- {tier}: {count}" for tier, count in sorted(counts.items())]


def _format_percent(value: Decimal) -> str:
    return f"{(value * Decimal('100')).quantize(Decimal('0.1'))}%"


def _format_money(value: Decimal) -> str:
    if value == value.to_integral():
        return f"{int(value):,}"
    return f"{value:,.2f}"
