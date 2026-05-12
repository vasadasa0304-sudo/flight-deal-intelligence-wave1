"""SQLAlchemy models for the Wave1 production schema."""

from __future__ import annotations

from datetime import date, datetime
from decimal import Decimal
from typing import Any

from sqlalchemy import (
    BigInteger,
    Boolean,
    CHAR,
    CheckConstraint,
    Date,
    DateTime,
    ForeignKey,
    Integer,
    Numeric,
    String,
    Text,
    UniqueConstraint,
    text,
)
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column
from sqlalchemy.sql import func


class Base(DeclarativeBase):
    """Base model class."""


# 1. airports
class Airport(Base):
    """Airport reference table."""

    __tablename__ = "airports"
    __table_args__ = (
        CheckConstraint("char_length(airport_code) = 3", name="ck_airports_airport_code_length"),
    )

    airport_code: Mapped[str] = mapped_column(CHAR(3), primary_key=True)
    city: Mapped[str] = mapped_column(Text, nullable=False)
    country: Mapped[str] = mapped_column(Text, nullable=False)
    region: Mapped[str] = mapped_column(Text, nullable=False)
    timezone: Mapped[str] = mapped_column(Text, nullable=False)
    is_wave1_hub: Mapped[bool] = mapped_column(
        Boolean,
        nullable=False,
        server_default=text("false"),
    )
    is_active: Mapped[bool] = mapped_column(Boolean, nullable=False, server_default=text("true"))
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        nullable=False,
        server_default=func.now(),
    )


# 2. airlines
class Airline(Base):
    """Airline reference table."""

    __tablename__ = "airlines"
    __table_args__ = (
        CheckConstraint("carrier_type in ('FSC', 'LCC', 'HYBRID')", name="ck_airlines_carrier_type"),
        CheckConstraint(
            "char_length(airline_code) between 2 and 3",
            name="ck_airlines_airline_code_length",
        ),
    )

    airline_code: Mapped[str] = mapped_column(String(3), primary_key=True)
    airline_name: Mapped[str] = mapped_column(Text, nullable=False)
    carrier_type: Mapped[str] = mapped_column(Text, nullable=False)
    primary_hub: Mapped[str | None] = mapped_column(Text)
    is_wave1_airline: Mapped[bool] = mapped_column(
        Boolean,
        nullable=False,
        server_default=text("false"),
    )
    is_active: Mapped[bool] = mapped_column(Boolean, nullable=False, server_default=text("true"))
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        nullable=False,
        server_default=func.now(),
    )


# 3. routes
class Route(Base):
    """Route reference table selected from the locked Wave1 route file."""

    __tablename__ = "routes"
    __table_args__ = (
        CheckConstraint("route_type in ('INTERNATIONAL', 'DOMESTIC')", name="ck_routes_route_type"),
        CheckConstraint(
            "route_priority in ('TIER_1_DAILY', 'TIER_2_EVERY_2_DAYS', 'STANDARD')",
            name="ck_routes_route_priority",
        ),
        CheckConstraint(
            "strategic_tag in ('STANDARD', 'WAVE_2_PRESEED', 'WAVE_3_PRESEED')",
            name="ck_routes_strategic_tag",
        ),
        CheckConstraint("origin <> destination", name="ck_routes_origin_destination_distinct"),
    )

    route_id: Mapped[str] = mapped_column(Text, primary_key=True)
    origin: Mapped[str] = mapped_column(CHAR(3), ForeignKey("airports.airport_code"), nullable=False)
    destination: Mapped[str] = mapped_column(
        CHAR(3),
        ForeignKey("airports.airport_code"),
        nullable=False,
    )
    route_type: Mapped[str] = mapped_column(Text, nullable=False)
    route_priority: Mapped[str] = mapped_column(Text, nullable=False)
    strategic_tag: Mapped[str] = mapped_column(Text, nullable=False)
    strategic_relevance: Mapped[str | None] = mapped_column(Text)
    carrier_overlap_notes: Mapped[str | None] = mapped_column(Text)
    source_document_note: Mapped[str] = mapped_column(Text, nullable=False)
    is_new_launch: Mapped[bool] = mapped_column(Boolean, nullable=False, server_default=text("false"))
    is_active: Mapped[bool] = mapped_column(Boolean, nullable=False, server_default=text("true"))
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        nullable=False,
        server_default=func.now(),
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        nullable=False,
        server_default=func.now(),
    )


