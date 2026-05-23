"""SQLAlchemy 2.x declarative models for the Wave1 flight-deal schema.

Table names, column names, constraints, and indexes all mirror
migrations/001_init.sql and migrations/002_grain_constraints.sql exactly.
If Base.metadata.create_all() is used for dev/test setup it produces the
same schema as the SQL migrations (minus trigger/function DDL that is not
expressed here — always prefer running the SQL files in production).

One section per table; sections ordered to match the migration file.
"""

from __future__ import annotations

from datetime import date, datetime
from decimal import Decimal

from sqlalchemy import (
    BigInteger,
    Boolean,
    CheckConstraint,
    Date,
    ForeignKey,
    ForeignKeyConstraint,
    Index,
    Integer,
    Numeric,
    String,
    Text,
    UniqueConstraint,
)
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column, relationship
from sqlalchemy.sql import func


class Base(DeclarativeBase):
    """Shared declarative base for all Wave1 models."""


# ---------------------------------------------------------------------------
# Reference tables
# ---------------------------------------------------------------------------


class Airport(Base):
    __tablename__ = "airports"
    __table_args__ = (
        CheckConstraint("char_length(airport_code) = 3", name="ck_airports_airport_code_length"),
    )

    airport_code: Mapped[str] = mapped_column(String(3), primary_key=True)
    city: Mapped[str] = mapped_column(Text, nullable=False)
    country: Mapped[str] = mapped_column(Text, nullable=False)
    region: Mapped[str] = mapped_column(Text, nullable=False)
    timezone: Mapped[str] = mapped_column(Text, nullable=False)
    is_wave1_hub: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)
    is_active: Mapped[bool] = mapped_column(Boolean, nullable=False, default=True)
    created_at: Mapped[datetime] = mapped_column(server_default=func.now(), nullable=False)


class Airline(Base):
    __tablename__ = "airlines"
    __table_args__ = (
        CheckConstraint("carrier_type in ('FSC', 'LCC', 'HYBRID')", name="ck_airlines_carrier_type"),
        CheckConstraint("char_length(airline_code) between 2 and 3", name="ck_airlines_airline_code_length"),
    )

    airline_code: Mapped[str] = mapped_column(String(3), primary_key=True)
    airline_name: Mapped[str] = mapped_column(Text, nullable=False)
    carrier_type: Mapped[str] = mapped_column(Text, nullable=False)
    primary_hub: Mapped[str | None] = mapped_column(Text)
    is_wave1_airline: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)
    is_active: Mapped[bool] = mapped_column(Boolean, nullable=False, default=True)
    created_at: Mapped[datetime] = mapped_column(server_default=func.now(), nullable=False)


class Route(Base):
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
    origin: Mapped[str] = mapped_column(String(3), ForeignKey("airports.airport_code"), nullable=False)
    destination: Mapped[str] = mapped_column(String(3), ForeignKey("airports.airport_code"), nullable=False)
    route_type: Mapped[str] = mapped_column(Text, nullable=False)
    route_priority: Mapped[str] = mapped_column(Text, nullable=False)
    strategic_tag: Mapped[str] = mapped_column(Text, nullable=False)
    strategic_relevance: Mapped[str | None] = mapped_column(Text)
    carrier_overlap_notes: Mapped[str | None] = mapped_column(Text)
    source_document_note: Mapped[str] = mapped_column(Text, nullable=False)
    is_new_launch: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)
    is_active: Mapped[bool] = mapped_column(Boolean, nullable=False, default=True)
    created_at: Mapped[datetime] = mapped_column(server_default=func.now(), nullable=False)
    updated_at: Mapped[datetime] = mapped_column(server_default=func.now(), nullable=False)


class RouteCarrier(Base):
    __tablename__ = "route_carriers"
    __table_args__ = (
        CheckConstraint(
            "role_on_route in ('PRIMARY', 'SECONDARY', 'LCC_PRESSURE', 'LEGACY_COMPETITOR')",
            name="ck_route_carriers_role_on_route",
        ),
        UniqueConstraint("route_id", "airline_code", name="uq_route_carriers_route_airline"),
    )

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True)
    route_id: Mapped[str] = mapped_column(Text, ForeignKey("routes.route_id", ondelete="CASCADE"), nullable=False)
    airline_code: Mapped[str] = mapped_column(String(3), ForeignKey("airlines.airline_code"), nullable=False)
    role_on_route: Mapped[str] = mapped_column(Text, nullable=False)
    is_primary_wave1_carrier: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)
    notes: Mapped[str | None] = mapped_column(Text)


