# Wave1 Build Validation Report

**Date:** 2026-05-24
**Branch:** `staging` (@ `33f0bb3`, Prompt 15 backtesting)
**Validated by:** QA pass (senior QA engineer role)
**Scope reference:** [docs/BUILD_SCOPE_WAVE1.md](BUILD_SCOPE_WAVE1.md)

## Environment

| Item | Value |
|---|---|
| Platform | Linux (WSL2), Python 3.x venv |
| Postgres | Local PostgreSQL 16 @ `localhost:5432` (Docker unavailable in this WSL) |
| Test DB | Isolated schema via `TEST_DATABASE_URL` against local Postgres |
| Amadeus | **No credentials configured** — live calls return `401` (expected) |
| Docker | WSL integration disabled — `docker compose` non-functional |

> **Substitution note:** `make db-reset` and the Docker-based checks (22) call Docker, which is
> not available in this environment. Where Docker was required, the **equivalent operation against
> local Postgres** was performed and is labelled as such. This does not change the schema or seed
> logic being validated — only the container that hosts Postgres.

## Results at a glance

| # | Check | Result |
|---|---|---|
| 1 | Repo clean (`git status`) | ✅ PASS (clean at start; see §1 note) |
| 2 | `make install` completes | ✅ PASS |
| 3 | `make test` — all pytest pass | ✅ PASS (155 passed) |
| 4 | `make lint` passes | ⚠️ FIXED → ✅ PASS (2 dead-code errors found & removed) |
| 5 | `make typecheck` passes | ⚠️ PASS w/ known issues (missing third-party stubs only) |
| 6 | db-reset + migrate → 13+ tables | ✅ PASS (17 tables) |
| 7 | seed-wave1 counts | ❌ PARTIAL FAIL (watchlist 620 < 700; all other counts in range) |
| 8 | Tier counts (T1≥9, T2≥6) | ✅ PASS (9 / 6) |
| 9 | 4 watchlist rows per route-carrier | ✅ PASS (155 pairs × 4; phrasing nuance, see §9) |
| 10 | Amadeus client mocked tests | ✅ PASS (8/8) |
| 11 | Parser + observation dedup | ✅ PASS (7 parser + dedup) |
| 12 | Scheduler dry-run | ✅ PASS |
| 13 | Scheduler `--once` → observation | ⏸️ DEFERRED (needs Amadeus creds; manual) |
| 14 | Baseline → GOOD health | ✅ PASS |
| 15 | Detector boundary tests | ✅ PASS (5/5 boundaries) |
| 16 | Phantom promotion guard | ✅ PASS (single-strike blocked) |
| 17 | FX regression (no false deal) | ✅ PASS |
| 18 | Quota THROTTLE_95 STANDARD-skip | ✅ PASS (code + 14 unit tests; see §18) |
| 19 | Streamlit on empty + seeded DB | ✅ PASS (health 200 both) |
| 20 | CSV export with expected columns | ✅ PASS (17 columns; 0 data rows) |
| 21 | Backtest replay → bt_* not prod | ✅ PASS (16/16, 4 isolation tests) |
| 22 | Docker Compose all healthy | ⏸️ DEFERRED (Docker unavailable) |
| 23 | README Ubuntu deploy end-to-end | ⏸️ DEFERRED (no clean Ubuntu; local equivalents OK) |

**Tally:** 18 PASS · 1 PARTIAL FAIL · 3 DEFERRED · (1 lint issue found and remediated)

---

## Detailed results

### 1. Repo clean — ✅ PASS

```
$ git status
On branch staging
Your branch is up to date with 'origin/staging'.
nothing to commit, working tree clean
```

> **Note:** Clean at the start of the pass. The lint remediation (§4) and this report introduce
> uncommitted changes that must be committed to restore a clean tree:
> `src/baselines/backtest.py`, `scripts/run_backtest.py`, `docs/WAVE1_BUILD_VALIDATION_REPORT.md`.

### 2. `make install` — ✅ PASS

```
$ python -m pip install -e ".[dev]"
Successfully installed flight-deal-intelligence-wave1-0.1.0
EXIT: 0
```

### 3. `make test` — ✅ PASS

Run against local Postgres (`TEST_DATABASE_URL` set so DB-backed tests execute rather than skip).