# 4. route_carriers
class RouteCarrier(Base):
    """Carrier participation and role on a route."""

    __tablename__ = "route_carriers"
    __table_args__ = (
        CheckConstraint(
            "role_on_route in ('PRIMARY', 'SECONDARY', 'LCC_PRESSURE', 'LEGACY_COMPETITOR')",
            name="ck_route_carriers_role_on_route",
        ),
        UniqueConstraint("route_id", "airline_code", name="uq_route_carriers_route_airline"),
    )

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True, autoincrement=True)
    route_id: Mapped[str] = mapped_column(
        Text,
        ForeignKey("routes.route_id", ondelete="CASCADE"),
        nullable=False,
    )
    airline_code: Mapped[str] = mapped_column(
        String(3),
        ForeignKey("airlines.airline_code"),
        nullable=False,
    )
    role_on_route: Mapped[str] = mapped_column(Text, nullable=False)
    is_primary_wave1_carrier: Mapped[bool] = mapped_column(
        Boolean,
        nullable=False,
        server_default=text("false"),
    )
    notes: Mapped[str | None] = mapped_column(Text)


# 5. watchlist
class Watchlist(Base):
    """Active and inactive monitoring rows."""

    __tablename__ = "watchlist"
    __table_args__ = (
        CheckConstraint(
            "cabin in ('ECONOMY', 'PREMIUM_ECONOMY', 'BUSINESS', 'FIRST')",
            name="ck_watchlist_cabin",
        ),
        CheckConstraint("booking_window_days in (14, 60)", name="ck_watchlist_booking_window_days"),
        CheckConstraint("poll_frequency_minutes > 0", name="ck_watchlist_poll_frequency_minutes"),
        CheckConstraint(
            "not is_active or cabin in ('ECONOMY', 'BUSINESS')",
            name="ck_watchlist_active_wave1_mvp_cabins",
        ),
        UniqueConstraint(
            "route_id",
            "airline_code",
            "cabin",
            "booking_window_days",
            name="uq_watchlist_route_airline_cabin_window",
        ),
    )

    watch_id: Mapped[int] = mapped_column(BigInteger, primary_key=True, autoincrement=True)
    route_id: Mapped[str] = mapped_column(Text, ForeignKey("routes.route_id"), nullable=False)
    airline_code: Mapped[str] = mapped_column(
        String(3),
        ForeignKey("airlines.airline_code"),
        nullable=False,
    )
    cabin: Mapped[str] = mapped_column(Text, nullable=False)
    booking_window_days: Mapped[int] = mapped_column(Integer, nullable=False)
    currency: Mapped[str] = mapped_column(CHAR(3), nullable=False)
    poll_frequency_minutes: Mapped[int] = mapped_column(Integer, nullable=False)
    route_priority: Mapped[str] = mapped_column(Text, nullable=False)
    strategic_tag: Mapped[str] = mapped_column(Text, nullable=False)
    is_active: Mapped[bool] = mapped_column(Boolean, nullable=False, server_default=text("true"))
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        nullable=False,
        server_default=func.now(),
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        nullable=False,
        server_default=func.now(),
    )


