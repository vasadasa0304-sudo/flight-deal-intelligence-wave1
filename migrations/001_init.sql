create table if not exists watchlist_routes (
    id bigserial primary key,
    origin char(3) not null,
    destination char(3) not null,
    marketing_carrier varchar(2) not null,
    cabin varchar(16) not null,
    booking_window_days integer not null,
    is_active boolean not null default true,
    source_document varchar(255) not null,
    created_at timestamptz not null default now(),
    constraint uq_watchlist_route_grain unique (
        origin,
        destination,
        marketing_carrier,
        cabin,
        booking_window_days
    )
);

create table if not exists fare_observations (
    id bigserial primary key,
    watchlist_route_id bigint not null references watchlist_routes(id),
    observed_at timestamptz not null,
    departure_date date not null,
    operating_carrier varchar(2),
    ticketing_carrier varchar(2),
    fare_class varchar(16),
    fare_family varchar(64),
    currency char(3) not null,
    total_amount numeric(12, 2) not null,
    source varchar(64) not null,
    source_hash varchar(64) not null,
    raw_payload_ref varchar(255),
    created_at timestamptz not null default now()
);

create index if not exists ix_fare_observations_route_observed
    on fare_observations (watchlist_route_id, observed_at);

create table if not exists baseline_snapshots (
    id bigserial primary key,
    watchlist_route_id bigint not null references watchlist_routes(id),
    baseline_date date not null,
    currency char(3) not null,
    median_amount numeric(12, 2) not null,
    observation_count integer not null,
    created_at timestamptz not null default now(),
    constraint uq_baseline_route_date unique (watchlist_route_id, baseline_date)
);

create table if not exists anomalies (
    id bigserial primary key,
    fare_observation_id bigint not null references fare_observations(id),
    baseline_snapshot_id bigint not null references baseline_snapshots(id),
    tier varchar(32) not null,
    percent_below_baseline numeric(6, 2) not null,
    absolute_saving numeric(12, 2) not null,
    confidence varchar(32) not null,
    status varchar(32) not null default 'qa_pending',
    created_at timestamptz not null default now()
);

create table if not exists qa_reviews (
    id bigserial primary key,
    anomaly_id bigint not null references anomalies(id),
    outcome varchar(32) not null,
    reviewer varchar(128),
    evidence text,
    reviewed_at timestamptz not null
);

create table if not exists alert_exports (
    id bigserial primary key,
    anomaly_id bigint not null references anomalies(id),
    export_format varchar(32) not null,
    destination varchar(64) not null,
    exported_at timestamptz not null
);

create table if not exists api_usage (
    id bigserial primary key,
    provider varchar(64) not null,
    endpoint varchar(128) not null,
    request_count integer not null,
    usage_date date not null
);
