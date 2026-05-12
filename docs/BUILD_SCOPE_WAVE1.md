# Build Scope: Wave1

## Status

Wave1 is the locked first production scope for Phase 1 of the Flight Deal Intelligence internal operations app.

Do not build for all regions yet. Do not add routes, carriers, products, or user-facing channels outside this Wave1 scope unless a later approved scope document explicitly expands it.

## Source Documents Read

- `docs/Wave1_Airlines_Routes_v1.docx`
- `docs/SoW_FlightDeal_Stefan_v3.docx`
- `docs/MENAT_CA_Fare_Deal_Intelligence_Employer_Plan.pdf`

## Wave1 Geography

Wave1 geography is limited to Middle East + Turkey.

Wave1 hubs:

| Hub | Market |
|---|---|
| IST | Istanbul |
| SAW | Istanbul Sabiha Gokcen |
| DXB | Dubai |
| AUH | Abu Dhabi |
| RUH | Riyadh |
| JED | Jeddah |
| DOH | Doha |
| CAI | Cairo |

## Wave1 Airlines

Wave1 airlines are limited to these 10 carriers:

| IATA | Airline | Type |
|---|---|---|
| TK | Turkish Airlines | Full-service |
| PC | Pegasus | Low-cost |
| EK | Emirates | Full-service |
| FZ | flydubai | Low-cost / hybrid |
| QR | Qatar Airways | Full-service |
| EY | Etihad | Full-service |
| SV | Saudia | Full-service |
| XY | flynas | Low-cost |
| MS | EgyptAir | Full-service |
| G9 | Air Arabia | Low-cost |

## Route Scope

Target active monitoring scope:

- 60-80 active monitored routes.
- Routes must be selected only from `docs/Wave1_Airlines_Routes_v1.docx`.
- No invented routes.
- No routes outside the Wave1 route file.
- Routes may be pruned if source coverage or data quality is unreliable.
- Any route addition must be traceable to the Wave1 route file or marked as out of scope.

## Booking Windows

Wave1 must capture both booking windows for each monitored route:

- 14 days before departure.
- 60 days before departure.

Baseline calculations, QA checks, and alert exports must preserve booking-window segmentation.

## MVP Cabins

MVP cabins are limited to:

- `ECONOMY`
- `BUSINESS`

Other cabins are out of scope for Wave1 unless separately approved.

## Core Logic

Wave1 production logic must follow these operating principles:

- Store fare observations as append-only history.
- Do not overwrite prior fare observations.
- Build the baseline from a 30-day rolling median.
- Segment baseline logic by route, carrier, cabin, and booking window.
- Classify candidate anomalies as `Deal`, `Flash Deal`, or `Phantom Fare`.
- Apply both relative discount and absolute saving checks before classification.
- Send candidate alerts to QA before export.
- Export only QA-verified alerts.

## Fare Classification

Use the SoW classification framework as the starting model:

| Tier | Baseline Drop | Minimum Absolute Saving | Wave1 Handling |
|---|---:|---:|---|
| Deal | >= 40% | >= $80 / EUR 75 | QA required before export |
| Flash Deal | >= 60% | >= $150 / EUR 140 | QA required before export |
| Phantom Fare | >= 75% | >= $250 / EUR 230 | Heightened QA required before export |

Phantom Fare candidates require stricter verification because they may be caused by currency mismatch, airline system error, stale inventory, or other transient conditions.

## QA Verification

Before alert export, QA must verify:

- fare is currently bookable;
- route and cabin are correct;
- price, currency, and saving calculation are correct;
- booking window is correct;
- carrier and source evidence are recorded;
- unusual restrictions are noted;
- Phantom Fare candidates receive heightened scrutiny.

QA outcomes must be recorded as `confirmed`, `rejected`, or `escalated`.

## Explicit Non-Scope

Wave1 does not include:

- public web app;
- mobile app;
- membership platform;
- airline direct scraping;
- OTA scraping;
- affiliate integration;
- social media content creation;
- notification system build;
- all-region expansion;
- route additions outside the Wave1 route file.

## Facts, Assumptions, Unknowns

Facts:

- Wave1 is Middle East + Turkey.
- Wave1 uses hubs `IST`, `SAW`, `DXB`, `AUH`, `RUH`, `JED`, `DOH`, and `CAI`.
- Wave1 uses the 10 airlines listed above.
- The active route target is 60-80 routes selected from the Wave1 route file.
- The MVP booking windows are 14 days and 60 days.
- The MVP cabins are `ECONOMY` and `BUSINESS`.
- Fare observations must be append-only.
- Alert export requires QA verification.

Assumptions:

- Staging branch is the active development branch for Phase 1 build work.
- Any future production deployment will keep Wave1 scope locked until an approved scope expansion exists.

Unknowns:

- Final Day 1 route selection from the Wave1 route file.
- Final data provider account limits and production API quotas.
- Final alert export template.
- Final QA log storage format.
