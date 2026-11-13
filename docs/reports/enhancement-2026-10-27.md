# MRZ, comparison and connectivity enhancement

Implemented in the existing DocuLens project on 27 October 2026. No application servers were started. OCR models, endpoints, canonical fields, GSAP lifecycle, temporary storage, crop/rotate, cancellation and JSON export are retained.

## Changes and root causes

| Files | Change |
| --- | --- |
| `frontend/src/hooks/useBackendHealth.ts`, `App.tsx`, `services/api.ts` | Replaced the single startup health probe with a bounded, cancellable readiness check. Four attempts, delays of 0/500/1000/2000 ms, 4-second request timeouts; no continuing polling. Requests use the existing relative `/api/v1/health`, same-origin credentials and `cache: no-store`. |
| `frontend/src/components/Results.tsx`, `TechnicalDetails.tsx` | MRZ heading and exact source lines are visible immediately, regardless of validation, with Copy MRZ. Absence says “MRZ not available”. Raw OCR, confidence, per-field evidence, alternatives, warnings, checksums and authenticity notes are grouped below it in one collapsed Technical details area. Additional useful fields join the ordinary field list. |
| `frontend/src/components/DocumentViewer.tsx`, `App.tsx`, `styles/index.css` | Desktop preview follows the results within the comparison container. Viewport-relative canvas height, independently scrollable zoomed image, keyboard focus and Fit control. Scan settings collapse during review; opening them returns the panel to normal page flow. Mobile has a compact comparison toggle; very short viewports use normal flow. |
| `backend/app/extractors/mrz_parser.py` | `raw_lines` retains actual recognized characters, case and spaces. Normalization for parsing is separate. Incomplete MRZ evidence also retains adjacent candidate rows without inventing a complete zone or parsed fields. |
| `backend/app/extractors/spatial_matcher.py` | Field association and wrapped-name geometry are measured in the label’s text angle, rather than its inflated axis-aligned rectangle. Original OCR boxes and evidence remain unchanged. |
| `backend/app/extractors/field_extractor.py` | A nonnumeric garbled translation after a recognized date caption no longer blocks association with the printed date below it. An invalid numeric inline date is still preserved and marked uncertain; it is not silently replaced. |
| `backend/tests`, `frontend/src/test`, `scripts/evaluate_accuracy.py` | Added MRZ visibility/copy, diagnostics/export, startup recovery/StrictMode, timeout/unmount, keyboard comparison, tilted geometry, unreadable-pixel and real blurred-sample checks. |

The false disconnect was reproducible in the old code: React StrictMode cleanup aborted a health request, but its catch handler still set the error flag. A newer success updated the service without clearing that flag. Transient proxy/startup failures also had no retry. The new hook ignores obsolete requests and updates readiness/error together. Vite already proxies `/api` to `http://127.0.0.1:8000`, and the configured backend accepts the development origins; neither startup commands nor endpoints required changes.

## Extraction evidence

Four initial generated cases (mild blur, low contrast, tilt and reduced resolution) already returned all six checked fields. More distant, tilted cases reproduced three missing given-name fields even though the OCR text itself was correct. Matching the unchanged OCR observations using aligned geometry improved those cases from 5/6 to 6/6 checked fields. See [tilted-field-comparison.json](tilted-field-comparison.json). No model, dictionary completion or additional enhancement pass was needed.

A derived mildly blurred authorized ID reproduced a separate failure: a garbled, nonnumeric suffix after the issue-date caption prevented the correct nearby date from being selected. A focused regression now covers that behavior without storing the private identity values in source.

Private sample ground truth was read from the supplied originals independently of OCR. The test reuses those same expected values for each original and its Gaussian-blur variant (7×7 kernel, sigma 1.2). Variants remain in memory; PNG is used unless it exceeds the existing 12 MB upload bound, in which case JPEG quality 95 is used. The limits themselves were not relaxed. The masked sample only checks non-extraction of the unavailable number, not accurate recovery of every blurred field.