# 6. price_observations
class PriceObservation(Base):
    """Append-only fare observation."""

    __tablename__ = "price_observations"
    __table_args__ = (
        UniqueConstraint(
            "request_hash",
            "polling_bucket_hour",
            name="uq_price_observations_request_bucket",
        ),
        CheckConstraint("native_price >= 0", name="ck_price_observations_native_price"),
        CheckConstraint("display_price >= 0", name="ck_price_observations_display_price"),
    )

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True, autoincrement=True)
    watch_id: Mapped[int] = mapped_column(
        BigInteger,
        ForeignKey("watchlist.watch_id"),
        nullable=False,
    )
    route_id: Mapped[str] = mapped_column(Text, ForeignKey("routes.route_id"), nullable=False)
    origin: Mapped[str] = mapped_column(CHAR(3), nullable=False)
    destination: Mapped[str] = mapped_column(CHAR(3), nullable=False)
    airline_code: Mapped[str] = mapped_column(
        String(3),
        ForeignKey("airlines.airline_code"),
        nullable=False,
    )
    cabin: Mapped[str] = mapped_column(Text, nullable=False)
    booking_window_days: Mapped[int] = mapped_column(Integer, nullable=False)
    departure_date: Mapped[date] = mapped_column(Date, nullable=False)
    return_date: Mapped[date | None] = mapped_column(Date)
    native_currency: Mapped[str] = mapped_column(CHAR(3), nullable=False)
    native_price: Mapped[Decimal] = mapped_column(Numeric(12, 2), nullable=False)
    taxes_fees: Mapped[Decimal | None] = mapped_column(Numeric(12, 2))
    display_currency: Mapped[str] = mapped_column(CHAR(3), nullable=False)
    display_price: Mapped[Decimal] = mapped_column(Numeric(12, 2), nullable=False)
    fx_rate_used: Mapped[Decimal | None] = mapped_column(Numeric(18, 8))
    source: Mapped[str] = mapped_column(Text, nullable=False)
    deeplink: Mapped[str | None] = mapped_column(Text)
    request_hash: Mapped[str] = mapped_column(Text, nullable=False)
    polling_bucket_hour: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    observed_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    raw_response: Mapped[dict[str, Any]] = mapped_column(JSONB, nullable=False)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        nullable=False,
        server_default=func.now(),
    )


# 7. fx_rates
class FxRate(Base):
    """Daily FX reference rate."""

    __tablename__ = "fx_rates"

    rate_date: Mapped[date] = mapped_column(Date, primary_key=True)
    from_currency: Mapped[str] = mapped_column(CHAR(3), primary_key=True)
    to_currency: Mapped[str] = mapped_column(CHAR(3), primary_key=True)
    rate: Mapped[Decimal] = mapped_column(Numeric(18, 8), nullable=False)
    source: Mapped[str] = mapped_column(Text, primary_key=True)
    fetched_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        nullable=False,
        server_default=func.now(),
    )


# 8. baselines
class Baseline(Base):
    """30-day baseline summary for one watchlist grain."""

    __tablename__ = "baselines"
    __table_args__ = (
        CheckConstraint(
            "baseline_health in ('GOOD', 'THIN', 'MISSING', 'OUTLIER_RISK')",
            name="ck_baselines_baseline_health",
        ),
        UniqueConstraint("watch_id", "baseline_date", name="uq_baselines_watch_date"),
    )

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True, autoincrement=True)
    watch_id: Mapped[int] = mapped_column(
        BigInteger,
        ForeignKey("watchlist.watch_id"),
        nullable=False,
    )
    route_id: Mapped[str] = mapped_column(Text, nullable=False)
    origin: Mapped[str] = mapped_column(CHAR(3), nullable=False)
    destination: Mapped[str] = mapped_column(CHAR(3), nullable=False)
    airline_code: Mapped[str] = mapped_column(String(3), nullable=False)
    cabin: Mapped[str] = mapped_column(Text, nullable=False)
    booking_window_days: Mapped[int] = mapped_column(Integer, nullable=False)
    native_currency: Mapped[str] = mapped_column(CHAR(3), nullable=False)
    baseline_date: Mapped[date] = mapped_column(Date, nullable=False)
    window_start_date: Mapped[date] = mapped_column(Date, nullable=False)
    window_end_date: Mapped[date] = mapped_column(Date, nullable=False)
    median_price_native: Mapped[Decimal] = mapped_column(Numeric(12, 2), nullable=False)
    min_price_native: Mapped[Decimal] = mapped_column(Numeric(12, 2), nullable=False)
    max_price_native: Mapped[Decimal] = mapped_column(Numeric(12, 2), nullable=False)
    p25_price_native: Mapped[Decimal] = mapped_column(Numeric(12, 2), nullable=False)
    p75_price_native: Mapped[Decimal] = mapped_column(Numeric(12, 2), nullable=False)
    iqr_price_native: Mapped[Decimal] = mapped_column(Numeric(12, 2), nullable=False)
    observation_count: Mapped[int] = mapped_column(Integer, nullable=False)
    baseline_health: Mapped[str] = mapped_column(Text, nullable=False)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        nullable=False,
        server_default=func.now(),
    )