# ---------------------------------------------------------------------------
# Watchlist
# ---------------------------------------------------------------------------


class Watchlist(Base):
    """One active monitoring slot: (route, airline, cabin, booking-window) grain."""

    __tablename__ = "watchlist"
    __table_args__ = (
        CheckConstraint("cabin in ('ECONOMY', 'PREMIUM_ECONOMY', 'BUSINESS', 'FIRST')", name="ck_watchlist_cabin"),
        CheckConstraint("booking_window_days in (14, 60)", name="ck_watchlist_booking_window_days"),
        CheckConstraint("poll_frequency_minutes > 0", name="ck_watchlist_poll_frequency_minutes"),
        CheckConstraint("not is_active or cabin in ('ECONOMY', 'BUSINESS')", name="ck_watchlist_active_wave1_mvp_cabins"),
        UniqueConstraint("route_id", "airline_code", "cabin", "booking_window_days", name="uq_watchlist_route_airline_cabin_window"),
        # Composite unique — required as FK target for grain consistency checks on observations and baselines.
        UniqueConstraint("watch_id", "route_id", "airline_code", "cabin", "booking_window_days", name="uq_watchlist_grain"),
    )

    watch_id: Mapped[int] = mapped_column(BigInteger, primary_key=True)
    route_id: Mapped[str] = mapped_column(Text, ForeignKey("routes.route_id"), nullable=False)
    airline_code: Mapped[str] = mapped_column(String(3), ForeignKey("airlines.airline_code"), nullable=False)
    cabin: Mapped[str] = mapped_column(Text, nullable=False)
    booking_window_days: Mapped[int] = mapped_column(Integer, nullable=False)
    currency: Mapped[str] = mapped_column(String(3), nullable=False)
    poll_frequency_minutes: Mapped[int] = mapped_column(Integer, nullable=False)
    route_priority: Mapped[str] = mapped_column(Text, nullable=False)
    strategic_tag: Mapped[str] = mapped_column(Text, nullable=False)
    is_active: Mapped[bool] = mapped_column(Boolean, nullable=False, default=True)
    created_at: Mapped[datetime] = mapped_column(server_default=func.now(), nullable=False)
    updated_at: Mapped[datetime] = mapped_column(server_default=func.now(), nullable=False)

    observations: Mapped[list["PriceObservation"]] = relationship(
        back_populates="watchlist_row",
        foreign_keys="[PriceObservation.watch_id]",
        primaryjoin="Watchlist.watch_id == PriceObservation.watch_id",
    )
    baselines: Mapped[list["Baseline"]] = relationship(
        back_populates="watchlist_row",
        foreign_keys="[Baseline.watch_id]",
        primaryjoin="Watchlist.watch_id == Baseline.watch_id",
    )


# ---------------------------------------------------------------------------
# Price observations (APPEND-ONLY)
# ---------------------------------------------------------------------------


