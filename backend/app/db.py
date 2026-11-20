"""Database schema (SQLAlchemy 2.0). Works on SQLite (default) and PostgreSQL."""
from __future__ import annotations

from contextlib import contextmanager
from datetime import datetime, timezone

from sqlalchemy import (JSON, Boolean, DateTime, Float, ForeignKey, Index, Integer, String, Text,
                        UniqueConstraint, create_engine, event)
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column, sessionmaker

from .config import DATABASE_URL


def utcnow() -> datetime:
    return datetime.now(timezone.utc).replace(tzinfo=None)


_is_sqlite = DATABASE_URL.startswith("sqlite")
engine = create_engine(
    DATABASE_URL,
    connect_args={"check_same_thread": False, "timeout": 30} if _is_sqlite else {},
    pool_pre_ping=True,
)

if _is_sqlite:
    @event.listens_for(engine, "connect")
    def _sqlite_pragmas(dbapi_conn, _):  # WAL lets the API and worker share the file safely
        cur = dbapi_conn.cursor()
        cur.execute("PRAGMA journal_mode=WAL")
        cur.execute("PRAGMA busy_timeout=30000")
        cur.close()

SessionLocal = sessionmaker(bind=engine, expire_on_commit=False)


class Base(DeclarativeBase):
    pass


class Airport(Base):
    __tablename__ = "airports"
    iata: Mapped[str] = mapped_column(String(8), primary_key=True)
    city: Mapped[str] = mapped_column(String(80))
    country: Mapped[str] = mapped_column(String(4))
    lat: Mapped[float] = mapped_column(Float)
    lon: Mapped[float] = mapped_column(Float)
    enabled: Mapped[bool] = mapped_column(Boolean, default=True)
    priority: Mapped[int] = mapped_column(Integer, default=3)
    custom: Mapped[bool] = mapped_column(Boolean, default=False)


class Provider(Base):
    __tablename__ = "providers"
    key: Mapped[str] = mapped_column(String(40), primary_key=True)
    name: Mapped[str] = mapped_column(String(120))
    kind: Mapped[str] = mapped_column(String(20))  # rss | api
    url: Mapped[str] = mapped_column(String(400), default="")
    homepage: Mapped[str] = mapped_column(String(400), default="")
    market: Mapped[str] = mapped_column(String(40), default="")
    enabled: Mapped[bool] = mapped_column(Boolean, default=True)
    priority: Mapped[bool] = mapped_column(Boolean, default=False)
    interval_minutes: Mapped[int] = mapped_column(Integer, default=120)
    requires_credentials: Mapped[str] = mapped_column(String(200), default="")
    status: Mapped[str] = mapped_column(String(20), default="pending")  # ok | failing | disabled | needs_credentials | pending
    last_run_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)
    last_success_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)
    next_run_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)
    last_error: Mapped[str] = mapped_column(Text, default="")
    consecutive_failures: Mapped[int] = mapped_column(Integer, default=0)
    offers_collected: Mapped[int] = mapped_column(Integer, default=0)
    api_calls_month: Mapped[int] = mapped_column(Integer, default=0)
    cost_per_call_eur: Mapped[float] = mapped_column(Float, default=0.0)
    notes: Mapped[str] = mapped_column(Text, default="")


