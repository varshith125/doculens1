# Verification record

## MRZ, comparison and startup connectivity refinement — 27 October 2026

This is the latest result and supersedes earlier UI descriptions below. See [the change report and manual acceptance plan](enhancement-2026-10-27.md) for changed files, precise behavior, commands and limitations.

| Executed check | Final result |
| --- | --- |
| `python -m pytest -q`, with real OCR and private sample manifest enabled | **200 passed**, 79.37 seconds; one existing Starlette/httpx deprecation warning |
| `npm.cmd test` | **40 passed** across five test files |
| `npm.cmd run lint` | Passed |
| `npm.cmd run build` (strict TypeScript and Vite production build) | Passed |
| `npm.cmd run format:check` | Passed |
| `python -m ruff check backend scripts` | Passed |
| `python -m ruff format --check backend scripts` | Passed; 40 files formatted |
| Browser/device/manual accessibility checks | **Not performed**; manual plan supplied, no servers started |

The full suite includes ten authorized-image checks: the five originals and five in-memory blur variants. Expected values come from independent reading of the originals; the masked sample checks that its unavailable number stays empty. The suite also includes generated small/blurred/tilted document cases, raw MRZ preservation, invalid/incomplete MRZ, empty pixels, field mapping, API privacy/cancellation, startup recovery and StrictMode cleanup, bounded retry/timeout, exact export, keyboard comparison controls and existing GSAP cleanup/reduced-motion tests.

Three generated tilted cases improved from 5/6 to 6/6 checked fields using the **same OCR observations**, after correcting field geometry. This is a narrow regression improvement, not a general accuracy percentage. A blurred-ID caption-suffix regression also passed after the issue-date association fix. Clear-document comparisons stayed correct.

Initial runs exposed an ambiguous frontend test selector, the blurred-ID association bug and oversized PNG test variants. The final runs above passed after fixing these. Upload size limits were not changed.

Production artifacts: main JS **306.27 kB / 94.46 kB gzip**, separate GSAP chunk **70.55 kB / 27.84 kB gzip**, CSS **32.74 kB / 8.45 kB gzip**. No OCR model/dependency replacement or extra inference passes were introduced.

## Final 17-section enhancement — 27 October 2026

This section describes the current implementation and supersedes earlier results-presentation notes below. The historical sections are retained as a work record.

- **180 backend tests passed** in the final full run (50.46 seconds), with real ONNX OCR and all five authorized private sample cases enabled. These include exact selected-name/number/date comparisons on three U.S. passports and an Emirates ID, plus a masked-number non-extraction check on the blurred Indian sample. This is not a claim that every field on every image was recovered.
- **24 frontend tests passed**, including API-to-screen field mapping, separate name captions, DMY display/copy, optional evidence, unmatched text, upload errors, timeout/cancellation, keyboard controls, reduced-motion behavior and GSAP cleanup/unmount handling.
- Python Ruff lint and format, ESLint, Prettier, strict TypeScript and the Vite production build passed. The full backend suite emits one existing Starlette/httpx TestClient deprecation warning; it does not affect these test results.
- GSAP **3.15.0** is implemented in the page, upload, progress and results views. Its separately loaded chunk is **70.55 kB / 27.84 kB gzip**. Main application JS is **307.12 kB / 94.42 kB gzip**; CSS is **30.40 kB / 7.95 kB gzip**. Rendering and scan processing do not wait for animations.
- Updated the compatible Vitest dependency to **4.1.12** after reviewing the dependency audit. Installation audit reported **zero frontend dependency vulnerabilities**. This does not represent a full application security audit.
- Main results now show only supported fields with human-readable states. Raw OCR, scores, alternate readings and selection reasons remain optional. Clear labeled print takes priority over conflicting MRZ readings; optional `selection_basis` and `display_label` metadata preserve traceability and printed name headings without changing canonical field keys.
- The source package excludes private manifests, original images, model files, caches and credentials. Real-sample expected values remain local in an ignored manifest, not public test fixtures.
- **Application servers were not started.** Browser use was unavailable in this environment; visual mobile/tablet/desktop and screen-reader acceptance remain manual checks. Automated tests use jsdom. Severe blur and residual MRZ disagreements still require review.

See [implementation-review.md](implementation-review.md) for the requirement-by-requirement assessment and sample-test instructions.