class PriceObservation(Base):
    """Append-only fare snapshot.  Never UPDATE or DELETE rows from this table."""

    __tablename__ = "price_observations"
    __table_args__ = (
        UniqueConstraint("request_hash", "polling_bucket_hour", name="uq_price_observations_request_bucket"),
        # Grain FK — ensures denormalised fields match the watchlist row for watch_id.
        ForeignKeyConstraint(
            ["watch_id", "route_id", "airline_code", "cabin", "booking_window_days"],
            ["watchlist.watch_id", "watchlist.route_id", "watchlist.airline_code", "watchlist.cabin", "watchlist.booking_window_days"],
            name="fk_price_observations_watchlist_grain",
        ),
        # Composite unique so detected_anomalies can cross-check (id, watch_id).
        UniqueConstraint("id", "watch_id", name="uq_price_observations_id_watch"),
        CheckConstraint("native_price >= 0", name="ck_price_observations_native_price"),
        CheckConstraint("display_price >= 0", name="ck_price_observations_display_price"),
        Index("ix_price_observations_watch_observed", "watch_id", "observed_at"),
        Index("ix_price_observations_route_observed", "route_id", "observed_at"),
        Index("ix_price_observations_airline_cabin_window_observed", "airline_code", "cabin", "booking_window_days", "observed_at"),
        Index("ix_price_observations_polling_bucket_hour", "polling_bucket_hour"),
    )

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True)
    watch_id: Mapped[int] = mapped_column(BigInteger, ForeignKey("watchlist.watch_id"), nullable=False)
    route_id: Mapped[str] = mapped_column(Text, ForeignKey("routes.route_id"), nullable=False)
    origin: Mapped[str] = mapped_column(String(3), nullable=False)
    destination: Mapped[str] = mapped_column(String(3), nullable=False)
    airline_code: Mapped[str] = mapped_column(String(3), ForeignKey("airlines.airline_code"), nullable=False)
    cabin: Mapped[str] = mapped_column(Text, nullable=False)
    booking_window_days: Mapped[int] = mapped_column(Integer, nullable=False)
    departure_date: Mapped[date] = mapped_column(Date, nullable=False)
    return_date: Mapped[date | None] = mapped_column(Date)
    native_currency: Mapped[str] = mapped_column(String(3), nullable=False)
    native_price: Mapped[Decimal] = mapped_column(Numeric(12, 2), nullable=False)
    taxes_fees: Mapped[Decimal | None] = mapped_column(Numeric(12, 2))
    display_currency: Mapped[str] = mapped_column(String(3), nullable=False)
    display_price: Mapped[Decimal] = mapped_column(Numeric(12, 2), nullable=False)
    fx_rate_used: Mapped[Decimal | None] = mapped_column(Numeric(18, 8))
    source: Mapped[str] = mapped_column(Text, nullable=False)
    deeplink: Mapped[str | None] = mapped_column(Text)
    request_hash: Mapped[str] = mapped_column(Text, nullable=False)
    polling_bucket_hour: Mapped[datetime] = mapped_column(nullable=False)
    observed_at: Mapped[datetime] = mapped_column(nullable=False)
    raw_response: Mapped[dict] = mapped_column(JSONB, nullable=False)
    created_at: Mapped[datetime] = mapped_column(server_default=func.now(), nullable=False)

    watchlist_row: Mapped[Watchlist] = relationship(
        back_populates="observations",
        foreign_keys=[watch_id],
        primaryjoin="PriceObservation.watch_id == Watchlist.watch_id",
    )


# ---------------------------------------------------------------------------
# FX rates
# ---------------------------------------------------------------------------


class FxRate(Base):
    __tablename__ = "fx_rates"

    rate_date: Mapped[date] = mapped_column(Date, primary_key=True)
    from_currency: Mapped[str] = mapped_column(String(3), primary_key=True)
    to_currency: Mapped[str] = mapped_column(String(3), primary_key=True)
    source: Mapped[str] = mapped_column(Text, primary_key=True)
    rate: Mapped[Decimal] = mapped_column(Numeric(18, 8), nullable=False)
    fetched_at: Mapped[datetime] = mapped_column(server_default=func.now(), nullable=False)


# ---------------------------------------------------------------------------
# Baselines
# ---------------------------------------------------------------------------


class Baseline(Base):
    """30-day rolling median baseline snapshot for one watchlist grain."""

    __tablename__ = "baselines"
    __table_args__ = (
        CheckConstraint("baseline_health in ('GOOD', 'THIN', 'MISSING', 'OUTLIER_RISK')", name="ck_baselines_baseline_health"),
        UniqueConstraint("watch_id", "baseline_date", name="uq_baselines_watch_date"),
        # Grain FK — ensures denormalised fields match the watchlist row for watch_id.
        ForeignKeyConstraint(
            ["watch_id", "route_id", "airline_code", "cabin", "booking_window_days"],
            ["watchlist.watch_id", "watchlist.route_id", "watchlist.airline_code", "watchlist.cabin", "watchlist.booking_window_days"],
            name="fk_baselines_watchlist_grain",
        ),
        # Composite unique so detected_anomalies can cross-check (id, watch_id).
        UniqueConstraint("id", "watch_id", name="uq_baselines_id_watch"),
        Index("ix_baselines_watch_baseline_date", "watch_id", "baseline_date"),
        Index("ix_baselines_baseline_health", "baseline_health"),
    )

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True)
    watch_id: Mapped[int] = mapped_column(BigInteger, ForeignKey("watchlist.watch_id"), nullable=False)
    route_id: Mapped[str] = mapped_column(Text, ForeignKey("routes.route_id"), nullable=False)
    origin: Mapped[str] = mapped_column(String(3), nullable=False)
    destination: Mapped[str] = mapped_column(String(3), nullable=False)
    airline_code: Mapped[str] = mapped_column(String(3), ForeignKey("airlines.airline_code"), nullable=False)
    cabin: Mapped[str] = mapped_column(Text, nullable=False)
    booking_window_days: Mapped[int] = mapped_column(Integer, nullable=False)
    native_currency: Mapped[str] = mapped_column(String(3), nullable=False)
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
    created_at: Mapped[datetime] = mapped_column(server_default=func.now(), nullable=False)

    watchlist_row: Mapped[Watchlist] = relationship(
        back_populates="baselines",
        foreign_keys=[watch_id],
        primaryjoin="Baseline.watch_id == Watchlist.watch_id",
    )