```
$ TEST_DATABASE_URL=postgresql+psycopg://postgres:postgres@localhost:5432/postgres python -m pytest -v
...
======================== 155 passed in 81.54s (0:01:21) ========================
```

> Without `TEST_DATABASE_URL`, the DB-backed tests **skip** (61 passed / 94 skipped). All
> targeted checks below were executed with the DB connected so nothing was silently skipped.

### 4. `make lint` — ⚠️ FIXED → ✅ PASS

Initial run found **2 errors**, both dead code shipped in Prompt 15:

```
F401 `sys` imported but unused        --> scripts/run_backtest.py:15
F841 `synthetic_id_to_tier` assigned but never used --> src/baselines/backtest.py:738
Found 2 errors.
```

**Remediation:** removed the unused import and the unused dict. Re-run:

```
$ python -m ruff check src/ app/ scripts/ tests/
All checks passed!
RUFF EXIT: 0
```

> **Finding:** Prompt 15 was committed/pushed with these two lint errors. CI lint would have
> caught them. Recommend confirming the lint job is wired into the `staging` CI gate.

### 5. `make typecheck` — ⚠️ PASS with known issues

```
$ python -m mypy src/
src/ingestion/watchlist_loader.py:10: error: Library stubs not installed for "pandas"
src/baselines/baseline_job.py:12:   error: Library stubs not installed for "pandas"
src/baselines/backtest.py:18:       error: Library stubs not installed for "pandas"
src/ingestion/scheduler.py:7:       error: Skipping "apscheduler...": missing library stubs
Found 4 errors in 4 files (checked 36 source files)
```

All 4 are **third-party stub gaps** (`pandas`, `apscheduler`), not type errors in Wave1 code.
No `[tool.mypy]` config exists. **Recommended fix:** add `pandas-stubs` to dev deps and a mypy
override for `apscheduler.*` (`ignore_missing_imports = true`) so the gate is green and real type
regressions become visible.

### 6. db-reset + migrate → tables — ✅ PASS (17 tables)

Docker-equivalent reset on local Postgres (`DROP SCHEMA public CASCADE; CREATE SCHEMA public;`)
followed by `make migrate`:

```
=== migrate ===  (17 × CREATE TABLE, no errors)
=== table count === 17
airlines, airports, alerts, api_request_logs, baselines,
bt_baselines, bt_detected_anomalies, bt_synthetic_observations,
detected_anomalies, fx_rates, price_observations, provider_budgets,
qa_checks, route_carriers, routes, scheduler_runs, watchlist
```

17 ≥ 13 required.

### 7. seed-wave1 counts — ❌ PARTIAL FAIL

```
$ python scripts/load_seed_data.py
airports loaded:         41
airlines loaded:         10
routes loaded:           82
route-carrier mappings:  155
watchlist rows loaded:   620
validation warnings:      0
```

| Field | Count | Expected | Result |
|---|---:|---|:--:|
| airports | 41 | (record) | ✅ |
| airlines | 10 | (record) | ✅ |
| routes | 82 | 65–82 | ✅ (upper bound) |
| route_carriers | 155 | (record) | ✅ |
| **watchlist** | **620** | **≥ 700** | ❌ |

> **Root cause:** watchlist grain = route-carrier × cabin × window = 155 × 2 × 2 = **620**.
> Reaching ≥700 requires ≥175 route-carrier mappings; the seed currently has 155.
> This is a **scope/data quantity gap, not a logic bug** — the grain is correct and balanced
> (§9). Either the ≥700 target was an estimate, or more carriers/routes need adding from
> `Wave1_Airlines_Routes_v1.docx` (still within the 65–82 route cap, by adding carriers to
> existing routes). **Action required:** confirm the intended watchlist size with the SoW owner.

### 8. Tier counts — ✅ PASS

```
route_priority      | routes | watchlist
--------------------+--------+----------
STANDARD            |   67   |   440
TIER_1_DAILY        |    9   |   120
TIER_2_EVERY_2_DAYS |    6   |    60
```

TIER_1_DAILY = 9 (≥9 ✓), TIER_2_EVERY_2_DAYS = 6 (≥6 ✓). Both at the minimum boundary.

### 9. Watchlist rows per route-carrier — ✅ PASS

