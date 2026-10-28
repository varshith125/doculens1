# DocuLens

A local passport and identity-document scanner. Upload a JPEG, PNG or WebP, review the corrected image beside extracted fields, inspect the supporting OCR evidence, and copy or export the results.

DocuLens performs actual OpenCV image processing and RapidOCR inference on ONNX Runtime. It uses no remote AI API, fabricated scan data, LLM field completion, or document database. All source was created in this project.

## What works

- Single-image and front/back scans with truthful processing stages and cancellation.
- EXIF orientation handling, conservative document detection, perspective correction, quality warnings, and keyboard/touch four-corner adjustment.
- Reused local OCR models returning recognized text, confidence and bounding boxes. Orientation voting uses selected text regions; uncertain recognition retries are limited to six regions with two enhancement variants. Initial and retry readings remain available in source details.
- TD1, TD2 and TD3 MRZ parsing, field checksums, composite checksums, format validation and extended TD1/TD2 document numbers.
- English, French and Arabic label aliases, spatial value association, Emirates ID number candidates and extensible extraction rules.
- Explicit uncertainty and contradictions. A preferred reading is shown with a verification state and all alternatives retained. Clearly labeled printed values take priority over conflicting MRZ readings; uncertain print can be cross-checked with checksum-validated MRZ data. Missing fields stay absent.
- Lazy-loaded GSAP page, upload, processing and results transitions, with reduced-motion handling and scoped cleanup.
- Immediately visible, copyable MRZ; one collapsed Technical details area; a bounded following preview with a compact mobile comparison toggle. Startup connectivity checks retry transient failures automatically and retain Reconnect for persistent failures.
- Protected corrected/original image access, temporary RAM-only scan storage, JSON export, copy actions and a responsive React interface.

This is a document-reading application, not an identity-verification or authenticity service. Five user-authorized images were checked locally alongside synthetic regressions. This small sample does not establish country-wide accuracy. See [the 17-section implementation review](docs/implementation-review.md) for implemented behavior, evidence and remaining limits.

## Requirements

- Python **3.11–3.13**, preferably 3.12. Python 3.14 is intentionally excluded until the full OCR stack is verified with it.
- Node.js 22 LTS or a supported newer release; npm.
- A CPU with ONNX Runtime support, approximately 4 GB available RAM recommended for development. GPU is not required.
- Internet access for initial package/model installation. Scanning works offline afterward.

## Install on Windows

Run commands from this `doculens` directory. Using a Python 3.12 installation:

```powershell
py -3.12 -m venv .venv
.\.venv\Scripts\python.exe -m pip install -e ".\backend[dev]"
Copy-Item .env.example backend\.env
cd frontend
npm install
npm run build
cd ..
.\start.ps1
```

If you use `uv`, replace the first two commands with:

```powershell
uv venv --python 3.12 .venv
uv pip install --python .venv\Scripts\python.exe -e ".\backend[dev]"
```

Open **http://127.0.0.1:8000** when the server reports startup complete. The first startup loads and self-tests the local OCR sessions. The production frontend is served by FastAPI on the same origin. Stop with Ctrl+C. `start.ps1` checks that dependencies and the frontend build are present; it does not install software or change execution policy.

If PowerShell script execution is restricted, run directly:

```powershell
cd backend
..\.venv\Scripts\python.exe -m uvicorn app.main:app --host 127.0.0.1 --port 8000 --no-access-log
```

The dependencies installed during development remain in `.venv` and `frontend/node_modules` in this workspace. They are excluded from the source ZIP. For repeatable installations, use `backend/requirements-lock.txt` as pip/uv constraints and `npm ci` for the frontend. The Python snapshot was generated on Windows/Python 3.12; other platforms may need environment-specific resolution.

## Install on macOS/Linux

```bash
python3.12 -m venv .venv
.venv/bin/python -m pip install -e './backend[dev]'
cp .env.example backend/.env
cd frontend
npm ci
npm run build
cd ../backend
../.venv/bin/python -m uvicorn app.main:app --host 127.0.0.1 --port 8000 --no-access-log
```

## Development

Run FastAPI as above, and Vite in a second terminal:

```powershell
cd frontend
npm run dev
```

Visit http://127.0.0.1:5173. Vite proxies `/api` to port 8000. Use the same hostname throughout a session. No document data is stored in localStorage, sessionStorage or an analytics service.

## OCR models and languages

RapidOCR **3.10.0** is pinned because the service explicitly selects the local models bundled with that release:

| Role | Model |
| --- | --- |
| Text detection | `PP-OCRv6_det_small.onnx` |
| Text-line orientation | `ch_ppocr_mobile_v2.0_cls_mobile.onnx` |
| Default recognition | `PP-OCRv6_rec_small.onnx` |
| Optional Arabic recognition | `arabic_PP-OCRv4_rec_mobile.onnx` |