class Offer(Base):
    __tablename__ = "offers"
    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    fingerprint: Mapped[str] = mapped_column(String(64), unique=True)
    dedupe_key: Mapped[str] = mapped_column(String(160), index=True)
    duplicate_of: Mapped[int | None] = mapped_column(Integer, nullable=True)
    provider_key: Mapped[str] = mapped_column(String(40), ForeignKey("providers.key"), index=True)
    source_url: Mapped[str] = mapped_column(String(800))
    title: Mapped[str] = mapped_column(String(400))
    summary: Mapped[str] = mapped_column(Text, default="")
    category: Mapped[str] = mapped_column(String(20), index=True)  # error_fare | flight | package | luxury
    subtype: Mapped[str] = mapped_column(String(20), default="flight")  # flight | package | hotel | cruise
    origin_code: Mapped[str] = mapped_column(String(8), default="EU*", index=True)
    origin_label: Mapped[str] = mapped_column(String(120), default="")
    origin_codes: Mapped[list] = mapped_column(JSON, default=list)
    dest_key: Mapped[str] = mapped_column(String(60), default="", index=True)
    dest_label: Mapped[str] = mapped_column(String(120), default="")
    dest_country: Mapped[str] = mapped_column(String(80), default="")
    dest_region: Mapped[str] = mapped_column(String(40), default="")
    lat: Mapped[float | None] = mapped_column(Float, nullable=True)
    lon: Mapped[float | None] = mapped_column(Float, nullable=True)
    price_eur: Mapped[float] = mapped_column(Float)
    price_original: Mapped[float] = mapped_column(Float)
    currency: Mapped[str] = mapped_column(String(4), default="EUR")
    price_basis: Mapped[str] = mapped_column(String(20), default="per_person")  # per_person | per_night | total
    trip_type: Mapped[str] = mapped_column(String(12), default="return")  # return | one_way
    cabin: Mapped[str] = mapped_column(String(16), default="economy")
    nights: Mapped[int | None] = mapped_column(Integer, nullable=True)
    board: Mapped[str] = mapped_column(String(30), default="")
    stars: Mapped[int | None] = mapped_column(Integer, nullable=True)
    baggage: Mapped[str] = mapped_column(String(20), default="unknown")  # included | excluded | unknown
    depart_date: Mapped[str] = mapped_column(String(10), default="")
    return_date: Mapped[str] = mapped_column(String(10), default="")
    travel_window: Mapped[str] = mapped_column(String(120), default="")
    image_url: Mapped[str] = mapped_column(String(800), default="")
    published_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)
    first_seen_at: Mapped[datetime] = mapped_column(DateTime, default=utcnow)
    last_seen_at: Mapped[datetime] = mapped_column(DateTime, default=utcnow)
    last_verified_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)
    link_status: Mapped[str] = mapped_column(String(20), default="unchecked")  # ok | gone | unchecked | blocked
    status: Mapped[str] = mapped_column(String(12), default="active", index=True)  # active | expired
    reference_price: Mapped[float] = mapped_column(Float, default=0)
    savings_eur: Mapped[float] = mapped_column(Float, default=0)
    discount_pct: Mapped[float] = mapped_column(Float, default=0)
    deal_score: Mapped[int] = mapped_column(Integer, default=0, index=True)
    score_breakdown: Mapped[dict] = mapped_column(JSON, default=dict)
    error_fare_flag: Mapped[str] = mapped_column(String(30), default="none")  # none | suspected_source | suspected_statistical
    confidence: Mapped[float] = mapped_column(Float, default=0.5)
    previous_price_eur: Mapped[float | None] = mapped_column(Float, nullable=True)
    price_changed_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)
    is_demo: Mapped[bool] = mapped_column(Boolean, default=False)
    dest_iata: Mapped[str] = mapped_column(String(4), default="")
    # live re-check against airline inventory (Duffel): confirmed | higher | unavailable | ""
    live_status: Mapped[str] = mapped_column(String(20), default="")
    live_price_eur: Mapped[float | None] = mapped_column(Float, nullable=True)
    live_detail: Mapped[str] = mapped_column(String(200), default="")
    live_checked_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)
    # exact times from fare APIs (ISO with UTC offset) – used to build same-day connections
    depart_at: Mapped[str] = mapped_column(String(30), default="")        # main flight leaves the departure airport
    back_arrive_at: Mapped[str] = mapped_column(String(30), default="")   # return flight lands back there
    # booking-search links found in the deal post (None = article not read yet, [] = none found)
    booking_links: Mapped[list | None] = mapped_column(JSON, nullable=True)


class PriceHistory(Base):
    __tablename__ = "price_history"
    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    route_key: Mapped[str] = mapped_column(String(160), index=True)
    offer_id: Mapped[int | None] = mapped_column(Integer, ForeignKey("offers.id"), nullable=True)
    provider_key: Mapped[str] = mapped_column(String(40))
    origin_code: Mapped[str] = mapped_column(String(8), default="")
    dest_key: Mapped[str] = mapped_column(String(60), default="", index=True)
    category: Mapped[str] = mapped_column(String(20), default="")
    price_eur: Mapped[float] = mapped_column(Float)
    observed_at: Mapped[datetime] = mapped_column(DateTime, default=utcnow, index=True)
    travel_month: Mapped[str] = mapped_column(String(7), default="")  # YYYY-MM when known


class ScanLog(Base):
    __tablename__ = "scan_logs"
    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    provider_key: Mapped[str] = mapped_column(String(40), index=True)
    started_at: Mapped[datetime] = mapped_column(DateTime, default=utcnow, index=True)
    finished_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)
    ok: Mapped[bool] = mapped_column(Boolean, default=False)
    fetched: Mapped[int] = mapped_column(Integer, default=0)
    parsed: Mapped[int] = mapped_column(Integer, default=0)
    new: Mapped[int] = mapped_column(Integer, default=0)
    updated: Mapped[int] = mapped_column(Integer, default=0)
    error: Mapped[str] = mapped_column(Text, default="")
    duration_ms: Mapped[int] = mapped_column(Integer, default=0)
    api_calls: Mapped[int] = mapped_column(Integer, default=0)


class AlertRule(Base):
    __tablename__ = "alert_rules"
    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    name: Mapped[str] = mapped_column(String(120))
    origins: Mapped[list] = mapped_column(JSON, default=list)       # IATA codes; empty = any
    destinations: Mapped[list] = mapped_column(JSON, default=list)  # dest keys / countries / regions; empty = any
    categories: Mapped[list] = mapped_column(JSON, default=list)    # empty = any
    cabins: Mapped[list] = mapped_column(JSON, default=list)
    max_price: Mapped[float | None] = mapped_column(Float, nullable=True)
    min_discount_pct: Mapped[float | None] = mapped_column(Float, nullable=True)
    min_score: Mapped[int] = mapped_column(Integer, default=70)
    min_nights: Mapped[int | None] = mapped_column(Integer, nullable=True)
    max_nights: Mapped[int | None] = mapped_column(Integer, nullable=True)
    channels: Mapped[list] = mapped_column(JSON, default=lambda: ["inapp"])
    mode: Mapped[str] = mapped_column(String(10), default="auto")  # instant | digest | auto
    enabled: Mapped[bool] = mapped_column(Boolean, default=True)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=utcnow)