# 9. detected_anomalies
class DetectedAnomaly(Base):
    """Detected anomaly before and after QA/export state transitions."""

    __tablename__ = "detected_anomalies"
    __table_args__ = (
        CheckConstraint(
            "tier in ('DEAL', 'FLASH_DEAL', 'PHANTOM_FARE')",
            name="ck_detected_anomalies_tier",
        ),
        CheckConstraint(
            "confidence_score between 0 and 1",
            name="ck_detected_anomalies_confidence_score",
        ),
        CheckConstraint(
            "threshold_set in ('SOW', 'LCC_EXPERIMENTAL')",
            name="ck_detected_anomalies_threshold_set",
        ),
        CheckConstraint(
            "status in ('DETECTED', 'VERIFIED', 'REJECTED', 'EXPORTED', 'ESCALATED')",
            name="ck_detected_anomalies_status",
        ),
    )

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True, autoincrement=True)
    price_observation_id: Mapped[int] = mapped_column(
        BigInteger,
        ForeignKey("price_observations.id"),
        nullable=False,
    )
    baseline_id: Mapped[int] = mapped_column(BigInteger, ForeignKey("baselines.id"), nullable=False)
    watch_id: Mapped[int] = mapped_column(
        BigInteger,
        ForeignKey("watchlist.watch_id"),
        nullable=False,
    )
    tier: Mapped[str] = mapped_column(Text, nullable=False)
    current_price: Mapped[Decimal] = mapped_column(Numeric(12, 2), nullable=False)
    baseline_price: Mapped[Decimal] = mapped_column(Numeric(12, 2), nullable=False)
    currency: Mapped[str] = mapped_column(CHAR(3), nullable=False)
    absolute_saving: Mapped[Decimal] = mapped_column(Numeric(12, 2), nullable=False)
    percent_saving: Mapped[Decimal] = mapped_column(Numeric(6, 2), nullable=False)
    confidence_score: Mapped[Decimal] = mapped_column(Numeric(4, 3), nullable=False)
    detection_reason: Mapped[str | None] = mapped_column(Text)
    threshold_set: Mapped[str] = mapped_column(Text, nullable=False)
    status: Mapped[str] = mapped_column(Text, nullable=False, server_default=text("'DETECTED'"))
    detected_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        nullable=False,
        server_default=func.now(),
    )


# 10. qa_checks
class QaCheck(Base):
    """QA verification event for a detected anomaly."""

    __tablename__ = "qa_checks"
    __table_args__ = (
        CheckConstraint(
            "verification_source in ('AMADEUS_PRICE', 'DUFFEL', 'MANUAL')",
            name="ck_qa_checks_verification_source",
        ),
        CheckConstraint(
            "result in ('CONFIRMED', 'REJECTED', 'ESCALATED')",
            name="ck_qa_checks_result",
        ),
    )

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True, autoincrement=True)
    anomaly_id: Mapped[int] = mapped_column(
        BigInteger,
        ForeignKey("detected_anomalies.id"),
        nullable=False,
    )
    checked_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        nullable=False,
        server_default=func.now(),
    )
    verification_source: Mapped[str] = mapped_column(Text, nullable=False)
    verified_price: Mapped[Decimal | None] = mapped_column(Numeric(12, 2))
    verified_currency: Mapped[str | None] = mapped_column(CHAR(3))
    result: Mapped[str] = mapped_column(Text, nullable=False)
    notes: Mapped[str | None] = mapped_column(Text)
    restrictions: Mapped[str | None] = mapped_column(Text)
    checked_by: Mapped[str | None] = mapped_column(Text)