# ---------------------------------------------------------------------------
# Detected anomalies
# ---------------------------------------------------------------------------


class DetectedAnomaly(Base):
    __tablename__ = "detected_anomalies"
    __table_args__ = (
        CheckConstraint("tier in ('DEAL', 'FLASH_DEAL', 'PHANTOM_FARE')", name="ck_detected_anomalies_tier"),
        CheckConstraint("confidence_score between 0 and 1", name="ck_detected_anomalies_confidence_score"),
        CheckConstraint("threshold_set in ('SOW', 'LCC_EXPERIMENTAL')", name="ck_detected_anomalies_threshold_set"),
        CheckConstraint("status in ('DETECTED', 'VERIFIED', 'REJECTED', 'EXPORTED', 'ESCALATED')", name="ck_detected_anomalies_status"),
        UniqueConstraint(
            "price_observation_id",
            "baseline_id",
            "threshold_set",
            name="uq_detected_anomalies_obs_baseline_threshold",
        ),
        # Grain FKs — observation and baseline must belong to the same watch_id.
        ForeignKeyConstraint(
            ["price_observation_id", "watch_id"],
            ["price_observations.id", "price_observations.watch_id"],
            name="fk_detected_anomalies_observation_grain",
        ),
        ForeignKeyConstraint(
            ["baseline_id", "watch_id"],
            ["baselines.id", "baselines.watch_id"],
            name="fk_detected_anomalies_baseline_grain",
        ),
        Index("ix_detected_anomalies_status_detected", "status", "detected_at"),
        Index("ix_detected_anomalies_tier_detected", "tier", "detected_at"),
        Index("ix_detected_anomalies_watch_detected", "watch_id", "detected_at"),
    )

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True)
    price_observation_id: Mapped[int] = mapped_column(BigInteger, ForeignKey("price_observations.id"), nullable=False)
    baseline_id: Mapped[int] = mapped_column(BigInteger, ForeignKey("baselines.id"), nullable=False)
    watch_id: Mapped[int] = mapped_column(BigInteger, ForeignKey("watchlist.watch_id"), nullable=False)
    tier: Mapped[str] = mapped_column(Text, nullable=False)
    current_price: Mapped[Decimal] = mapped_column(Numeric(12, 2), nullable=False)
    baseline_price: Mapped[Decimal] = mapped_column(Numeric(12, 2), nullable=False)
    currency: Mapped[str] = mapped_column(String(3), nullable=False)
    absolute_saving: Mapped[Decimal] = mapped_column(Numeric(12, 2), nullable=False)
    percent_saving: Mapped[Decimal] = mapped_column(Numeric(6, 2), nullable=False)
    confidence_score: Mapped[Decimal] = mapped_column(Numeric(4, 3), nullable=False)
    detection_reason: Mapped[str | None] = mapped_column(Text)
    threshold_set: Mapped[str] = mapped_column(Text, nullable=False)
    status: Mapped[str] = mapped_column(Text, nullable=False, default="DETECTED")
    detected_at: Mapped[datetime] = mapped_column(server_default=func.now(), nullable=False)


# ---------------------------------------------------------------------------
# QA checks
# ---------------------------------------------------------------------------


class QaCheck(Base):
    __tablename__ = "qa_checks"
    __table_args__ = (
        CheckConstraint("verification_source in ('AMADEUS_PRICE', 'DUFFEL', 'MANUAL')", name="ck_qa_checks_verification_source"),
        CheckConstraint("result in ('CONFIRMED', 'REJECTED', 'ESCALATED')", name="ck_qa_checks_result"),
    )

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True)
    anomaly_id: Mapped[int] = mapped_column(BigInteger, ForeignKey("detected_anomalies.id"), nullable=False)
    checked_at: Mapped[datetime] = mapped_column(server_default=func.now(), nullable=False)
    verification_source: Mapped[str] = mapped_column(Text, nullable=False)
    verified_price: Mapped[Decimal | None] = mapped_column(Numeric(12, 2))
    verified_currency: Mapped[str | None] = mapped_column(String(3))
    result: Mapped[str] = mapped_column(Text, nullable=False)
    notes: Mapped[str | None] = mapped_column(Text)
    external_source_verified: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False, server_default="false")
    restrictions: Mapped[str | None] = mapped_column(Text)
    checked_by: Mapped[str | None] = mapped_column(Text)


