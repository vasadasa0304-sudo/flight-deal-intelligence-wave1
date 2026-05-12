create table if not exists airports (
    airport_code char(3) primary key,
    city text not null,
    country text not null,
    region text not null,
    timezone text not null,
    is_wave1_hub boolean not null default false,
    is_active boolean not null default true,
    created_at timestamptz not null default now(),
    constraint ck_airports_airport_code_length check (char_length(airport_code) = 3)
);

create table if not exists airlines (
    airline_code varchar(3) primary key,
    airline_name text not null,
    carrier_type text not null,
    primary_hub text,
    is_wave1_airline boolean not null default false,
    is_active boolean not null default true,
    created_at timestamptz not null default now(),
    constraint ck_airlines_carrier_type check (carrier_type in ('FSC', 'LCC', 'HYBRID')),
    constraint ck_airlines_airline_code_length check (char_length(airline_code) between 2 and 3)
);

create table if not exists routes (
    route_id text primary key,
    origin char(3) not null references airports(airport_code),
    destination char(3) not null references airports(airport_code),
    route_type text not null,
    route_priority text not null,
    strategic_tag text not null,
    strategic_relevance text,
    carrier_overlap_notes text,
    source_document_note text not null,
    is_new_launch boolean not null default false,
    is_active boolean not null default true,
    created_at timestamptz not null default now(),
    updated_at timestamptz not null default now(),
    constraint ck_routes_route_type check (route_type in ('INTERNATIONAL', 'DOMESTIC')),
    constraint ck_routes_route_priority check (
        route_priority in ('TIER_1_DAILY', 'TIER_2_EVERY_2_DAYS', 'STANDARD')
    ),
    constraint ck_routes_strategic_tag check (
        strategic_tag in ('STANDARD', 'WAVE_2_PRESEED', 'WAVE_3_PRESEED')
    ),
    constraint ck_routes_origin_destination_distinct check (origin <> destination)
);

create table if not exists route_carriers (
    id bigserial primary key,
    route_id text not null references routes(route_id) on delete cascade,
    airline_code varchar(3) not null references airlines(airline_code),
    role_on_route text not null,
    is_primary_wave1_carrier boolean not null default false,
    notes text,
    constraint ck_route_carriers_role_on_route check (
        role_on_route in ('PRIMARY', 'SECONDARY', 'LCC_PRESSURE', 'LEGACY_COMPETITOR')
    ),
    constraint uq_route_carriers_route_airline unique (route_id, airline_code)
);

create table if not exists watchlist (
    watch_id bigserial primary key,
    route_id text not null references routes(route_id),
    airline_code varchar(3) not null references airlines(airline_code),
    cabin text not null,
    booking_window_days integer not null,
    currency char(3) not null,
    poll_frequency_minutes integer not null,
    route_priority text not null,
    strategic_tag text not null,
    is_active boolean not null default true,
    created_at timestamptz not null default now(),
    updated_at timestamptz not null default now(),
    constraint ck_watchlist_cabin check (
        cabin in ('ECONOMY', 'PREMIUM_ECONOMY', 'BUSINESS', 'FIRST')
    ),
    constraint ck_watchlist_booking_window_days check (booking_window_days in (14, 60)),
    constraint ck_watchlist_poll_frequency_minutes check (poll_frequency_minutes > 0),
    constraint ck_watchlist_active_wave1_mvp_cabins check (
        not is_active or cabin in ('ECONOMY', 'BUSINESS')
    ),
    constraint uq_watchlist_route_airline_cabin_window unique (
        route_id,
        airline_code,
        cabin,
        booking_window_days
    )
);

-- APPEND-ONLY by application convention: never UPDATE or DELETE rows from this table.
create table if not exists price_observations (
    id bigserial primary key,
    watch_id bigint not null references watchlist(watch_id),
    route_id text not null references routes(route_id),
    origin char(3) not null,
    destination char(3) not null,
    airline_code varchar(3) not null references airlines(airline_code),
    cabin text not null,
    booking_window_days integer not null,
    departure_date date not null,
    return_date date,
    native_currency char(3) not null,
    native_price numeric(12, 2) not null,
    taxes_fees numeric(12, 2),
    display_currency char(3) not null,
    display_price numeric(12, 2) not null,
    fx_rate_used numeric(18, 8),
    source text not null,
    deeplink text,
    request_hash text not null,
    polling_bucket_hour timestamptz not null,
    observed_at timestamptz not null,
    raw_response jsonb not null,
    created_at timestamptz not null default now(),
    constraint uq_price_observations_request_bucket unique (request_hash, polling_bucket_hour),
    constraint ck_price_observations_native_price check (native_price >= 0),
    constraint ck_price_observations_display_price check (display_price >= 0)
);

create table if not exists fx_rates (
    rate_date date not null,
    from_currency char(3) not null,
    to_currency char(3) not null,
    rate numeric(18, 8) not null,
    source text not null,
    fetched_at timestamptz not null default now(),
    constraint pk_fx_rates primary key (rate_date, from_currency, to_currency, source)
);

