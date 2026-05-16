"""Wave1 watchlist polling orchestration."""

from __future__ import annotations

import logging
from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from typing import Any

from sqlalchemy import text
from sqlalchemy.orm import Session

from src.ingestion.observation_writer import insert_observation
from src.ingestion.parser import parse_offer_payload

logger = logging.getLogger(__name__)


@dataclass(frozen=True)
class PollCounters:
    """Summary counters for one polling pass."""

    watch_rows_attempted: int
    observations_inserted: int
    duplicates: int
    parse_errors: int
    requests_failed: int
    status: str


def load_active_watch_rows(session: Session) -> list[dict[str, Any]]:
    """Load active watchlist rows with route endpoints."""
    result = session.execute(
        text(
            """
            SELECT
                w.watch_id,
                w.route_id,
                r.origin,
                r.destination,
                w.airline_code,
                w.cabin,
                w.booking_window_days,
                w.currency,
                w.poll_frequency_minutes,
                w.route_priority,
                w.strategic_tag
            FROM watchlist w
            JOIN routes r ON r.route_id = w.route_id
            WHERE w.is_active = TRUE
            ORDER BY w.watch_id
            """
        )
    )
    return [dict(row._mapping) for row in result]


def load_watch_row(session: Session, watch_id: int) -> dict[str, Any] | None:
    """Load one active watchlist row by id."""
    result = session.execute(
        text(
            """
            SELECT
                w.watch_id,
                w.route_id,
                r.origin,
                r.destination,
                w.airline_code,
                w.cabin,
                w.booking_window_days,
                w.currency,
                w.poll_frequency_minutes,
                w.route_priority,
                w.strategic_tag
            FROM watchlist w
            JOIN routes r ON r.route_id = w.route_id
            WHERE w.is_active = TRUE
              AND w.watch_id = :watch_id
            """
        ),
        {"watch_id": watch_id},
    ).first()
    return dict(result._mapping) if result is not None else None


async def one_pass(
    session: Session,
    amadeus_client: Any,
    watch_rows: Sequence[Mapping[str, Any]] | None = None,
) -> PollCounters:
    """Poll all active watchlist rows once and write a scheduler_runs row."""
    started_at = datetime.now(UTC)
    rows = [dict(row) for row in (watch_rows if watch_rows is not None else load_active_watch_rows(session))]
    inserted = 0
    duplicates = 0
    parse_errors = 0
    requests_failed = 0

    for row in rows:
        logger.debug(
            "Polling watch_id=%s route_id=%s airline=%s cabin=%s window=%s",
            row["watch_id"],
            row["route_id"],
            row["airline_code"],
            row["cabin"],
            row["booking_window_days"],
        )
        try:
            departure_date = datetime.now(UTC).date() + timedelta(
                days=int(row["booking_window_days"])
            )
            offers = await amadeus_client.search_flight_offers(
                origin=row["origin"],
                destination=row["destination"],
                departure_date=departure_date,
                cabin=row["cabin"],
                max_offers=10,
            )
            if not offers:
                parse_errors += 1
                logger.warning(
                    "No parseable offers for watch_id=%s route_id=%s.",
                    row["watch_id"],
                    row["route_id"],
                )
                continue

            observation = parse_offer_payload(
                {"data": offers},
                row,
                observed_at=datetime.now(UTC),
                session=session,
            )
            if observation is None:
                parse_errors += 1
                logger.warning(
                    "Parse error for watch_id=%s route_id=%s.",
                    row["watch_id"],
                    row["route_id"],
                )
                continue

            try:
                if insert_observation(session, observation):
                    inserted += 1
                else:
                    duplicates += 1
            except Exception as exc:  # noqa: BLE001
                requests_failed += 1
                logger.warning(
                    "Insert failure for watch_id=%s route_id=%s: %s",
                    row["watch_id"],
                    row["route_id"],
                    exc,
                )
        except Exception as exc:  # noqa: BLE001
            requests_failed += 1
            logger.exception(
                "Unexpected polling failure for watch_id=%s route_id=%s: %s",
                row.get("watch_id"),
                row.get("route_id"),
                exc,
            )

    attempted = len(rows)
    status = _run_status(attempted=attempted, requests_failed=requests_failed)
    finished_at = datetime.now(UTC)
    _write_scheduler_run(
        session,
        started_at=started_at,
        finished_at=finished_at,
        watch_rows_attempted=attempted,
        observations_inserted=inserted,
        requests_failed=requests_failed,
        status=status,
        notes=f"duplicates={duplicates}; parse_errors={parse_errors}",
    )
    session.flush()

    logger.info(
        "POLL pass complete: attempted=%d inserted=%d duplicates=%d parse_errors=%d "
        "requests_failed=%d status=%s",
        attempted,
        inserted,
        duplicates,
        parse_errors,
        requests_failed,
        status,
    )
    return PollCounters(
        watch_rows_attempted=attempted,
        observations_inserted=inserted,
        duplicates=duplicates,
        parse_errors=parse_errors,
        requests_failed=requests_failed,
        status=status,
    )


async def poll_one_watch_row(
    session: Session,
    amadeus_client: Any,
    watch_id: int,
) -> PollCounters:
    """Poll one active watchlist row as an APScheduler job."""
    row = load_watch_row(session, watch_id)
    if row is None:
        logger.warning("watch_id=%s is inactive or missing; skipping.", watch_id)
        return PollCounters(0, 0, 0, 0, 0, "SUCCESS")
    return await one_pass(session, amadeus_client, watch_rows=[row])


def _run_status(*, attempted: int, requests_failed: int) -> str:
    if attempted > 0 and requests_failed >= attempted:
        return "FAILED"
    if requests_failed > 0:
        return "PARTIAL"
    return "SUCCESS"


def _write_scheduler_run(
    session: Session,
    *,
    started_at: datetime,
    finished_at: datetime,
    watch_rows_attempted: int,
    observations_inserted: int,
    requests_failed: int,
    status: str,
    notes: str,
) -> None:
    session.execute(
        text(
            """
            INSERT INTO scheduler_runs (
                run_kind, started_at, finished_at, watch_rows_attempted,
                observations_inserted, requests_failed, status, notes
            )
            VALUES (
                'POLL', :started_at, :finished_at, :watch_rows_attempted,
                :observations_inserted, :requests_failed, :status, :notes
            )
            """
        ),
        {
            "started_at": started_at,
            "finished_at": finished_at,
            "watch_rows_attempted": watch_rows_attempted,
            "observations_inserted": observations_inserted,
            "requests_failed": requests_failed,
            "status": status,
            "notes": notes,
        },
    )


def poll_wave1_watchlist(settings: Any) -> PollCounters:
    """Compatibility wrapper for legacy imports."""
    settings.validate_wave1()
    raise RuntimeError("Use async one_pass() with a database session and AmadeusClient.")