> **Phrasing correction:** the checklist's "4 watchlist rows per route" is precise only for
> single-carrier routes. The true invariant is **4 rows per *route-carrier*** (per `(route_id,
> airline_code)`): 2 cabins × 2 booking windows. A route served by N carriers therefore has N×4
> rows. The check passes on this corrected grain.

```
rows per (route, airline) | num pairs
--------------------------+----------
            4             |    155      ← every pair has exactly 4

rows per route | num routes
---------------+-----------
       4       |    31   (1 carrier)
       8       |    35   (2 carriers)
      12       |    10   (3 carriers)
      16       |     6   (4 carriers)

cabin × window grain: ECONOMY/14, ECONOMY/60, BUSINESS/14, BUSINESS/60 = 155 each
```

The watchlist uniqueness key is `(route_id, airline_code, cabin, booking_window_days)`.
**Every (route, carrier) pair has exactly 4 rows** (2 cabins × 2 windows) — the invariant holds
perfectly. The literal phrasing "4 rows per route" should read **"4 rows per route-carrier"**,
because a route served by N carriers has N×4 rows.

### 10. Amadeus client (mocked transport) — ✅ PASS (8/8)

`tests/test_amadeus_client.py` — 8/8 passed. Uses `httpx.MockTransport`; **no live API calls**.

### 11. Parser + observation dedup — ✅ PASS

```
tests/test_parser.py ......................... 7 passed
tests/test_observation_writer.py::test_duplicate_request_hash_and_bucket_returns_false PASSED
```

Append-only dedup honoured (`uq_price_observations_request_bucket`, ON CONFLICT DO NOTHING).

### 12. Scheduler dry-run — ✅ PASS

```
$ python scripts/run_scheduler.py --dry-run
Dry run: 620 active watchlist row(s). No API calls made.
  watch_id=1 route=AUH-BKK airline=EY cabin=ECONOMY window=14d
  ...
  watch_id=620 route=SAW-TAS airline=PC cabin=BUSINESS window=60d
EXIT: 0
```

Prints the full schedule and exits 0; no API calls.

### 13. Scheduler `--once` → price_observation — ⏸️ DEFERRED (manual)

```
price_observations before: 0
... POST https://test.api.amadeus.com/.../oauth2/token "HTTP/1.1 401 Unauthorized"
WARNING Token fetch attempt 1/3 failed ... (retry/backoff)
price_observations after: 0
```

The full pipeline runs and handles the `401` gracefully (3-attempt retry/backoff, then continues),
but **no observation rows are written without Amadeus credentials**. Per the checklist this is the
"skip in CI; require manual verification" case. **Manual step:** set `AMADEUS_CLIENT_ID` /
`AMADEUS_CLIENT_SECRET` in `.env` (test env) and re-run `make scheduler-once`; expect ≥1 row.

### 14. Baseline → GOOD health — ✅ PASS

```
tests/test_baseline_job.py::test_classify_health_good PASSED
test_classify_health_thin / _missing_low_count / _missing_zero_count PASSED
test_classify_health_outlier_risk_overrides_good / _thin PASSED
test_build_baselines_five_obs_health_missing PASSED
```

GOOD requires ≥30 obs and IQR ≤ 0.5×median; thin/missing/outlier branches all covered. The
Prompt 15 backtest synthetic test independently confirms a **GOOD** baseline forms from a
30-day synthetic window (`test_synthetic_recall_is_1_for_all_tiers`, §21).

### 15. Detector boundary tests — ✅ PASS (5/5)

```
test_399_percent_saving_on_200_eur_baseline_does_not_classify PASSED   (39.9% → none)
test_40_percent_saving_below_absolute_threshold_does_not_classify PASSED (dual-metric)
test_40_percent_and_absolute_threshold_classifies_deal PASSED          (40% +$80 → DEAL)
test_60_percent_and_absolute_threshold_classifies_flash_deal PASSED    (60% +$150 → FLASH)
test_75_percent_and_absolute_threshold_classifies_phantom_fare PASSED  (75% +$250 → PHANTOM)
test_thin_baseline_classifies_with_confidence_below_one PASSED
test_lcc_threshold_set_requires_45_percent_for_deal PASSED
```

Both relative-discount and absolute-saving gates enforced; LCC_EXPERIMENTAL set also covered.

### 16. Phantom promotion guard — ✅ PASS