create table if not exists baselines (
    id bigserial primary key,
    watch_id bigint not null references watchlist(watch_id),
    route_id text not null,
    origin char(3) not null,
    destination char(3) not null,
    airline_code varchar(3) not null,
    cabin text not null,
    booking_window_days integer not null,
    native_currency char(3) not null,
    baseline_date date not null,
    window_start_date date not null,
    window_end_date date not null,
    median_price_native numeric(12, 2) not null,
    min_price_native numeric(12, 2) not null,
    max_price_native numeric(12, 2) not null,
    p25_price_native numeric(12, 2) not null,
    p75_price_native numeric(12, 2) not null,
    iqr_price_native numeric(12, 2) not null,
    observation_count integer not null,
    baseline_health text not null,
    created_at timestamptz not null default now(),
    constraint ck_baselines_baseline_health check (
        baseline_health in ('GOOD', 'THIN', 'MISSING', 'OUTLIER_RISK')
    ),
    constraint uq_baselines_watch_date unique (watch_id, baseline_date)
);

create table if not exists detected_anomalies (
    id bigserial primary key,
    price_observation_id bigint not null references price_observations(id),
    baseline_id bigint not null references baselines(id),
    watch_id bigint not null references watchlist(watch_id),
    tier text not null,
    current_price numeric(12, 2) not null,
    baseline_price numeric(12, 2) not null,
    currency char(3) not null,
    absolute_saving numeric(12, 2) not null,
    percent_saving numeric(6, 2) not null,
    confidence_score numeric(4, 3) not null,
    detection_reason text,
    threshold_set text not null,
    status text not null default 'DETECTED',
    detected_at timestamptz not null default now(),
    constraint ck_detected_anomalies_tier check (tier in ('DEAL', 'FLASH_DEAL', 'PHANTOM_FARE')),
    constraint ck_detected_anomalies_confidence_score check (confidence_score between 0 and 1),
    constraint ck_detected_anomalies_threshold_set check (
        threshold_set in ('SOW', 'LCC_EXPERIMENTAL')
    ),
    constraint ck_detected_anomalies_status check (
        status in ('DETECTED', 'VERIFIED', 'REJECTED', 'EXPORTED', 'ESCALATED')
    )
);

create table if not exists qa_checks (
    id bigserial primary key,
    anomaly_id bigint not null references detected_anomalies(id),
    checked_at timestamptz not null default now(),
    verification_source text not null,
    verified_price numeric(12, 2),
    verified_currency char(3),
    result text not null,
    notes text,
    restrictions text,
    checked_by text,
    constraint ck_qa_checks_verification_source check (
        verification_source in ('AMADEUS_PRICE', 'DUFFEL', 'MANUAL')
    ),
    constraint ck_qa_checks_result check (result in ('CONFIRMED', 'REJECTED', 'ESCALATED'))
);

create table if not exists alerts (
    id bigserial primary key,
    anomaly_id bigint not null references detected_anomalies(id),
    tier text not null,
    origin char(3) not null,
    destination char(3) not null,
    airline_code varchar(3) not null,
    cabin text not null,
    fare_native numeric(12, 2) not null,
    native_currency char(3) not null,
    fare_display numeric(12, 2) not null,
    display_currency char(3) not null,
    baseline_price numeric(12, 2) not null,
    absolute_saving numeric(12, 2) not null,
    percent_saving numeric(6, 2) not null,
    booking_link text,
    valid_window text,
    urgency_flag text,
    verification_notes text,
    visibility text not null default 'FREE',
    status text not null default 'READY',
    exported_at timestamptz,
    created_at timestamptz not null default now(),
    constraint ck_alerts_visibility check (visibility in ('FREE', 'MEMBER')),
    constraint ck_alerts_status check (status in ('READY', 'EXPORTED', 'EXPIRED'))
);

create table if not exists api_request_logs (
    id bigserial primary key,
    provider text not null,
    endpoint text not null,
    method text not null,
    status_code integer,
    duration_ms integer,
    success boolean not null,
    error_message text,
    request_id text,
    estimated_cost_usd numeric(8, 4),
    requested_at timestamptz not null default now()
);

create table if not exists scheduler_runs (
    id bigserial primary key,
    run_kind text not null,
    started_at timestamptz not null,
    finished_at timestamptz,
    watch_rows_attempted integer,
    observations_inserted integer,
    requests_failed integer,
    status text not null,
    notes text,
    constraint ck_scheduler_runs_status check (status in ('RUNNING', 'SUCCESS', 'PARTIAL', 'FAILED'))
);

create index if not exists ix_price_observations_watch_observed
    on price_observations (watch_id, observed_at desc);

create index if not exists ix_price_observations_route_observed
    on price_observations (route_id, observed_at desc);

create index if not exists ix_price_observations_airline_cabin_window_observed
    on price_observations (airline_code, cabin, booking_window_days, observed_at desc);

create index if not exists ix_price_observations_polling_bucket_hour
    on price_observations (polling_bucket_hour);

create index if not exists ix_baselines_watch_baseline_date
    on baselines (watch_id, baseline_date desc);

create index if not exists ix_baselines_baseline_health
    on baselines (baseline_health);

create index if not exists ix_detected_anomalies_status_detected
    on detected_anomalies (status, detected_at desc);

create index if not exists ix_detected_anomalies_tier_detected
    on detected_anomalies (tier, detected_at desc);

create index if not exists ix_detected_anomalies_watch_detected
    on detected_anomalies (watch_id, detected_at desc);

create index if not exists ix_alerts_status
    on alerts (status);

create index if not exists ix_alerts_visibility_status
    on alerts (visibility, status);

create index if not exists ix_api_request_logs_provider_requested
    on api_request_logs (provider, requested_at desc);

create index if not exists ix_api_request_logs_success_requested
    on api_request_logs (success, requested_at desc);

create index if not exists ix_scheduler_runs_run_kind_started
    on scheduler_runs (run_kind, started_at desc);