# 11. alerts
class Alert(Base):
    """QA-approved alert payload state."""

    __tablename__ = "alerts"
    __table_args__ = (
        CheckConstraint("visibility in ('FREE', 'MEMBER')", name="ck_alerts_visibility"),
        CheckConstraint("status in ('READY', 'EXPORTED', 'EXPIRED')", name="ck_alerts_status"),
    )

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True, autoincrement=True)
    anomaly_id: Mapped[int] = mapped_column(
        BigInteger,
        ForeignKey("detected_anomalies.id"),
        nullable=False,
    )
    tier: Mapped[str] = mapped_column(Text, nullable=False)
    origin: Mapped[str] = mapped_column(CHAR(3), nullable=False)
    destination: Mapped[str] = mapped_column(CHAR(3), nullable=False)
    airline_code: Mapped[str] = mapped_column(String(3), nullable=False)
    cabin: Mapped[str] = mapped_column(Text, nullable=False)
    fare_native: Mapped[Decimal] = mapped_column(Numeric(12, 2), nullable=False)
    native_currency: Mapped[str] = mapped_column(CHAR(3), nullable=False)
    fare_display: Mapped[Decimal] = mapped_column(Numeric(12, 2), nullable=False)
    display_currency: Mapped[str] = mapped_column(CHAR(3), nullable=False)
    baseline_price: Mapped[Decimal] = mapped_column(Numeric(12, 2), nullable=False)
    absolute_saving: Mapped[Decimal] = mapped_column(Numeric(12, 2), nullable=False)
    percent_saving: Mapped[Decimal] = mapped_column(Numeric(6, 2), nullable=False)
    booking_link: Mapped[str | None] = mapped_column(Text)
    valid_window: Mapped[str | None] = mapped_column(Text)
    urgency_flag: Mapped[str | None] = mapped_column(Text)
    verification_notes: Mapped[str | None] = mapped_column(Text)
    visibility: Mapped[str] = mapped_column(Text, nullable=False, server_default=text("'FREE'"))
    status: Mapped[str] = mapped_column(Text, nullable=False, server_default=text("'READY'"))
    exported_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        nullable=False,
        server_default=func.now(),
    )


# 12. api_request_logs
class ApiRequestLog(Base):
    """Provider API request audit log."""

    __tablename__ = "api_request_logs"

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True, autoincrement=True)
    provider: Mapped[str] = mapped_column(Text, nullable=False)
    endpoint: Mapped[str] = mapped_column(Text, nullable=False)
    method: Mapped[str] = mapped_column(Text, nullable=False)
    status_code: Mapped[int | None] = mapped_column(Integer)
    duration_ms: Mapped[int | None] = mapped_column(Integer)
    success: Mapped[bool] = mapped_column(Boolean, nullable=False)
    error_message: Mapped[str | None] = mapped_column(Text)
    request_id: Mapped[str | None] = mapped_column(Text)
    estimated_cost_usd: Mapped[Decimal | None] = mapped_column(Numeric(8, 4))
    requested_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        nullable=False,
        server_default=func.now(),
    )


# 13. scheduler_runs
class SchedulerRun(Base):
    """Scheduled job run audit log."""

    __tablename__ = "scheduler_runs"
    __table_args__ = (
        CheckConstraint(
            "status in ('RUNNING', 'SUCCESS', 'PARTIAL', 'FAILED')",
            name="ck_scheduler_runs_status",
        ),
    )

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True, autoincrement=True)
    run_kind: Mapped[str] = mapped_column(Text, nullable=False)
    started_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    finished_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    watch_rows_attempted: Mapped[int | None] = mapped_column(Integer)
    observations_inserted: Mapped[int | None] = mapped_column(Integer)
    requests_failed: Mapped[int | None] = mapped_column(Integer)
    status: Mapped[str] = mapped_column(Text, nullable=False)
    notes: Mapped[str | None] = mapped_column(Text)