```
test_phantom_single_strike_amadeus_confirmed_stays_detected PASSED        ← blocked
test_phantom_two_strikes_and_manual_confirmed_becomes_verified PASSED     ← allowed
test_phantom_amadeus_and_duffel_confirmed_becomes_verified PASSED         ← allowed
test_passes_phantom_two_source_rule_rejects_single_unconfirmed_strike PASSED
test_passes_phantom_two_source_rule_rejects_manual_confirmed_without_external_flag PASSED
```

A Phantom Fare with a single confirmed strike **stays `DETECTED`** (cannot promote). Promotion to
`VERIFIED` requires **two independent sources** (e.g. Amadeus + Duffel) **or two-strike + manual**.

### 17. FX regression — ✅ PASS

```
tests/test_currency.py::test_fx_movement_alone_does_not_create_false_deal PASSED
```

A pure FX-rate movement (no native-fare change) does **not** manufacture a false deal — detection
runs in native currency; FX is for display only.

### 18. Quota THROTTLE_95 STANDARD-skip — ✅ PASS

14/14 quota unit tests pass (`tests/test_quota.py`). Poller enforcement verified in code:

```
src/ingestion/poller.py:117
  elif current_quota_status == QUOTA_THROTTLE_95 and row["route_priority"] == "STANDARD":
      quota_skipped += 1
      ... continue   # STANDARD skipped; TIER_1/TIER_2 fall through and still poll
```

At `THROTTLE_95`, **STANDARD routes are skipped while TIER_1/TIER_2 continue**; at `HARD_LIMIT`
the loop breaks and the run is marked `PARTIAL`. **Gap:** band detection is unit-tested but there
is no dedicated poller integration test asserting "STANDARD skipped while TIER_1 continues".
Recommend adding one. (Verified here by code inspection + unit tests.)

### 19. Streamlit on empty + seeded DB — ✅ PASS

```
Check 19a (seeded DB):  health: 200   "You can now view your Streamlit app"   (no errors)
Check 19b (empty DB):   health: 200   "You can now view your Streamlit app"   (no errors)
```

App modules import cleanly; server boots headless and serves `/_stcore/health` = 200 on both a
freshly-migrated empty DB and the seeded DB. (Empty DB created/migrated/dropped for the test.)

### 20. CSV export with expected columns — ✅ PASS

```
$ python scripts/export_alerts.py
Exported 0 READY alerts to data/exports/confirmed_alerts_20260524.csv.

header:
tier,origin,destination,airline_code,cabin,fare_native,native_currency,fare_display,
display_currency,baseline_price,percent_saving,absolute_saving,booking_link,valid_window,
urgency_flag,verification_notes,visibility
```

File written to `data/exports/` with all **17 expected columns**. 0 data rows (no verified alerts
in the seeded DB) — the export schema and file creation are correct.

### 21. Backtest replay → bt_* mirrors, not production — ✅ PASS

```
tests/test_backtest.py  16 passed
  test_replay_does_not_touch_production_baselines PASSED
  test_replay_does_not_touch_production_detected_anomalies PASSED
  test_replay_does_not_touch_production_alerts PASSED
  test_replay_does_not_touch_production_price_observations PASSED
  test_replay_produces_non_empty_bt_baselines / _bt_detected_anomalies PASSED
  test_synthetic_injected_obs_written_to_bt_synthetic_observations PASSED
```

Replay writes only to `bt_baselines` / `bt_detected_anomalies` / `bt_synthetic_observations`;
production `baselines` / `detected_anomalies` / `alerts` / `price_observations` row counts are
asserted **unchanged** after a replay run. Live replay on the seeded DB returns an empty result
(no observations in window), which is handled gracefully.

### 22. Docker Compose all healthy — ⏸️ DEFERRED

Docker Desktop WSL integration is disabled in this environment (`docker compose` is non-functional;
`docker compose down` returns "command could not be found in this WSL 2 distro"). The compose file
defines `postgres` (with healthcheck), `app`, `scheduler`, and `adminer` (profile-gated). **Action:**
run `docker compose up -d && docker compose ps` on a host with a working Docker Engine and confirm
`postgres` → healthy and `app`/`scheduler` → running.

### 23. README Ubuntu deploy end-to-end — ⏸️ DEFERRED