## OCR text as main results — 27 October 2026

- Text readings now appear in an expanded main section. When no field values are identified, the summary counts text regions and the OCR readings appear first instead of an empty-field message. Recognized fields and unmatched text can also appear together.
- Each selected reading retains its OCR confidence. Alternate/enhanced readings stay collapsed; copying OCR text copies the selected readings in order, without changing characters or inventing field labels.
- Frontend production build, TypeScript, ESLint and **16 tests passed**. New coverage checks seven unclassified readings, collapsed retry details, exact copied text, coexistence with structured fields, and the genuinely empty state.
- Backend extraction was unchanged in this update; the existing verification below still applies. Application servers were not started, and no new browser/device verification is claimed.

## Supplied-image follow-up — 27 October 2026

- The complete backend suite passed **155 tests**, including real ONNX OCR. One further regression checks reversed OCR row order; the final extraction suite passed all **79 cases**, for **156 verified backend cases** overall. Frontend production build, TypeScript, ESLint and **13 tests** passed; Python Ruff checks passed.
- Reproduced the reported full-name bug on the user-provided ID: the detector's two text rectangles overlapped vertically, so the previous continuation rule rejected the second row. The corrected geometry joins the entire name while keeping the two original evidence records. Issue/expiry dates centered beneath wide bilingual captions are now associated correctly.
- Three supplied U.S. passport photographs now crop to their booklets. Two originally exceeded the 20-megapixel limit; inputs up to 40 megapixels are now accepted with bounded processing dimensions. Translated captions no longer become surname/nationality/sex values. The selected given names, surnames, combined names, document numbers, and birth/issue/expiry dates match the visible text in these three samples. A malformed month reading is corrected only from a separate actual OCR observation, and remains uncertain.
- One passport's MRZ still confuses letters with digits in its names. Correct printed names are shown, with the differing MRZ evidence retained. This is not claimed as perfect MRZ transcription.
- The supplied 576×432 Indian passport image remains unsuitable for reliable field extraction: small captions are blurred and the number is masked. Enlarging it was tested but did not restore reliable readings; no hidden number or missing characters were fabricated.
- Images and private OCR diagnostics are excluded from the source package. Regression tests use fictional names and identifiers. Servers were not started. Visual browser/device review remains unavailable as described below.

## Update — 27 October 2026

- Backend: 132 tests passed in the complete suite, followed by 4 newly added passing regression cases and one additional format/conflict regression (137 total verified cases). The additional checks exercise a generated wrapped-name image with the real OCR model, DMY/MDY/auto dates through the in-process API, and retention of conflicts when a preferred number fails format checks. The final extraction suite passed all 64 cases.
- Frontend: 11 tests passed, including value-first display with collapsed evidence and day/month/year display/copy. Production build, TypeScript and ESLint passed. The workflow suite passed again after asserting that the UI sends `date_order: dmy`.
- Python Ruff lint and formatting passed.
- `scripts/evaluate_accuracy.py` compared six expected fields on the same fictional clear image, Gaussian blur at sigma 0.8 and 1.2, and a 576×360 version. Each case improved from 5/6 to 6/6 exact field values: the missed dotted DOB caption/date was recovered. Raw before/after observations are in `accuracy-before.json` and `accuracy-after.json`. This small fixture is a regression check, not a general OCR accuracy estimate or proof that severely blurred characters can be recovered.
- Wrapped names now combine adjacent rows; genuine differences show the highest-confidence reading with alternatives and the conflict status retained. Enhanced crop retries preserve their original observations. No actual user passport/ID image was available for reproducing the reported name layout.
- Application servers were not started during this update, as requested. The browser/device verification limitation below still applies. The performance figures below are historical and predate these changes.

## Original verification — 26 October 2026

Date: 26 October 2026. All images used were generated fictional specimens or public ICAO example strings, not actual identification documents.

## Executed checks

