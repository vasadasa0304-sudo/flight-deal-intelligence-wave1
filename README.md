# Flight Deal Intelligence — Wave1

Internal operations app for Wave1 fare monitoring.

## Locked first scope

Wave1 only:
- Middle East + Turkey
- Hubs: IST, SAW, DXB, AUH, RUH, JED, DOH, CAI
- Airlines: TK, PC, EK, FZ, QR, EY, SV, XY, MS, G9
- 60–80 active monitored routes
- 14-day and 60-day booking windows
- Economy and Business cabins first
- Append-only price observations
- 30-day rolling median baselines
- Deal / Flash Deal / Phantom Fare detection
- QA verification before alert export

## Branch strategy

- main: stable approved code
- staging: active development and Codex work

## Notes

Employer documents are stored in `/docs`.
Raw source spreadsheets are stored in `/data/raw`.
Generated exports should not be committed.