Generated test ground truth comes from known fictional rendering text, not model output. These small sets are regression evidence, not general accuracy estimates.

## Commands and execution record

Run from `doculens` unless a working directory is specified. Final results are recorded in [verification.md](verification.md).

```powershell
# Backend directory; private manifest remains ignored and is not included in exports.
$env:PYTHONUTF8 = '1'
$env:DOCULENS_TEST_REAL_OCR = '1'
$env:DOCULENS_SAMPLE_MANIFEST = '<absolute path to your private authorized manifest>'
..\.venv\Scripts\python.exe -m pytest -q

# Project directory
.\.venv\Scripts\python.exe -m ruff check backend scripts
.\.venv\Scripts\python.exe -m ruff format --check backend scripts

# Frontend directory
npm.cmd test
npm.cmd run lint
npm.cmd run build
npm.cmd run format:check
```

The production build includes strict TypeScript checks. Initial focused frontend and extraction runs passed. Subsequent tests exposed one ambiguous test query, the blurred-ID mapping defect, and two oversized generated PNG fixtures; these were corrected and rerun. No private values are included in this report or in distributed fixtures.

## Manual browser acceptance (not performed)

Use the existing backend and frontend startup commands yourself, then open the existing development URL. No browser/device verification is claimed from jsdom tests or CSS inspection.

1. **Connectivity:** With the backend ready, reload the frontend normally and in React development mode. It should connect without Reconnect. Start the frontend just before the backend: it should show Connecting during the bounded retries, then become ready automatically. With the backend stopped throughout, an accessible error and Reconnect must appear after retries end. Start the backend afterward and confirm Reconnect works. In Network tools, check relative `/api/v1/health` requests, no stale cache, and no continuous polling. StrictMode may show an extra aborted development probe.
2. **MRZ:** Scan a clear passport, then an imperfect passport with incomplete/invalid MRZ. Both must show the recognized lines under “Machine-readable Zone (MRZ)” without opening anything. Copy and compare characters, spaces, fillers and line order. An ID without MRZ must say “MRZ not available”.
3. **Primary results:** Check names, dates, document number and Document Code. There should be no generic Front/Line rows, OCR region counter, separate Additional printed fields section, or primary checksum panel. Open Technical details below MRZ to access all diagnostics and copy raw text. Export JSON and confirm evidence and canonical dates remain intact.
4. **Desktop/tablet:** At approximately 1440×900, 1024×768 and 820×1180, scroll to lower fields and MRZ. The left preview should follow within the workspace, stop at its boundary and remain useful. Zoom/pan to both names and the bottom MRZ; Fit resets scale and pan. Open scan settings to ensure all upload/rescan controls remain reachable in normal flow.
5. **Mobile:** At 390×844, 360×640 and landscape height below 500 px, use Compare with document / Hide document comparison. Results must remain reachable without horizontal page overflow. MRZ may scroll horizontally inside its own text area to preserve line breaks. Very short screens deliberately disable sticky positioning.
6. **Keyboard/motion:** Tab through comparison, preview, zoom, rotate/crop, MRZ copy and Technical details. Use arrow keys on a zoomed preview and Enter on the comparison toggle. Confirm focus remains visible. Enable reduced motion and repeat upload, cancellation and results review; no animation should delay scanning.

## Limits

- Real viewport positioning, touch panning, browser zoom and screen-reader behavior still need the manual checks above. DOM tests do not establish visual accessibility conformance.
- Severe blur, obscured characters, unsupported layouts/scripts and misread MRZ names remain possible. Uncertainty and raw evidence are retained; no name dictionary or missing-character completion was added.
- Automatic readiness recovery is intentionally bounded. If the backend starts after the retry window, use Reconnect. This does not provide continuous server monitoring.
- Existing native OCR calls finish before cancellation can release the worker; results from cancelled scans are still discarded.