class WatchItem(Base):
    __tablename__ = "watchlist"
    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    kind: Mapped[str] = mapped_column(String(20))  # destination | route | holiday_type
    label: Mapped[str] = mapped_column(String(160))
    value: Mapped[dict] = mapped_column(JSON, default=dict)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=utcnow)


class Notification(Base):
    __tablename__ = "notifications"
    __table_args__ = (UniqueConstraint("rule_id", "dedupe_key", "channel", name="uq_notif"),)
    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    rule_id: Mapped[int | None] = mapped_column(Integer, nullable=True)
    offer_id: Mapped[int | None] = mapped_column(Integer, nullable=True)
    dedupe_key: Mapped[str] = mapped_column(String(200))
    channel: Mapped[str] = mapped_column(String(20))
    kind: Mapped[str] = mapped_column(String(10), default="instant")  # instant | digest | test
    status: Mapped[str] = mapped_column(String(12), default="queued")  # queued | sent | failed | skipped
    title: Mapped[str] = mapped_column(String(300), default="")
    body: Mapped[str] = mapped_column(Text, default="")
    error: Mapped[str] = mapped_column(Text, default="")
    created_at: Mapped[datetime] = mapped_column(DateTime, default=utcnow, index=True)
    sent_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)
    read: Mapped[bool] = mapped_column(Boolean, default=False)


class PositioningFare(Base):
    """Cheapest known return fare between a home hub and another departure airport."""
    __tablename__ = "positioning_fares"
    key: Mapped[str] = mapped_column(String(40), primary_key=True)  # "VNO-ARN" or dated "VNO-ARN-2027-02-13-2027-02-28"
    hub: Mapped[str] = mapped_column(String(4))
    gateway: Mapped[str] = mapped_column(String(4))
    price_eur: Mapped[float | None] = mapped_column(Float, nullable=True)
    airline: Mapped[str] = mapped_column(String(20), default="")
    depart_date: Mapped[str] = mapped_column(String(10), default="")
    return_date: Mapped[str] = mapped_column(String(10), default="")
    fetched_at: Mapped[datetime] = mapped_column(DateTime, default=utcnow)
    hotel_nights: Mapped[int] = mapped_column(Integer, default=1)  # 0 = same-day connections both ways
    detail: Mapped[str] = mapped_column(String(240), default="")


class GeoCache(Base):
    __tablename__ = "geocache"
    name: Mapped[str] = mapped_column(String(160), primary_key=True)
    lat: Mapped[float | None] = mapped_column(Float, nullable=True)
    lon: Mapped[float | None] = mapped_column(Float, nullable=True)
    image_url: Mapped[str] = mapped_column(String(800), default="")
    fetched_at: Mapped[datetime] = mapped_column(DateTime, default=utcnow)


class FxRate(Base):
    __tablename__ = "fx_rates"
    currency: Mapped[str] = mapped_column(String(4), primary_key=True)
    per_eur: Mapped[float] = mapped_column(Float)  # units of currency per 1 EUR
    fetched_at: Mapped[datetime] = mapped_column(DateTime, default=utcnow)


class Setting(Base):
    __tablename__ = "settings"
    key: Mapped[str] = mapped_column(String(60), primary_key=True)
    value: Mapped[dict] = mapped_column(JSON, default=dict)


Index("ix_offers_active_score", Offer.status, Offer.deal_score)


@contextmanager
def session_scope():
    s = SessionLocal()
    try:
        yield s
        s.commit()
    except Exception:
        s.rollback()
        raise
    finally:
        s.close()


def init_db() -> None:
    Base.metadata.create_all(engine)
    # add columns introduced after the first release to existing databases
    from sqlalchemy import inspect, text
    insp = inspect(engine)
    with engine.begin() as conn:
        for table in Base.metadata.sorted_tables:
            have = {c["name"] for c in insp.get_columns(table.name)}
            for col in table.columns:
                if col.name in have:
                    continue
                default = col.default.arg if col.default is not None and not callable(col.default.arg) else None
                ddl = f"ALTER TABLE {table.name} ADD COLUMN {col.name} {col.type.compile(engine.dialect)}"
                if isinstance(default, bool):
                    ddl += f" DEFAULT {'TRUE' if default else 'FALSE'}" if not _is_sqlite else f" DEFAULT {int(default)}"
                elif isinstance(default, str):
                    ddl += f" DEFAULT '{default}'"
                conn.execute(text(ddl))
