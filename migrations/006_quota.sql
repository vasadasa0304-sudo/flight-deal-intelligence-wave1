-- 002_quota.sql
-- Provider-level API budget controls for polling, verification, and FX refresh.

CREATE TABLE IF NOT EXISTS provider_budgets (
    provider TEXT PRIMARY KEY,
    daily_call_soft_limit INTEGER NOT NULL,
    daily_call_hard_limit INTEGER NOT NULL,
    cost_soft_limit_usd NUMERIC(10, 2),
    cost_hard_limit_usd NUMERIC(10, 2),
    updated_at TIMESTAMPTZ NOT NULL DEFAULT now(),
    CONSTRAINT ck_provider_budgets_daily_call_limits CHECK (
        daily_call_soft_limit >= 0
        AND daily_call_hard_limit > 0
        AND daily_call_soft_limit <= daily_call_hard_limit
    ),
    CONSTRAINT ck_provider_budgets_cost_limits CHECK (
        (
            cost_soft_limit_usd IS NULL
            OR cost_hard_limit_usd IS NULL
            OR cost_soft_limit_usd <= cost_hard_limit_usd
        )
        AND COALESCE(cost_soft_limit_usd, 0) >= 0
        AND COALESCE(cost_hard_limit_usd, 0) >= 0
    )
);
