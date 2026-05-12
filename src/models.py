"""SQLAlchemy models for Wave1 operations."""

from __future__ import annotations

from datetime import date, datetime
from decimal import Decimal

from sqlalchemy import CheckConstraint, Date, DateTime, ForeignKey, Integer, Numeric, String, Text, UniqueConstraint
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column, relationship
from sqlalchemy.sql import func


class Base(DeclarativeBase):
    """Base model class."""


class WatchlistRoute(Base):
    """Wave1 route selected from the locked route file."""

    __tablename__ = "watchlist_routes"
    __table_args__ = (
        CheckConstraint(
            "not is_active or cabin in ('ECONOMY', 'BUSINESS')",
            name="ck_active_wave1_watchlist_mvp_cabins",
        ),
        UniqueConstraint(
            "origin",
            "destination",
            "marketing_carrier",
            "cabin",
            "booking_window_days",
            name="uq_watchlist_route_grain",
        ),
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    origin: Mapped[str] = mapped_column(String(3), nullable=False)
    destination: Mapped[str] = mapped_column(String(3), nullable=False)
    marketing_carrier: Mapped[str] = mapped_column(String(2), nullable=False)
    cabin: Mapped[str] = mapped_column(String(16), nullable=False)
    booking_window_days: Mapped[int] = mapped_column(Integer, nullable=False)
    is_active: Mapped[bool] = mapped_column(default=True, nullable=False)
    source_document: Mapped[str] = mapped_column(String(255), nullable=False)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        server_default=func.now(),
        nullable=False,
    )

    observations: Mapped[list["FareObservation"]] = relationship(back_populates="watchlist_route")


class FareObservation(Base):
    """Append-only fare observation."""

    __tablename__ = "fare_observations"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    watchlist_route_id: Mapped[int] = mapped_column(ForeignKey("watchlist_routes.id"), nullable=False)
    observed_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    departure_date: Mapped[date] = mapped_column(Date, nullable=False)
    operating_carrier: Mapped[str | None] = mapped_column(String(2))
    ticketing_carrier: Mapped[str | None] = mapped_column(String(2))
    fare_class: Mapped[str | None] = mapped_column(String(16))
    fare_family: Mapped[str | None] = mapped_column(String(64))
    currency: Mapped[str] = mapped_column(String(3), nullable=False)
    total_amount: Mapped[Decimal] = mapped_column(Numeric(12, 2), nullable=False)
    source: Mapped[str] = mapped_column(String(64), nullable=False)
    source_hash: Mapped[str] = mapped_column(String(64), nullable=False)
    raw_payload_ref: Mapped[str | None] = mapped_column(String(255))
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        server_default=func.now(),
        nullable=False,
    )

    watchlist_route: Mapped[WatchlistRoute] = relationship(back_populates="observations")


class BaselineSnapshot(Base):
    """Daily rolling median baseline by Wave1 route grain."""

    __tablename__ = "baseline_snapshots"
    __table_args__ = (
        UniqueConstraint("watchlist_route_id", "baseline_date", name="uq_baseline_route_date"),
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    watchlist_route_id: Mapped[int] = mapped_column(ForeignKey("watchlist_routes.id"), nullable=False)
    baseline_date: Mapped[date] = mapped_column(Date, nullable=False)
    currency: Mapped[str] = mapped_column(String(3), nullable=False)
    median_amount: Mapped[Decimal] = mapped_column(Numeric(12, 2), nullable=False)
    observation_count: Mapped[int] = mapped_column(Integer, nullable=False)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        server_default=func.now(),
        nullable=False,
    )


class Anomaly(Base):
    """Detected fare anomaly awaiting QA."""

    __tablename__ = "anomalies"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    fare_observation_id: Mapped[int] = mapped_column(ForeignKey("fare_observations.id"), nullable=False)
    baseline_snapshot_id: Mapped[int] = mapped_column(ForeignKey("baseline_snapshots.id"), nullable=False)
    tier: Mapped[str] = mapped_column(String(32), nullable=False)
    percent_below_baseline: Mapped[Decimal] = mapped_column(Numeric(6, 2), nullable=False)
    absolute_saving: Mapped[Decimal] = mapped_column(Numeric(12, 2), nullable=False)
    confidence: Mapped[str] = mapped_column(String(32), nullable=False)
    status: Mapped[str] = mapped_column(String(32), default="qa_pending", nullable=False)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        server_default=func.now(),
        nullable=False,
    )


class QaReview(Base):
    """Manual QA decision for an anomaly."""

    __tablename__ = "qa_reviews"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    anomaly_id: Mapped[int] = mapped_column(ForeignKey("anomalies.id"), nullable=False)
    outcome: Mapped[str] = mapped_column(String(32), nullable=False)
    reviewer: Mapped[str | None] = mapped_column(String(128))
    evidence: Mapped[str | None] = mapped_column(Text)
    reviewed_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)


class AlertExport(Base):
    """QA-approved alert export record."""

    __tablename__ = "alert_exports"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    anomaly_id: Mapped[int] = mapped_column(ForeignKey("anomalies.id"), nullable=False)
    export_format: Mapped[str] = mapped_column(String(32), nullable=False)
    destination: Mapped[str] = mapped_column(String(64), nullable=False)
    exported_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)


class ApiUsage(Base):
    """Provider usage counters for quota visibility."""

    __tablename__ = "api_usage"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    provider: Mapped[str] = mapped_column(String(64), nullable=False)
    endpoint: Mapped[str] = mapped_column(String(128), nullable=False)
    request_count: Mapped[int] = mapped_column(Integer, nullable=False)
    usage_date: Mapped[date] = mapped_column(Date, nullable=False)
