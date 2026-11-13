# Full document accuracy — 11 November 2026

Completed 16/16 document scans using the current PP-OCRv6 Medium detector and recognizer.

- Normalized field accuracy: **168/259 (64.86%)**.
- Strict string accuracy: 114/259 (44.02%).
- Completely correct documents: 2/16.
- Missing fields: 60; incorrect nonempty values: 31.
- Mean scan time: 11.86 seconds; range 6.59–21.96 seconds.

## Document results

| Document | Correct fields | Accuracy | Seconds |
|---|---:|---:|---:|
| Photo 01 | 17/17 | 100.0% | 10.71 |
| Photo 02 | 17/17 | 100.0% | 9.64 |
| Photo 03 | 11/17 | 64.7% | 12.19 |
| Photo 04 | 3/17 | 17.6% | 10.81 |
| Photo 05 | 12/17 | 70.6% | 14.62 |
| Photo 06 | 11/17 | 64.7% | 11.48 |
| Photo 08 | 5/10 | 50.0% | 6.59 |
| Photo 09 | 0/16 | 0.0% | 7.56 |
| Photo 10 | 12/17 | 70.6% | 9.11 |
| Photo 12 | 12/17 | 70.6% | 7.98 |
| Photo 13 | 13/17 | 76.5% | 16.5 |
| Photo 14 | 6/17 | 35.3% | 17.62 |
| Photo 16 | 6/15 | 40.0% | 10.79 |
| Photo 17 | 16/17 | 94.1% | 11.33 |
| Photo 18 | 15/16 | 93.8% | 10.89 |
| Photo 20 | 12/15 | 80.0% | 21.96 |

## Field results

| Field | Correct / scored |
|---|---:|
| Issuing authority | 3/14 |
| Place of birth | 5/13 |
| Date of issue | 7/16 |
| Date of expiry | 8/16 |
| Place of issue | 2/4 |
| Date of birth | 9/16 |
| Nationality | 9/15 |
| MRZ line 1 | 9/15 |
| Issuing country | 10/15 |
| MRZ line 2 | 10/15 |
| Issuing country code | 10/14 |
| Sex | 12/16 |
| Surname / last name | 12/15 |
| Given names | 12/15 |
| Full name | 13/16 |
| Document | 13/16 |
| Passport number | 10/12 |
| Document type code | 13/15 |
| Authority code | 1/1 |

## Scope and limitations

Existing notebook expected values, not independently re-annotated. Normalized scoring uses existing case/spacing, date, country, name, and number equivalence rules. Strict scoring compares exact strings. Two generic Other document ID labels have no unambiguous output mapping and are unscored. Obscured/unavailable fields excluded. Extra unlabelled outputs are not evaluated.

All 16 mapped local images were tested end to end through run_scan. No cloud requests were used. DocRes and Telescope remained disabled; the enabled Tesseract backup was unavailable. Application code and configuration were not changed.
