# Flight Fare Monitor Spec

Status: locked for v1. Data posture is fixed: Amadeus Self-Service is the primary fare source, Duffel is the secondary verifier, scraping is prohibited, and Kiwi is excluded.

## 1. Scope

| Area | In scope |
| --- | --- |
| Origin clusters | GCC: `DXB`, `AUH`, `SHJ`, `DOH`, `RUH`, `JED`, `DMM`, `KWI`, `BAH`, `MCT`; Levant/Iraq: `AMM`, `BEY`, `TLV`, `BGW`, `EBL`; Turkey: `IST`, `SAW`, `ESB`, `ADB`, `AYT`; North Africa: `CAI`, `HBE`, `CMN`, `RAK`, `ALG`, `TUN`, `TIP`; South Caucasus: `TBS`, `EVN`, `GYD`; Central Asia: `ALA`, `NQZ`, `TAS`, `FRU`, `DYU`, `ASB` |
| Carrier Tier 1 | Regional/network carriers and primary NDC/API carriers: Emirates, Qatar Airways, Etihad, Turkish Airlines, Saudia, Oman Air, Gulf Air, Kuwait Airways, Royal Jordanian, MEA, Egyptair, Royal Air Maroc, Air Astana, Uzbekistan Airways, Azerbaijan Airlines |
| Carrier Tier 2 | Regional LCC/hybrid carriers where API fares are available: flydubai, Air Arabia group, Jazeera, flynas, flyadeal, Pegasus, AJet, Nile Air, Air Cairo, SalamAir, Wizz Air Abu Dhabi |
| Carrier Tier 3 | Long-haul/global carriers serving MENAT+CA origin markets through Amadeus or Duffel: Lufthansa Group, IAG, Air France-KLM, ITA, Aegean, LOT, Ethiopian, Kenya Airways, Singapore Airlines, Cathay Pacific, Malaysia Airlines, US3 where available |

Hard exclusions: web scraping, Kiwi/Tequila, unofficial aggregator APIs, hidden-city fares, throwaway-ticketing logic, private/corporate fares, opaque OTA-only fares, charter-only inventory, package fares, ancillaries-only pricing, and any source requiring credential sharing or ToS circumvention.

## 2. Metric Definitions

| Metric | Definition | Formula / rule |
| --- | --- | --- |
| `deal` | A currently sellable fare materially below its comparable baseline for the same market, cabin, trip type, stay length, and season flag. | `discount_pct = 1 - live_total_price / baseline_p50_total_price`; deal if `discount_pct >= cabin_threshold` and `live_total_price <= baseline_p25_total_price`. |
| `phantom` | A fare observed from the primary source that cannot be reproduced or confirmed by the verifier within the verification window. | Phantom if Amadeus result exists and Duffel returns no equivalent offer within `route + date +/- 1 day + cabin + pax + max_price_delta`, or if the offer disappears on immediate Amadeus recheck. |
| `verified` | A candidate deal confirmed by independent source agreement and immediate recheck. | Verified if Amadeus candidate still prices on recheck and Duffel confirms an equivalent offer with `abs(amadeus_price - duffel_price) / min(price) <= 0.03` or `<= 25 USD`, whichever is greater. |

All prices are total payable fare in USD, including carrier-imposed surcharges and mandatory taxes/fees. Baselines use rolling trailing observations by `origin_cluster`, destination, carrier tier, cabin, trip type, stay-length bucket, advance-purchase bucket, and season flag.

## 3. Latency Targets and SLOs

| Stage | Target | SLO |
| --- | ---: | --- |
| Search ingestion from scheduled watchlist run | <= 2 minutes | 99% of scheduled searches start within 2 minutes of due time per calendar day. |
| Candidate scoring after Amadeus response | <= 30 seconds | 99% of Amadeus results are normalized, deduped, and scored within 30 seconds. |
| Duffel verification after candidate detection | <= 3 minutes | 95% of candidate deals receive verifier outcome within 3 minutes. |
| Alert dispatch after verification | <= 60 seconds | 99% of verified deals are sent to configured alert channels within 60 seconds. |
| End-to-end detection-to-alert latency | <= 5 minutes | 95% of verified deals alert within 5 minutes from first primary-source observation. |

Availability SLO: 99.5% of scheduled watchlist checks complete without unhandled failure per rolling 30 days. Freshness SLO: 95% of active watchlist rows are checked at least once within their configured polling interval per rolling 24 hours.

## 4. Watchlist Schema

| Field | Meaning |
| --- | --- |
| `watch_id` | Stable unique identifier for the watchlist row. |
| `origin_cluster` | One scoped cluster from Section 1; expands to configured origin airports. |
| `destination` | IATA airport, city, country, or region target resolved before search. |
| `trip_type` | `one_way`, `round_trip`, or `open_jaw` when supported by source APIs. |
| `date_window` | Departure window plus optional return window, stored as ISO dates or relative offsets. |
| `stay_length_bucket` | `0-3`, `4-7`, `8-14`, `15-30`, or `30+` nights for baseline comparability. |
| `cabin` | `economy`, `premium_economy`, `business`, or `first`. |
| `carrier_tiers` | Allowed carrier tiers from Section 1; default is all in-scope tiers. |
| `max_total_price_usd` | Absolute ceiling for alert eligibility before discount scoring. |
| `poll_interval_minutes` | Scheduled cadence for this row, bounded by source quota and SLO budget. |

## 5. Alert Thresholds Per Cabin

| Cabin | Minimum discount vs baseline p50 | Additional price rule |
| --- | ---: | --- |
| Economy | >= 30% | Must also be <= baseline p25. |
| Premium economy | >= 35% | Must also be <= baseline p25. |
| Business | >= 40% | Must also be <= baseline p20. |
| First | >= 45% | Must also be <= baseline p20 and verified by Duffel before alerting. |

Suppress alerts when the live fare is above `max_total_price_usd`, when baggage/fare-family ambiguity changes the effective fare class, or when source agreement fails the `verified` rule.

## 6. Hijri-Calendar Season Flags

| Flag | Window |
| --- | --- |
| `ramadan` | 1-30 Ramadan. |
| `eid_al_fitr` | 25 Ramadan through 7 Shawwal. |
| `hajj` | 1-13 Dhu al-Hijjah, applied globally and separately tagged for KSA-bound traffic. |
| `eid_al_adha` | 7-15 Dhu al-Hijjah. |
| `muharram_ashura` | 1-12 Muharram. |

Hijri dates are computed per configured calendar source and materialized to Gregorian dates before watchlist expansion. Season flags are non-exclusive; overlapping windows keep all matching flags.

## 7. Out of Scope

Booking, ticketing, payment handling, PNR management, seat maps, ancillary optimization, loyalty earning estimates, visa or entry-rule advice, hotel/package bundling, carbon scoring, fare prediction, user-specific personalization, OTA deep links, web scraping, browser automation against supplier sites, and unsupported carriers or markets outside MENAT+CA origin scope.