The bundled recognizer was verified on synthetic Latin text. Its embedded character dictionary has no Arabic characters. It must not be presented as an Arabic recognizer. Other scripts in its dictionary have not been evaluated here.

### Arabic mode (experimental)

From the project root:

```powershell
.\.venv\Scripts\python.exe scripts\download_arabic_model.py
```

Restart the backend. The downloader retrieves the official model and verifies its SHA-256 before installation. The service automatically discovers it under `models/`. Alternatively, set `DOCULENS_ARABIC_MODEL_PATH` in `backend/.env`. The official ONNX model embeds its dictionary; a separate dictionary path is only needed for a custom model without embedded keys. The current workspace has this optional model installed; the source ZIP uses the downloader instead of bundling it.

Arabic mode replaces the recognition model for that scan; it does not run two full OCR engines on every image. Both models are cached when used. Browser rendering applies bidi layout; the backend preserves logical Unicode instead of RapidOCR's optional display-order transformation.

Synthetic Arabic recognition was exercised and correctly read the label `الجنسية`, but it misread other Arabic text and confused zero with `O` in an English ID-number line. Arabic mode is therefore explicitly marked experimental. English text may also perform differently under that recognizer. Always inspect the source and do not treat a high score as proof of accuracy.

## Reading workflow

1. Add the document front. Add its reverse separately if useful.
2. Select the recognition language and start scanning.
3. Compare the corrected image with the original. Automatic cropping is always identified as an estimate.
4. If necessary, rotate or adjust all four corners. These changes clear old results; scan again to obtain results for the new crop.
5. Read or copy the labeled extracted values and immediately visible MRZ. Adjacent wrapped name lines are joined, including slightly overlapping or tilted OCR boxes. Full names appear first; separate given/first, middle and surname/last names retain their headings and values. An assembled full name keeps its component fields unchanged. Only supported fields appear; unreadable associated fields retain their headings. Raw text, scores, evidence, alternatives and validation notes are in the single collapsed Technical details section below MRZ. If no field can be matched, the interface explains this and retains the transcript. Choose the printed date order (day/month/year by default); recognized full-year dates display and copy as DD/MM/YYYY and export as ISO YYYY-MM-DD. Raw OCR and MRZ text stay as read. Emirates ID numbers display with 3-4-7-1 grouping while JSON retains the digits. Passport numbers retain original letters and leading zeros. During review, use the following preview, Zoom/Fit, or the mobile comparison toggle; expand Upload and scan settings to change inputs or rescan.
6. Clear the scan to remove server results immediately.

Manual crop coordinates refer to the EXIF-corrected original image, before rotation. Automatic crops include a small edge margin. When detection is uncertain or multiple separate document candidates exist, the pipeline retains the complete image and asks for manual selection.

## API

All endpoints are under `/api/v1`:

| Method / path | Behavior |
| --- | --- |
| `GET /health` | Readiness, available model routes, limits and version |
| `POST /session` | Creates/reuses an opaque signed HttpOnly session cookie |
| `POST /scans` | Multipart `front`, optional `back`, optional JSON `options`; returns HTTP 202 |
| `GET /scans/{id}` | Current stage, completed result or safe error |
| `GET /scans/{id}/image` | Session-restricted JPEG; `side=front|back`, `variant=original|corrected` |
| `DELETE /scans/{id}` | Cancels/deletes this session's scan; HTTP 204 |

Create a session first and retain its cookie. An unowned scan returns 404. Options are described in [docs/contract.md](docs/contract.md). For example:

```json
{"front":{"rotation":0,"corners":null},"back":{"rotation":0,"corners":null},"language":"latin","date_order":"dmy"}
```

Status polling returns `scan_id`, `status`, `stage`, `result` and `error`. A result includes `fields`, `other_fields`, `mrz`, `ocr_lines`, `images`, `warnings` and `timings_ms`. Every field carries evidence, confidence when available, status and a reason when uncertain. Bounding boxes use corrected-image pixels. A damaged image may be accepted as a queued upload and then fail safely during decoding; no successful result is fabricated.

The OpenAPI schema is at `/openapi.json`; interactive API docs are disabled by default. Session cookies are not a substitute for organizational authentication.

## Pipeline and code layout

```text
frontend/src/
  components/      Upload, crop, preview, progress, fields and shadcn-style button
  hooks/           Scan lifecycle and object-URL cleanup
  services/        Same-origin API client
  types/           Strict TypeScript contract
  styles/          Tailwind and responsive visual styling
backend/app/
  main.py          FastAPI routes, lifespan, middleware and static frontend
  core/            Settings, signed sessions, bounded RAM store, request limits
  services/        Image validation/correction, OCR sessions, scan orchestration
  extractors/      MRZ parsing, labels, spatial association, evidence merging
  patterns/        Dates, country aliases, document number rules
  schemas/         Pydantic request/result models
```

