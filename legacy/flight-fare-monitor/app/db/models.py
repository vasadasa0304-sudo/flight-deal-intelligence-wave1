from datetime import datetime
from sqlalchemy import String, Numeric, DateTime, Integer, BigInteger, Boolean, Date, Text, ForeignKey
from sqlalchemy.orm import Mapped, mapped_column, relationship
from app.db.base import Base


class Route(Base):
    __tablename__ = "routes"

    route_id:         Mapped[int]  = mapped_column(Integer, primary_key=True, autoincrement=True)
    origin_iata:      Mapped[str]  = mapped_column(String(3), nullable=False)
    destination_iata: Mapped[str]  = mapped_column(String(3), nullable=False)
    is_active:        Mapped[bool] = mapped_column(Boolean, nullable=False, default=True)

    search_configs: Mapped[list["SearchConfig"]] = relationship(back_populates="route")


class SearchConfig(Base):
    __tablename__ = "search_configs"

    search_id:      Mapped[int]  = mapped_column(Integer, primary_key=True, autoincrement=True)
    route_id:       Mapped[int]  = mapped_column(Integer, ForeignKey("routes.route_id"), nullable=False)
    departure_date: Mapped[str]  = mapped_column(Date, nullable=False)
    adults:         Mapped[int]  = mapped_column(Integer, nullable=False)
    cabin:          Mapped[str]  = mapped_column(String(20), nullable=False)
    currency:       Mapped[str]  = mapped_column(String(3), nullable=False)
    non_stop:       Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)

    route:     Mapped["Route"]              = relationship(back_populates="search_configs")
    snapshots: Mapped[list["FareSnapshot"]] = relationship(back_populates="search_config")


class FareSnapshot(Base):
    __tablename__ = "fare_snapshots"

    snapshot_id:             Mapped[int]   = mapped_column(BigInteger, primary_key=True, autoincrement=True)
    search_id:               Mapped[int]   = mapped_column(Integer, ForeignKey("search_configs.search_id"), nullable=False)
    carrier_code:            Mapped[str]   = mapped_column(String(8), nullable=True)
    validating_airline_code: Mapped[str]   = mapped_column(String(8), nullable=True)
    departure_time:          Mapped[datetime] = mapped_column(DateTime, nullable=True)
    arrival_time:            Mapped[datetime] = mapped_column(DateTime, nullable=True)
    stops:                   Mapped[int]   = mapped_column(Integer, nullable=True)
    duration_minutes:        Mapped[int]   = mapped_column(Integer, nullable=True)
    price_total:             Mapped[float] = mapped_column(Numeric(12, 2), nullable=True)
    currency:                Mapped[str]   = mapped_column(String(3), nullable=True)
    collected_at:            Mapped[datetime] = mapped_column(DateTime, nullable=False)

    search_config: Mapped["SearchConfig"] = relationship(back_populates="snapshots")


class PipelineRun(Base):
    __tablename__ = "pipeline_runs"

    run_id:        Mapped[int]  = mapped_column(BigInteger, primary_key=True, autoincrement=True)
    started_at:    Mapped[datetime] = mapped_column(DateTime, nullable=False)
    finished_at:   Mapped[datetime] = mapped_column(DateTime, nullable=True)
    status:        Mapped[str]  = mapped_column(String(20), nullable=False)
    rows_inserted: Mapped[int]  = mapped_column(Integer, default=0)
    error_message: Mapped[str]  = mapped_column(Text, nullable=True)