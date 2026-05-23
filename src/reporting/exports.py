"""Confirmed alert promotion and CSV exports."""

from __future__ import annotations

import csv
import logging
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Any

from sqlalchemy import text
from sqlalchemy.orm import Session

logger = logging.getLogger(__name__)

ALERT_EXPORT_COLUMNS = [
    "tier",
    "origin",
    "destination",
    "airline_code",
    "cabin",
    "fare_native",
    "native_currency",
    "fare_display",
    "display_currency",
    "baseline_price",
    "percent_saving",
    "absolute_saving",
    "booking_link",
    "valid_window",
    "urgency_flag",
    "verification_notes",
    "visibility",
]


@dataclass(frozen=True)
class AlertExportResult:
    """Result of one confirmed-alert CSV export."""

    path: Path
    row_count: int


def promote_to_alerts(session: Session) -> int:
    """Promote verified anomalies to READY alert rows and mark them exported."""
    rows = _verified_anomalies_without_alert(session)
    promoted = 0
    for row in rows:
        session.execute(
            text(
                """
                INSERT INTO alerts (
                    anomaly_id, tier, origin, destination, airline_code, cabin,
                    fare_native, native_currency, fare_display, display_currency,
                    baseline_price, absolute_saving, percent_saving, booking_link,
                    valid_window, urgency_flag, verification_notes, visibility, status
                )
                VALUES (
                    :anomaly_id, :tier, :origin, :destination, :airline_code, :cabin,
                    :fare_native, :native_currency, :fare_display, :display_currency,
                    :baseline_price, :absolute_saving, :percent_saving, :booking_link,
                    :valid_window, :urgency_flag, :verification_notes, :visibility, 'READY'
                )
                """
            ),
            {
                "anomaly_id": row["anomaly_id"],
                "tier": row["tier"],
                "origin": row["origin"],
                "destination": row["destination"],
                "airline_code": row["airline_code"],
                "cabin": row["cabin"],
                "fare_native": row["current_price"],
                "native_currency": row["currency"],
                "fare_display": row["display_price"],
                "display_currency": row["display_currency"],
                "baseline_price": row["baseline_price"],
                "absolute_saving": row["absolute_saving"],
                "percent_saving": row["percent_saving"],
                "booking_link": row["deeplink"],
                "valid_window": "typically 24-72h",
                "urgency_flag": _urgency_flag(row["tier"]),
                "verification_notes": row["verification_notes"],
                "visibility": "MEMBER" if row["tier"] == "PHANTOM_FARE" else "FREE",
            },
        )
        session.execute(
            text(
                """
                UPDATE detected_anomalies
                SET status = 'EXPORTED'
                WHERE id = :anomaly_id
                """
            ),
            {"anomaly_id": row["anomaly_id"]},
        )
        promoted += 1

    logger.info("Promoted %d verified anomalies to alerts.", promoted)
    return promoted


def export_ready_alerts(
    session: Session,
    export_dir: Path = Path("data/exports"),
    generated_at: datetime | None = None,
) -> AlertExportResult:
    """Export READY alerts from the last 24 hours and mark them EXPORTED."""
    generated_at = generated_at or datetime.now(UTC)
    export_dir.mkdir(parents=True, exist_ok=True)
    path = export_dir / f"confirmed_alerts_{generated_at:%Y%m%d}.csv"
    rows = _ready_alert_rows(session, generated_at - timedelta(hours=24))

    with path.open("w", encoding="utf-8", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=ALERT_EXPORT_COLUMNS)
        writer.writeheader()
        writer.writerows(
            {column: row[column] for column in ALERT_EXPORT_COLUMNS}
            for row in rows
        )

    if rows:
        session.execute(
            text(
                """
                UPDATE alerts
                SET status = 'EXPORTED',
                    exported_at = :exported_at
                WHERE id = ANY(:alert_ids)
                """
            ),
            {
                "exported_at": generated_at,
                "alert_ids": [row["_alert_id"] for row in rows],
            },
        )

    logger.info("Exported %d READY alerts to %s.", len(rows), path)
    return AlertExportResult(path=path, row_count=len(rows))


def export_placeholder(path: Path, rows: list[dict[str, object]]) -> Path:
    """Compatibility wrapper for older orchestration tests."""
    logger.info("Export placeholder prepared for %s with %s rows.", path, len(rows))
    return path


def _verified_anomalies_without_alert(session: Session) -> list[dict[str, Any]]:
    result = session.execute(
        text(
            """
            SELECT
                da.id AS anomaly_id,
                da.tier,
                da.current_price,
                da.baseline_price,
                da.currency,
                da.absolute_saving,
                da.percent_saving,
                po.origin,
                po.destination,
                po.airline_code,
                po.cabin,
                po.display_price,
                po.display_currency,
                po.deeplink,
                qa.notes AS verification_notes
            FROM detected_anomalies da
            JOIN price_observations po
              ON po.id = da.price_observation_id
            LEFT JOIN LATERAL (
                SELECT notes
                FROM qa_checks
                WHERE anomaly_id = da.id
                  AND result = 'CONFIRMED'
                ORDER BY checked_at DESC, id DESC
                LIMIT 1
            ) qa ON true
            WHERE da.status = 'VERIFIED'
              AND NOT EXISTS (
                  SELECT 1 FROM alerts a WHERE a.anomaly_id = da.id
              )
            ORDER BY da.detected_at ASC, da.id ASC
            """
        )
    )
    return [dict(row._mapping) for row in result]


def _ready_alert_rows(session: Session, since: datetime) -> list[dict[str, Any]]:
    result = session.execute(
        text(
            """
            SELECT
                id AS _alert_id,
                tier, origin, destination, airline_code, cabin,
                fare_native, native_currency, fare_display, display_currency,
                baseline_price, percent_saving, absolute_saving, booking_link,
                valid_window, urgency_flag, verification_notes, visibility
            FROM alerts
            WHERE status = 'READY'
              AND created_at >= :since
            ORDER BY created_at ASC, id ASC
            """
        ),
        {"since": since},
    )
    rows = []
    for row in result:
        mapping = dict(row._mapping)
        export_row = {column: mapping[column] for column in ALERT_EXPORT_COLUMNS}
        export_row["_alert_id"] = mapping["_alert_id"]
        rows.append(export_row)
    return rows


def _urgency_flag(tier: str) -> str:
    if tier == "PHANTOM_FARE":
        return "URGENT"
    if tier == "FLASH_DEAL":
        return "HIGH"
    return "NORMAL"