Pillow verifies file headers, frame counts and dimensions before pixel allocation and normalizes EXIF orientation. Accepted images up to 40 megapixels are reduced to at most 16 megapixels and a 6000-pixel edge for processing. Normalized crop coordinates remain relative to the full image. OpenCV converts colors, analyzes edges/thresholds/Hough lines, estimates corners and applies perspective transforms. Small document candidates can occupy as little as 4.5% of the frame; a blue-paper color mask provides an additional fallback for some booklet covers/pages when grayscale contours fail. Blur, contrast, lighting, shadows, noise and resolution metrics produce warnings. CLAHE is applied only when measured contrast or brightness warrants it. A metadata-free full-image JPEG preview is retained separately, while the browser retains the original selected file until cleared.

A bounded executor keeps decoding and inference off the event loop. The OCR service serializes its ONNX calls and limits native threads; increasing `DOCULENS_WORKERS` does not imply parallel OCR inference. Up to six lower-confidence regions receive enlarged and contrast/sharpened rereads. A changed reading is used only when both variants agree with at least 85% confidence and exceed the initial score by eight percentage points. Such fields remain uncertain, with all observations retained. These are correlated readings from the same model, not independent verification. `perf_counter` measures processing durations and `monotonic` measures queue/retention times.

There is one explicit date fallback: a malformed named month such as `0CT` triggers a reread even at high confidence. If a retry actually reads one unambiguous valid calendar date at 90% confidence or above, that observed date may be selected as uncertain. No character replacement is applied to manufacture a valid date; the original and retry observations remain available.

React uses an AbortController and generation counter to ignore stale requests, disposes protected image blob URLs, and deletes known server scan IDs on reset/cancellation. Native inference already running cannot be forcibly interrupted; its result is discarded after cancellation. If a network request is aborted before the returned scan ID arrives, the server's retention policy is the cleanup fallback.

## Validation and extension

MRZ checks use ICAO weights 7, 3, 1, exact line lengths and structure. No `O`/`0` substitution or missing-character completion is performed. Checksums do not cover every field and do not establish authenticity. MRZ dates retain `YYMMDD` and are uncertain until corroborated by an unambiguous printed full-year date; no century is invented.

Add label aliases in `patterns/common.py`, then add synthetic spatial/label tests. Country number rules live in `patterns/passports.py`; UK and US syntax checks are deliberately conservative and warn about legacy/exceptional formats. Add country rules only with a documented source and tests. The `784` Emirates ID pattern normalizes separators but does not infer birth year, nationality or other personal attributes.

Front/back candidates are compared under explicit normalization. Genuine contradictions retain all evidence and the `conflicting` status; the highest-confidence observed value is displayed and exported (ties preserve the first reading). A populated value does not imply resolved agreement. Source details expose alternatives without replacing the name or number with a warning. Consecutive aligned name rows are joined only on the same side and without crossing another caption. This is not proof that two uploaded sides belong to the same physical document.

## Configuration

Copy `.env.example` to `backend/.env`, or use environment variables. Start the backend from `backend/` so its `.env` is discovered.

| Variable | Default / meaning |
| --- | --- |
| `DOCULENS_ALLOWED_ORIGINS` | JSON array of local origins; exact CORS/unsafe-request allowlist |
| `DOCULENS_ALLOWED_HOSTS` | JSON array: localhost, 127.0.0.1, testserver |
| `DOCULENS_COOKIE_SECURE` | `false` for local HTTP; set `true` for HTTPS |
| `DOCULENS_RETENTION_SECONDS` | 900; scan lifetime from submission, 30–3600 allowed |
| `DOCULENS_MAX_UPLOAD_MB` | 12 per image, maximum 12 |
| `DOCULENS_MAX_ACTIVE_SCANS` | 8 total retained/queued scans; maximum 2 per session |
| `DOCULENS_MAX_STORAGE_MB` | 160 for retained encoded images |
| `DOCULENS_WORKERS` | 1 image-processing worker; ONNX access remains serialized |
| `DOCULENS_ARABIC_MODEL_PATH` | Optional absolute recognizer path; otherwise auto-detect project `models/` |
| `DOCULENS_ARABIC_DICTIONARY_PATH` | Optional dictionary for a compatible custom recognizer |

## Security and retention