| Check | Result |
| --- | --- |
| Backend pytest suite, with `DOCULENS_TEST_REAL_OCR=1` | **117 passed** |
| Backend Ruff lint | Passed |
| Frontend strict TypeScript check (`tsc -b`, included in build) | Passed |
| Vite production build | Passed; approximately 301 KB JS / 92 KB gzip and 29 KB CSS / 8 KB gzip |
| Frontend ESLint | Passed |
| Vitest / Testing Library | **9 passed** |
| Live HTTP health and production HTML | Both HTTP 200, OCR ready |
| Live multipart upload → real OCR → result → corrected JPEG | Passed, 8 candidate fields produced |
| Second-session result access | Rejected with HTTP 404 |
| Delete → subsequent image access | Rejected with HTTP 404 |
| Real Latin OCR at 0°, 90°, 180°, 270° | Text read and orientation corrected |
| Real Arabic OCR smoke | Logical Unicode label and English test caption read; accuracy limitations below |

The backend tests cover MRZ formats/checksums/extended numbers, dates and century uncertainty, aliases and spatial matching, UAE number patterns, conflicts/evidence, image decoding/EXIF/limits, crop geometry, noisy/dark/blurred synthetic inputs, OCR normalization, ownership, expiry, errors, capacity and cancellation. Ordinary API unit tests inject a controlled OCR service; the separate integration suite and live HTTP smoke use actual RapidOCR/ONNX models.

The frontend tests cover upload preview, file validation, backend failure, scan failure, cancellation and a stale completion, cleanup, field display, copy/export, conflicting evidence and keyboard crop adjustment. They run in jsdom, not a visual browser.

One dependency emits a non-failing deprecation warning: Starlette's current TestClient recommends `httpx2` rather than `httpx`. The tested client remains functional; the warning is not suppressed.

## Accuracy observations

- The Latin synthetic passport produced a correct surname and several other printed fields. Its MRZ reading contained `UT0` instead of `UTO` in the nationality slot. Numeric checksums still passed because that slot is not covered by the composite checksum. Structure validation failed; the application flagged uncertainty/conflict instead of repairing the character or accepting the MRZ as valid.
- The optional Arabic model correctly recognized `الجنسية` in logical order, but misread another Arabic label/value and confused `0` with `O` in a Latin ID-number line. An initial exact-word Arabic assertion failed. The final smoke test deliberately checks script routing and logical order, not perfect transcription, and the product labels Arabic mode experimental. No Arabic accuracy percentage is claimed.
- A valid MRZ parser fixture is not evidence that every photograph of that fixture will be read correctly.
- No authorized real-document corpus was available. Country/layout-specific recall, precision and field accuracy remain unmeasured.

## Performance

The machine-readable [benchmark report](benchmark.json) contains the final measured p50, p95, cold startup, per-stage samples, process resident memory and four requests from two concurrent clients. The included script reproduces these measurements.

Final run: **1,777 ms p50**, **2,060 ms p95**, **3,759 ms cold model startup**, and **165.84 MB resident process memory**. These figures apply only to the synthetic fixture and the methodology below.

Method: one generated 1400×940 JPEG, 10 sequential scans after model startup, in-process FastAPI ASGI client, actual CPU ONNX inference, 20 ms polling interval, one OCR worker. Cold startup includes the model self-test but excludes Python module-import time. Request latency includes submission/polling/serialization overhead; it excludes external network latency. The detection and perspective correction time is measured together. Resident memory is an end-of-run snapshot, not peak memory. Native OCR calls are serialized, so simultaneous requests queue.

Hardware: Windows 11, Intel family 6 model 154 stepping 3, 12 logical processors, approximately 15.7 GB RAM. The machine is not a controlled benchmark host. The final measurement was run after build/test activity finished, but other user/system processes were not stopped. A ten-sample p95 is descriptive only; it is not a production latency guarantee.

## Not verified / not included

- Desktop/mobile visual browser inspection: **blocked because local browser use is disabled in Work settings**. No screenshots or device-level accessibility/conformance claims are provided. Responsive CSS, focus states, semantic controls, reduced-motion handling and keyboard crop controls exist, but require visual/device review.
- Docker build, HTTPS reverse proxy and public multiuser deployment: recipes/guidance supplied, not executed or deployed.
- Trained document-boundary fallback: not supplied. Classical edge/threshold/Hough methods plus manual four-corner fallback are implemented.
- Universal passport/ID/script support, document authenticity, NFC/barcodes, anti-fraud checks and calibrated OCR confidence: not claimed.

Initial sandbox restrictions blocked package downloads and Windows asyncio loopback sockets. Approved dependency installation and test execution subsequently succeeded. The temporary approval-review usage-limit failure was resolved on continuation; it did not invalidate or erase source work.