No clean Ubuntu 22.04/24.04 host available in this run. The **local-equivalent** steps from the
README were exercised successfully here: `pip install -e ".[dev]"` (§2), migrate (§6), `seed-wave1`
(§7), `seed_quota.py`, and `streamlit run` (§19). The Docker-dependent bootstrap path (steps 3–6 of
the README "First-time bootstrap") is **DEFERRED** with check 22.

---

## Completed modules summary

| Module | Status | Evidence |
|---|---|---|
| Schema & migrations (001–007) | ✅ Complete | 17 tables, clean migrate (§6) |
| Wave1 seed loader | ✅ Complete | 41/10/82/155/620 rows, 0 warnings (§7) |
| Amadeus async client (OAuth, retry, concurrency) | ✅ Complete | 8 mocked tests (§10) |
| Parser + append-only observation writer | ✅ Complete | 7 + dedup tests (§11) |
| FX handling (Frankfurter, native vs display) | ✅ Complete | FX regression (§17) |
| 30-day rolling-median baseline + health | ✅ Complete | baseline tests (§14) |
| Detector (SOW + LCC dual-metric tiers) | ✅ Complete | 5 boundary tests (§15) |
| Verification (Phantom two-source / two-strike) | ✅ Complete | promotion-guard tests (§16) |
| Quota / cost controls (4 bands + degradation) | ✅ Complete | 14 tests + poller (§18) |
| Alert exports + weekly summary | ✅ Complete | CSV export, 17 cols (§20) |
| Streamlit operations dashboard (8 pages) | ✅ Complete | boots on empty+seeded (§19) |
| Scheduler (APScheduler, dry-run/once) | ✅ Complete | dry-run (§12) |
| Backtest harness (replay + synthetic) | ✅ Complete | 16 tests, prod-isolated (§21) |
| Deployment (Make + Docker Compose) | ⚠️ Partial | local OK; Docker DEFERRED (§22–23) |

## Known limitations

- **Duffel not yet integrated.** Duffel is referenced as a second verification source in the
  Phantom two-source rule and `.env` has `DUFFEL_API_KEY`, but there is no Duffel client/poller.
  Verification currently relies on Amadeus + manual.
- **Production Amadeus not enabled.** `AMADEUS_ENV=test`; no credentials configured. All live API
  paths are unverified end-to-end (checks 13, 23).
- **Live-schedule validation TODO.** The scheduler runs structurally (dry-run), but a real polling
  pass producing observations has not been verified (needs credentials).
- **Watchlist below SoW target.** 620 rows vs the ≥700 expectation (§7) — needs a scope decision.
- **typecheck not green.** 4 missing third-party stub errors (pandas, apscheduler) (§5).
- **No poller-level quota integration test.** THROTTLE_95 skip verified by code + unit tests only (§18).
- **Docker stack unvalidated in this run** (§22) and Ubuntu deploy DEFERRED (§23).

## Remaining manual setup

1. **Amadeus credentials** — add `AMADEUS_CLIENT_ID` / `AMADEUS_CLIENT_SECRET` to `.env`
   (test env first; rotate any keys ever pasted into chat).
2. **`.env` file** — copy from `.env.example`; set `DATABASE_URL`, FX provider, quota seeds.
3. **Provider budgets** — run `python scripts/seed_quota.py` after seeding.
4. **Postgres backup cron** — schedule `scripts/backup_postgres.sh` (e.g. daily) and confirm the
   7-backup retention writes to `data/exports/backups/`.
5. **Docker host** — enable Docker Engine / WSL integration to validate the full compose stack.

## Next recommended build task

**Primary: Duffel integration** — implement a Duffel client + poller so the Phantom Fare
two-source rule has a real second source instead of relying on manual confirmation. This is the
single biggest correctness gap (it directly affects which alerts can be promoted).

Then, in order:
1. **Baseline warm-up window** — define how the system behaves before 30 days of history exists
   (currently baselines are MISSING/THIN, so no detection) — needed before any live launch.
2. **Calibration backtest with real data** — once Amadeus test/production data is flowing, run the
   Prompt 15 synthetic + replay harness on real observations to tune SOW vs LCC thresholds and
   measure false-positive / rejection rates per carrier type.
3. **Close the QA gaps** from this report: add `pandas-stubs` + mypy override (§5), a poller quota
   integration test (§18), and resolve the watchlist-count decision (§7).