- Default loopback binding; no public deployment is performed.
- Upload content signatures, format verification, 12 MB/image limits, 40 megapixels, 12,000-pixel maximum input edge, bounded processing dimensions, and single-frame checks.
- A streaming request-body limit applies before multipart parsing. Bounded multipart files stay in RAM rather than spooling identity images to disk.
- Signed random session cookies, HttpOnly/SameSite Strict, per-session ownership, allowed hosts/origins and no-store responses.
- Uploaded bytes are released after processing. Images/results are removed on clear, expiry, shutdown or restart. A sweeper runs at most every 15 seconds; access also checks expiry. Running native inference can retain temporary buffers until it returns.
- No OCR text or document-number logging, analytics, external AI calls, durable history or public image links. Do not enable request-body logging in a proxy.
- JSON exports, clipboard contents, user-selected source files and browser memory remain outside server deletion control. RAM may be paged by the operating system; this is not a secure-erasure guarantee.

For multiuser/public operation, add authenticated identity and authorization at the gateway, HTTPS, external rate limiting, trusted proxy settings, operational limits and a reviewed data-retention policy. Use **one Uvicorn process**: session signing keys, jobs and images are process-local. Multiple workers require shared authenticated job/storage infrastructure or sticky routing with stable signing keys; it is not implemented here.

## Tests and measurements

Windows, from `backend/`:

```powershell
..\.venv\Scripts\python.exe -m pytest -q
..\.venv\Scripts\python.exe -m ruff check app tests
$env:DOCULENS_TEST_REAL_OCR='1'
..\.venv\Scripts\python.exe -m pytest -q
```

Frontend, from `frontend/`:

```powershell
npm test
npm run lint
npm run typecheck
npm run build
```

From the root, with a running production server for the HTTP smoke test:

```powershell
.\.venv\Scripts\python.exe scripts\smoke_http.py
.\.venv\Scripts\python.exe scripts\benchmark.py --runs 10 --output docs\benchmark.json
.\.venv\Scripts\python.exe scripts\generate_fixture.py docs\specimen.png
```

See [docs/verification.md](docs/verification.md) and [docs/benchmark.json](docs/benchmark.json) for executed results, methodology and limitations. Normal tests use dependency injection to isolate API failures. The opt-in integration suite and benchmark execute real ONNX inference. Fixtures are clearly fictional or public ICAO sample data; no real identity documents are included.

## Deployment

The simplest deployment is the built frontend served by the single FastAPI process. Put a trusted authenticating HTTPS reverse proxy in front, set exact allowed hosts/origins and secure cookies, and limit requests at that proxy. Keep `/api` on the same origin. Do not expose the unauthenticated development server on a public interface.

An optional Dockerfile builds the frontend and backend:

```bash
docker build -t doculens .
docker run --rm -p 127.0.0.1:8000:8000 doculens
```

The Docker recipe is supplied but was not executed in this environment. Arabic is optional in Docker: mount a verified model read-only and set `DOCULENS_ARABIC_MODEL_PATH`. No cloud hosting or external data transfer is required.

## Known limitations

- No trained document-boundary detector is included. Edge, threshold and Hough methods can fail on textured backgrounds, severe perspective or very small documents. Use manual corners; compare every edge and the MRZ.
- Severe blur, glare, hidden/cut-off text and missing pixels cannot be recovered. Quality metrics are heuristics, not calibrated readability guarantees.
- Recognition/extraction coverage is not universally verified for Indian, UAE, US, UK, European or other passports. Country-independent labels/MRZ are implemented; real layout-specific accuracy remains to be measured with authorized examples.
- Arabic is experimental. Other languages have no measured coverage. Mixed-script text and complex label layouts may fail or create conflicts; printed names can differ from MRZ transliteration.
- Non-MRZ document authenticity, face matching, NFC chips, signatures, barcodes, PDFs, animated images and multi-page documents are outside this version.
- Browser visual/responsive/accessibility inspection was blocked by the desktop app's disabled local-browser automation. Responsive CSS and accessible controls are implemented; component tests are not a substitute for real device testing.
- Benchmarks use a small synthetic corpus on one machine, include polling overhead and are not accuracy or production-load guarantees.

## Sources

- [ICAO Doc 9303 Part 3: common specifications](https://www.icao.int/publications/documents/9303_p3_cons_en.pdf)
- [ICAO Doc 9303 Part 4: TD3 passports](https://www.icao.int/sites/default/files/publications/DocSeries/9303_p4_cons_en.pdf)
- [ICAO Doc 9303 Part 5: TD1 documents](https://www.icao.int/sites/default/files/publications/DocSeries/9303_p5_cons_en.pdf)
- [ICAO Doc 9303 Part 6: TD2 documents](https://www.icao.int/sites/default/files/publications/DocSeries/9303_p6_cons_en.pdf)
- [RapidOCR installation](https://rapidai.github.io/RapidOCRDocs/main/en/install_usage/rapidocr/install/)
- [RapidOCR model routes](https://rapidai.github.io/RapidOCRDocs/main/en/model_list/)

Third-party packages/models retain their own licenses. No pretrained weights were authored in this project.