# ---------------------------------------------------------------------------
# Alerts
# ---------------------------------------------------------------------------


class Alert(Base):
    __tablename__ = "alerts"
    __table_args__ = (
        UniqueConstraint("anomaly_id", name="uq_alerts_anomaly_id"),
        CheckConstraint("visibility in ('FREE', 'MEMBER')", name="ck_alerts_visibility"),
        CheckConstraint("status in ('READY', 'EXPORTED', 'EXPIRED')", name="ck_alerts_status"),
        Index("ix_alerts_status", "status"),
        Index("ix_alerts_visibility_status", "visibility", "status"),
    )

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True)
    anomaly_id: Mapped[int] = mapped_column(BigInteger, ForeignKey("detected_anomalies.id"), nullable=False)
    tier: Mapped[str] = mapped_column(Text, nullable=False)
    origin: Mapped[str] = mapped_column(String(3), nullable=False)
    destination: Mapped[str] = mapped_column(String(3), nullable=False)
    airline_code: Mapped[str] = mapped_column(String(3), nullable=False)
    cabin: Mapped[str] = mapped_column(Text, nullable=False)
    fare_native: Mapped[Decimal] = mapped_column(Numeric(12, 2), nullable=False)
    native_currency: Mapped[str] = mapped_column(String(3), nullable=False)
    fare_display: Mapped[Decimal] = mapped_column(Numeric(12, 2), nullable=False)
    display_currency: Mapped[str] = mapped_column(String(3), nullable=False)
    baseline_price: Mapped[Decimal] = mapped_column(Numeric(12, 2), nullable=False)
    absolute_saving: Mapped[Decimal] = mapped_column(Numeric(12, 2), nullable=False)
    percent_saving: Mapped[Decimal] = mapped_column(Numeric(6, 2), nullable=False)
    booking_link: Mapped[str | None] = mapped_column(Text)
    valid_window: Mapped[str | None] = mapped_column(Text)
    urgency_flag: Mapped[str | None] = mapped_column(Text)
    verification_notes: Mapped[str | None] = mapped_column(Text)
    visibility: Mapped[str] = mapped_column(Text, nullable=False, default="FREE")
    status: Mapped[str] = mapped_column(Text, nullable=False, default="READY")
    exported_at: Mapped[datetime | None] = mapped_column()
    created_at: Mapped[datetime] = mapped_column(server_default=func.now(), nullable=False)


# ---------------------------------------------------------------------------
# Operational tables
# ---------------------------------------------------------------------------


class ApiRequestLog(Base):
    __tablename__ = "api_request_logs"
    __table_args__ = (
        Index("ix_api_request_logs_provider_requested", "provider", "requested_at"),
        Index("ix_api_request_logs_success_requested", "success", "requested_at"),
    )

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True)
    provider: Mapped[str] = mapped_column(Text, nullable=False)
    endpoint: Mapped[str] = mapped_column(Text, nullable=False)
    method: Mapped[str] = mapped_column(Text, nullable=False)
    status_code: Mapped[int | None] = mapped_column(Integer)
    duration_ms: Mapped[int | None] = mapped_column(Integer)
    success: Mapped[bool] = mapped_column(Boolean, nullable=False)
    error_message: Mapped[str | None] = mapped_column(Text)
    request_id: Mapped[str | None] = mapped_column(Text)
    estimated_cost_usd: Mapped[Decimal | None] = mapped_column(Numeric(8, 4))
    requested_at: Mapped[datetime] = mapped_column(server_default=func.now(), nullable=False)


class SchedulerRun(Base):
    __tablename__ = "scheduler_runs"
    __table_args__ = (
        CheckConstraint("status in ('RUNNING', 'SUCCESS', 'PARTIAL', 'FAILED')", name="ck_scheduler_runs_status"),
        Index("ix_scheduler_runs_run_kind_started", "run_kind", "started_at"),
    )

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True)
    run_kind: Mapped[str] = mapped_column(Text, nullable=False)
    started_at: Mapped[datetime] = mapped_column(nullable=False)
    finished_at: Mapped[datetime | None] = mapped_column()
    watch_rows_attempted: Mapped[int | None] = mapped_column(Integer)
    observations_inserted: Mapped[int | None] = mapped_column(Integer)
    requests_failed: Mapped[int | None] = mapped_column(Integer)
    status: Mapped[str] = mapped_column(Text, nullable=False)
    notes: Mapped[str | None] = mapped_column(Text)
