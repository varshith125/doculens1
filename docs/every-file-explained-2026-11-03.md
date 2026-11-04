# DocuLens: every project file explained

Prepared on 3 November 2026 from the working files in this workspace. This guide explains the current application, including uncommitted changes. Application code was not changed. No new application test run, OCR benchmark, or browser check was performed for this guide.

Start with [the concise architecture reference](../ARCHITECTURE.md). After this inventory was taken, the older extracted folder and source ZIP were consolidated into `DOCULENS/.archive/doculens-source-snapshots-2026-11-03.zip`; the historical paths below describe that pre-cleanup snapshot. Regenerable caches were removed. The separate generated JSON inventory was removed to avoid duplicating this guide's file table.

The active tree contained **120 project/configuration/documentation/model/fixture files before this guide was added**, excluding installed dependencies, generated builds, Git internals, caches, bytecode, and installation metadata. Those generated categories are explained separately below. The older extracted copy contains 86 corresponding files. The ZIP has 93 files and is a third snapshot; it is not identical to the extracted copy. A per-file comparison is appended at the end.

## Understand the file types first

| Extension/name | Meaning here |
| --- | --- |
| `.py` | Python source: backend logic, tests, or development scripts. |
| `.tsx` | TypeScript source that can contain React interface markup. |
| `.ts` | TypeScript source without React markup, usually helpers/types/configuration/tests. |
| `.js` | JavaScript configuration in this project. |
| `.css` | Interface appearance and responsive layout rules. |
| `.html` | The browser page that starts the frontend. |
| `.json` | Structured data: configuration, dependency lock, or recorded measurements. |
| `.toml` | Python project/build/tool configuration. |
| `.md` | Markdown documentation such as this guide. |
| `.ps1` | PowerShell script for Windows startup. |
| `.env` | Machine-local settings; it is not application source and should not be distributed. |
| `.onnx` | A trained model graph and weights executed by ONNX Runtime. |
| `.png`, `.svg` | Raster image or vector image asset. |
| `__init__.py` | Establishes a Python package; it may also expose selected imports. |
| `test_*.py`, `*.test.ts(x)` | Automated checks; these are not production scan code. |

## The complete connection between the important files

```text
Browser loads frontend/index.html
  -> src/main.tsx mounts App
  -> App.tsx assembles the screen
  -> UploadArea.tsx selects a file
  -> useBackendHealth.ts checks readiness through services/api.ts
  -> useScan.ts starts a session, uploads files, and polls
  -> backend/app/main.py accepts the request
  -> core/store.py creates a temporary job
  -> services/pipeline.py runs the job in a background thread
       -> imaging.py decodes, crops, rotates, and checks the image
       -> ocr.py runs local OCR and returns text with coordinates
       -> field_extractor.py associates text with fields
            -> document_context.py identifies document family
            -> caption_context.py reconstructs split labels
            -> label_matcher.py recognizes labels
            -> spatial_matcher.py connects labels and values
            -> regions.py separates emergency contacts
            -> mrz_parser.py reads/checks the MRZ
            -> layout_fallback.py provides narrow layout recovery
            -> patterns/ supplies dates, country aliases, and number rules
       -> output.py prepares the final structured output
  -> Results.tsx displays fields; DocumentViewer.tsx shows source locations
  -> review.ts applies local edits; format.ts formats display/copy values
  -> useScan.ts deletes the server job after preview transfer
```

An API is the agreed way the browser asks the backend to do work. JSON is the structured text format used for responses. Multipart upload carries the actual files plus options. OCR is optical character recognition: reading characters from pixels. MRZ is the machine-readable zone containing tightly formatted document text. The backend is one modular application, not a set of separately deployed microservices.

## Workspace and project-root files

**`DOCULENS/.vscode/settings.json`** — Workspace editor settings. `python.analysis.extraPaths` points VS Code at `./doculens/backend` so imports beginning with `app` can be understood. `git.ignoreLimitWarning` controls an editor warning. Neither setting changes extraction behavior.

**`DOCULENS/DocuLens-source.zip`** — A packaged source snapshot with 93 members. It is an archive, not an executable or the current source of truth. It contains seven files absent from the older extracted copy, and 18 shared files have different bytes. It does not automatically update when you edit the active project.

**`DOCULENS/DocuLens-source/doculens/`** — Older extracted project with 86 files. Files have the same general roles described below, but changed implementations lack some newer behavior. The appendix explicitly maps every older file to its current counterpart.

All paths in the rest of this guide are relative to the active `DOCULENS/doculens/` directory unless stated otherwise.

**`README.md`** — Human-facing project overview, setup instructions, OCR model configuration, API summary, workflow, security, and limitations. Read it for orientation, but verify behavior in source: portions still describe older MRZ precedence, date presentation, and cleanup rules.

**`start.ps1`** — Windows launcher. Accepts a `Port` parameter, checks `.venv/Scripts/python.exe` and `frontend/dist/index.html`, changes into `backend`, and runs `uvicorn app.main:app`. `Push-Location`/`Pop-Location` restore the original terminal folder. It does not install dependencies or build the frontend. Starting in `backend` makes its `.env` discoverable.

**`Dockerfile`** — Two-stage container recipe. A Node stage installs/builds the frontend. A Python stage installs the backend, copies the browser build, creates a non-root user, and runs Uvicorn. The final runtime serves both frontend and API. External custom models need appropriate container paths/mounts. Reading this recipe is not evidence that a Docker build has passed.

**`.env.example`** — Configuration template. Documents allowed origins/hosts, secure-cookie choice, retention, upload/job/worker limits, and optional OCR paths. Commented model examples are not active settings. Copying this file supplies defaults for a fresh machine.

**`.gitignore`** — Tells Git which local/generated material normally stays out of version control: environments, dependencies, builds, caches, `.env`, models, logs, and TypeScript build metadata. It does not delete files, encrypt them, or retroactively untrack files already committed.

**`.dockerignore`** — Excludes local environments, models, caches, Git metadata, dotenv files, and selected generated images from Docker's build context. Its purpose is separate from `.gitignore`: it controls what Docker receives.

## Backend setup and entry point

**`backend/.env`** — Actual local backend settings. The current configuration selects a Small resource directory plus Medium detector and recognizer files on the machine's `D:` drive. The model dictionary and orientation resources are still required. Model settings are read at startup; changing them requires restarting the backend. This guide does not reproduce local configuration contents.

**`backend/pyproject.toml`** — Declares the installable Python package, Python compatibility, runtime dependencies, optional development dependencies, and pytest/Ruff configuration. `setuptools` builds/discovers the `app` package. Installing `backend[dev]` includes development tools. Dependencies explain why OpenCV, RapidOCR, PDFium, Pydantic, and related packages are installed.

**`backend/requirements-lock.txt`** — A historical exact-version dependency snapshot. Useful as evidence of an earlier installed environment. It currently omits some later direct dependencies, including pycountry, RapidFuzz, and PDFium, so it should not be treated as a complete current installation specification by itself.

**`backend/app/__init__.py`** — Empty package marker. Allows the application directory to participate in imports such as `app.main`.

**`backend/app/main.py`** — The backend entry point and composition root: it constructs the pieces and connects them. `app = create_app()` creates the application imported by Uvicorn.

- `create_app(settings, ocr)` allows injected settings/OCR, which helps tests substitute a fake engine.
- `lifespan` creates a bounded `ThreadPoolExecutor`, warms up OCR, starts periodic expiry cleanup, and clears resources during shutdown.
- `cleanup` periodically calls `store.prune()`.
- `validation_error` returns a short validation response without echoing submitted document data.
- `health` reports OCR readiness, language routes, limits, and version.
- `session` creates or reuses a signed session cookie.
- `scan` validates scan options, language availability, upload size, and file signatures; creates a job; submits `run_scan`; returns HTTP 202.
- `owned_job` looks up only a scan belonging to the current session.
- `scan_status` returns job status, stage, result, or error.
- `scan_image` serves an owned original/corrected JPEG preview.
- `delete_scan` removes or cancels a job.
- `extract` is a one-shot adapter: it uses the same worker, waits up to 120 seconds, returns extraction without retained preview URLs, and deletes the job afterward. The main UI uses `/scans`, not this adapter.
- If `frontend/dist` exists, it is mounted at `/` so the same server can serve the built interface.

Explicitly configured custom-model initialization failures stop startup; a bundled-model warmup failure can instead yield a degraded service. The OpenAPI JSON schema is enabled while interactive Swagger/ReDoc pages are disabled.

## Backend core: configuration, ownership, and temporary jobs

**`backend/app/core/__init__.py`** — Empty package marker for shared infrastructure.

**`backend/app/core/config.py`** — `Settings` is a Pydantic settings model. It reads variables with the `DOCULENS_` prefix and the current directory's `.env`. Defaults include 900-second retention, 12 MB per upload, eight total jobs, one worker, and a 160 MiB encoded-image budget. Numeric bounds reject unsupported configuration. `get_settings()` is cached to avoid rebuilding settings for every use.

**`backend/app/core/security.py`** — Session ownership, not an account/login system. `Sessions.__init__()` creates a random per-process signing key. `issue()` signs a timestamp and random nonce with HMAC-SHA256. `owner()` checks token shape, age, and signature and derives an ownership key. `require_owner()` is a FastAPI dependency that rejects requests without a valid session. Tokens last up to 24 hours; restarting changes the signing key. The cookie is HttpOnly and SameSite Strict, with Secure controlled by configuration.

**`backend/app/core/middleware.py`** — Request checks surrounding the routes. `RequestGuard.__call__()` optionally requires HTTPS, limits POSTs per client address, checks unsafe request origins, and bounds request bodies before multipart processing. Nested `bounded_receive()` counts streamed bytes; `private_send()` adds no-store, nosniff, no-referrer, and frame-denial headers. `UploadTooLarge` stops oversized bodies. Current POST limiting is 30 requests per client address per minute with a bounded client map. It is an in-process control, not distributed rate limiting.

**`backend/app/core/store.py`** — Temporary in-memory storage. `ScanJob` holds owner, generated ID, creation time, status, stage, result, image bytes, error, and a cancellation event. `ScanStore` protects its dictionary with an `RLock`.

- `create()` prunes expired work, checks total/per-session capacity, then creates a job.
- `get()` checks expiry and ownership.
- `complete()` checks cancellation and retained-image budget before publishing results.
- `delete()` marks cancellation and removes the job/results/images.
- `prune()` expires jobs based on time since submission.
- `clear()` removes all jobs during shutdown.
- `CapacityError` communicates full job/image capacity.

The encoded-image budget excludes model sessions, decoded pixel arrays, result objects, and browser memory. There is no SQL database or persistent scan history. Multiple independent backend processes would need a different shared-state/routing design.

## Backend schemas: the data contract

**`backend/app/schemas/__init__.py`** — Empty package marker.

**`backend/app/schemas/models.py`** — Defines Pydantic models shared by processing and HTTP responses. These classes store/validate information; they do not perform OCR themselves.

| Class/type | What it represents |
| --- | --- |
| `Side` | Front or back. |
| `FieldStatus` | Validated, detected, uncertain, conflicting, or not detected. |
| `OCRObservation` | One original or retry reading with confidence and method. |
| `OCRLine` | Recognized text, confidence, four-corner box, side, observations, review notes. |
| `CaptionFragment` | Original text/box for one fragment of a reconstructed label. |
| `Evidence` | A reading's source, location, label association, candidate value, and checks. |
| `FieldValue` | Selected value plus observed/display/normalized forms, status, evidence, country metadata, and reasons. |
| `MRZResult` | Raw/interpreted MRZ lines, parsed fields, format, checks, warnings, corrections. |
| `ImageResult` | Corrected dimensions, selected corners, crop/rotation, quality, preview routes. |
| `ScanResult` | Final document type, fields, MRZ, images, OCR lines, warnings, and timings. |
| `SideOptions` | One side's rotation and optional normalized crop corners. |
| `ScanOptions` | Front/back options, language, and date order; extra option keys are forbidden. |
| `JobResponse` | Scan ID, state, current stage, optional result/error. |
| `HealthResponse` | Readiness, supported languages, limits, version. |

`value` is the selected machine-facing value, `observed_value` retains a source reading, `normalized_value` is a standardized interpretation when established, and `display_value` is presentation text. A date can be observed as `25 MAR 2000`, normalized as `2000-03-25`, and displayed as `25-March-2000`. Several declarations are duplicated in the current `MRZResult` class body; this is source duplication, not multiple serialized copies of those keys.

## Backend services: running a scan

**`backend/app/services/__init__.py`** — Empty package marker.

**`backend/app/services/pipeline.py`** — The scan coordinator. Its input is a job, uploaded byte strings, options, store, and OCR service. `run_scan()` loops through uploaded sides, decodes each image, processes geometry, runs OCR, prepares preview JPEGs, combines OCR lines, extracts fields, normalizes output, and completes the job. Nested `stage()` updates actual progress and checks cancellation. `measure()` records elapsed milliseconds. `Cancelled` ends cooperative work. Known failures become safe errors; unexpected failures get a generic message. `uploads.clear()` releases the raw-upload references on completion/failure. An already executing native OCR call is not forcibly terminated by cancellation.

**`backend/app/services/imaging.py`** — Works with image pixels and geometry, not identity-field meaning.

- `ImageValidationError` identifies invalid or unsupported image input.
- `ProcessedImage` groups original/corrected arrays with metadata.
- `decode_image()` checks size, format, frame count, dimensions, and corruption; handles EXIF rotation, transparency, resizing, and BGR conversion.
- `decode_pdf()` locks PDFium access; `_decode_pdf()` requires one page, renders it at a bounded scale, and closes page/bitmap/document resources.
- `encode_jpeg()` creates metadata-free JPEG preview bytes.
- `rotate_image()` handles 90/180/270-degree rotation.
- `_order_corners()` establishes a consistent polygon order.
- `validate_corners()` checks four finite normalized coordinates, image bounds, convexity, area, and minimum side length.
- `_warp()` maps four corners to a rectangular image using a perspective transform.
- `_candidate_score()` evaluates possible document quadrilaterals.
- `_line_candidate()` uses Hough lines when contours are incomplete.
- `detect_corners()` uses edges, morphology, threshold contours, a blue-paper fallback, and line evidence. It keeps the full image when boundaries are ambiguous.
- `assess_quality()` measures sharpness, brightness, contrast, overexposure, darkness, uneven lighting, noise, and resolution; these produce warnings, not guaranteed readability judgments.
- `enhance_for_ocr()` conditionally applies local contrast correction.
- `text_region_for_ocr()` rectifies/enlarges a selected text region for rereading.
- `process_image()` chooses manual/automatic cropping, rotates, assesses quality, and returns metadata.

Input raster limits are 40 million pixels and a 12,000-pixel edge; working images are bounded to 16 million pixels and a 6,000-pixel edge. Manual corners are normalized to the EXIF-corrected original before rotation. OCR boxes use corrected-image pixels, so original and corrected coordinates must not be mixed.

**`backend/app/services/ocr.py`** — Executes pretrained models and retains the resulting observations. It does not train a model.

- `OCRUnavailableError` represents unavailable or failed OCR.
- `normalize_output()` converts RapidOCR boxes/text/scores into checked `OCRLine` objects.
- `_reading_order()` sorts lines into an approximate reading order.
- `_rotate_lines()` transforms boxes when the page rotates.
- `_malformed_named_date()` detects damaged month text such as a digit inside a three-character month.
- `_observed_month_reading()` can select an actually observed retry date under narrow constraints; it does not manufacture a date by arbitrary character substitution.
- `OCRService.__init__()` resolves model configuration, establishes a shared lock, and initializes an engine cache.
- `ready` and `languages` expose readiness and available model routes.
- `_get_engine()` loads/caches a selected-language pipeline, applies Small/Medium overrides, validates required resources/dictionary/output classes, and reuses compatible stages.
- `warmup()` runs fictional startup text through the engine before declaring readiness.
- `_read()` executes a full read and conditional recovery.
- `_recover_small_captions()` may run one bounded enlarged biodata pass when a passport MRZ is readable but captions are sparse.
- `_retry_uncertain_regions()` chooses at most six regions for up to two additional readings. Original and alternative observations remain available; changed readings require specific agreement/quality conditions and review.
- `read()` is the normal locked OCR entry point.
- `_orientation()` votes using confident text regions.
- `read_oriented()` can compare right-angle orientations for weak reads, retain the winning reading, restore correct box coordinates, and refine selected regions.

The stages are detection (where text is), classification (line orientation), and recognition (which characters). A recognition dictionary maps model output positions to characters, so dictionary order must match the model. Arabic uses an optional recognizer and retains logical Unicode for browser bidi rendering. OCR calls are serialized under the shared lock; increasing worker count does not create independent parallel OCR engines.

**`backend/app/services/medium_models.py`** — Compatibility checks for configured Medium ONNX exports. `medium_parameters()` reads the model's same-stem `.yml`, checks the declared model/stage and preprocessing, compares recognition dictionary order, and maps settings into RapidOCR parameters. `check_medium_signature()` verifies input/output tensor shapes/types. A detector cannot simply be plugged into the recognizer slot, and equally sized but differently ordered dictionaries are incompatible.

**`backend/app/services/output.py`** — `prepare_output()` adds presentation metadata after extraction. It preserves observed text as `raw`, supplies rectangular box coordinates, uppercases selected name output, adds country codes/names, groups Emirates ID digits, and prepares established date display strings. It also summarizes MRZ checks and print/MRZ agreement. It does not implement an authoritative Emirates ID checksum; that check remains unavailable. It can mutate the extracted field objects passed to it.

## Backend extractors: deciding what text means

**`backend/app/extractors/__init__.py`** — Re-exports `extract_fields` and lists it in `__all__`, allowing callers to import the main extraction entry point from the package.

**`backend/app/extractors/field_extractor.py`** — Central interpretation and evidence-merging logic. Input: OCR lines plus date order. Output: document type/context, selected fields, additional fields, MRZ, and warnings.

| Function | Explanation |
| --- | --- |
| `_evidence()` | Turns a line and its retry observations into traceable supporting evidence. |
| `_visual_value()` | Interprets one associated printed value; validates its field-specific format and preserves the observed form. |
| `_same_value()` | Compares candidates with field-appropriate normalization, without general OCR character guessing. |
| `_name_representations()` | Builds comparison forms for printed/MRZ spelling, accents, punctuation, and selected transliterations. |
| `_selection_basis()` | Determines whether support comes from labeled print, checked MRZ, or an ordinary OCR reading. |
| `_selection_rank()` | Assigns precedence to those evidence categories. |
| `_unresolved()` | Creates a conflicting field with no selected value while retaining evidence. |
| `_mrz_date_with_printed_year()` | Carefully combines a matching explicit printed year with checked MRZ day/month when the permitted partial-date conditions hold. |
| `merge_field()` | Merges agreement, retains disagreement, chooses an eligible primary source, or leaves ambiguity unresolved. |
| `_extract_visual()` | Reconstructs captions, partitions contact sections, associates values, joins eligible names, and collects printed fields. |
| `_mrz_values()` | Converts parsed MRZ fields into the same `FieldValue` structure, with source/check limitations. |
| `_check_dates()` | Evaluates calendar/chronology consistency without swapping dates or rewriting years. |
| `_cross_check_first_name()` | Compares a printed first-name field to MRZ given names without treating them as identical field semantics. |
| `_cross_check_issuer()` | Checks country/issuer information while preserving sources and distinctions. |
| `_assemble_full_name()` | Builds an explicitly marked derived full name only under the supported component/source rules. |
| `extract_fields()` | Calls the helpers, performs document routing/MRZ/layout recovery, merges candidates, and returns the extraction. |

Current associated readable print generally ranks above MRZ. Two incompatible printed candidates or equally supported conflicting candidates can yield `value=None`. Confidence alone is not permission to choose which label owns text. Unknown `word: value` strings stay in the transcript unless the label is supported. A passport reference on an identity card is not automatically its card number. An emergency-contact name is not the holder's name.

**`backend/app/extractors/label_matcher.py`** — Recognizes captions such as `Surname`, `Given Names`, and multilingual date labels. `LabelMatch` carries the canonical field, any inline value, whether it is additional, printed label, and approximate-match flag. `cached_label_matches()` scopes a caption cache to one scan. `_caption_distance()` uses edit distance for labels only. `_nationality_caption()` and `_multilingual_caption()` handle specialized translated-label cases. `_fold_with_positions()` preserves positions while normalizing for matching. `_damaged_translation()` detects narrow translation damage. `_label_patterns()` caches alias regexes. `_match_start()` and `_match_label()` implement internal matching; `match_label()` is the public cached wrapper. `match_labels()` handles supported multiple-label rows; `is_caption()` tells association code not to treat another label as a value. Fuzzy label recognition does not authorize changing a person's actual name or number.

**`backend/app/extractors/caption_context.py`** — Reconstructs labels split into separate OCR boxes, for example `Date of` plus `Birth`. `_caption_text()` normalizes a working caption copy. `_next_to()` checks geometric adjacency. `_joined()` produces an association-only combined box. `_join_translations()` combines compatible adjacent translated labels when supported separators connect them. `prepare_captions()` coordinates these operations and retains a mapping to original fragments. Its context-based English-suffix recovery is constrained; arbitrary words in a paragraph do not become labels. Original OCR transcript rows remain available.

**`backend/app/extractors/spatial_matcher.py`** — Connects labels to values by geometry. `bounds()` obtains rectangular limits. `_angle()` finds the text baseline angle; `_aligned_bounds()` measures in the label's rotated frame. `_fits_caption()` rejects unsuitable candidate text. `_spatial_scores()` considers right/below placement, alignment, distance, intervening rows, and narrow distant-date rules. `spatial_candidates()` returns plausible nearby candidates, including ambiguity. `competing_labels()` identifies another plausible owner. `name_continuations()` joins eligible aligned wrapped name lines without crossing another caption. `SpatialScores` caches per-label calculations within a scan.

**`backend/app/extractors/document_context.py`** — `DocumentContext` stores a side's kind, supporting headings, and ambiguity. `document_context()` recognizes headings while excluding label values and misleading references. `classify_document()` combines side headings, supported MRZ formats, and narrow layout evidence. It can return `unknown` when sources conflict. A holder's nationality does not establish the document's issuing country.

**`backend/app/extractors/regions.py`** — `contact_regions()` finds explicitly marked emergency-contact/next-of-kin sections and assigns nearby rows to those sections using boundaries and geometry. This prevents a contact's name or number from competing with holder biodata.

**`backend/app/extractors/mrz_parser.py`** — Handles structured machine-readable text. `FORMATS` maps exact line counts/lengths to TD1/TD2/TD3. `check_digit()` computes the implemented repeating 7/3/1 weighted sum modulo ten. `_check()` compares a result with a printed check digit. `_names()` interprets `<` separators. `_document_number()` handles supported extended TD1/TD2 numbers. `_partial_passport()` exposes independently readable fields from a damaged passport MRZ without padding it. `_parse_mrz()` parses fields and validates structure, calendar constraints, and checks. `parse_mrz()` adds bounded, documented lookalike corrections where constraints support them. `detect_mrz()` finds candidate OCR rows; `_adjacent_rows()` checks spatial continuity.

At most four constrained substitutions are accepted, and the resulting structure/checks must pass. The TD3 number-correction exception additionally requires strong independent labeled printed evidence and at most two number lookalikes. Raw and interpreted lines remain separate. Names have no check digit, and MRZ-only two-digit years do not establish centuries.

**`backend/app/extractors/layout_fallback.py`** — A narrow fallback for recognizable Indian passport biodata geometry. `_evidence()` preserves source readings; `_center_y()` measures rows. `indian_passport_candidates()` requires multiple anchors, including country context, partial passport MRZ/name evidence, and spatial layout, before offering candidates. Its nested `candidate()` constructs evidence-bearing fields. This is not a universal passport template detector and does not fill arbitrary missing numbers or dates.

## Backend patterns: shared vocabulary and checks

**`backend/app/patterns/__init__.py`** — Empty package marker.

**`backend/app/patterns/common.py`** — Main/additional label alias dictionaries and country aliases. `fold_text()` normalizes case/marks for matching while callers retain originals. `country_code()` and `known_country_code()` look up supported country wording/codes. `_country_database()` caches reference data from pycountry; `_exact_country_code()` performs exact-code resolution. This file is a common place to extend supported captions, with associated tests.

**`backend/app/patterns/dates.py`** — `DateOrder` describes `auto`, `dmy`, and `mdy`. `MONTHS` contains supported month spellings/abbreviations, including certain bilingual pairs. `normalize_date()` interprets full-year numeric/named dates and returns the original text plus a reason when unresolved. `date_context_warning()` flags future birth/issue dates. `valid_mrz_date()` checks six-digit MRZ calendar syntax without establishing a real person's century. `display_full_date()` formats an established ISO date as `DD-MMMM-YYYY`; `matches_mrz_date()` compares printed full dates with MRZ short years. Validating date syntax and establishing its field role are separate tasks.

**`backend/app/patterns/passports.py`** — `PASSPORT_NUMBER_PATTERNS` holds configured UK/US syntax patterns. `passport_number_matches()` returns true, false, or unavailable depending on support and match. These are formatting checks, not queries to government records or proof of issuance.

**`backend/app/patterns/emirates_id.py`** — `EMIRATES_ID_PATTERN` recognizes supported 15-digit numbers starting with `784`, with permitted separators. `find_emirates_ids()` locates candidates in text; `normalize_emirates_id()` validates a whole value and strips separators. Document/label context still decides the field's meaning. No nationality or birth year is inferred from the digits.

## Frontend build and configuration files

**`frontend/package.json`** — Lists runtime and development packages and npm commands. React is the UI library; GSAP handles animation; Lucide supplies icons; Radix Slot and class utilities support shared controls. `dev` starts Vite; `build` runs TypeScript plus Vite; `test` runs Vitest; `lint` runs ESLint; `typecheck` runs TypeScript; format commands use Prettier.

**`frontend/package-lock.json`** — npm's resolved dependency tree, exact versions, package locations, and integrity data. `npm ci` installs according to it. It contains package metadata, not document scan results. Usually update it through npm when dependencies change.

**`frontend/index.html`** — The initial HTML document. Defines metadata/title/favicon, creates `<div id="root">`, and imports `/src/main.tsx`. React fills that root element.

**`frontend/vite.config.ts`** — Configures React and Tailwind plugins, the `@` alias for `src`, development port 5173, preview port 4173, and `/api` proxying to backend port 8000. Also configures Vitest to use jsdom and `src/test/setup.ts`. The proxy lets browser calls stay on the same origin.

**`frontend/tsconfig.json`** — Top-level TypeScript project references, connecting app and Node-side configuration projects.

**`frontend/tsconfig.app.json`** — Strict compiler settings for browser source under `src`: JSX support, DOM types, ES2022 target, `@/*` alias, unused-variable checking, and test type declarations. `noEmit` means this compiler check does not itself produce the final browser bundle; Vite performs bundling.

**`frontend/tsconfig.node.json`** — TypeScript settings for `vite.config.ts`, using Node types instead of browser application settings.

**`frontend/eslint.config.js`** — ESLint rules for JavaScript/TypeScript, React hooks, and refresh-compatible component exports. Ignores builds/dependencies/coverage. Lint checks code patterns; it does not prove OCR accuracy.

**`frontend/components.json`** — shadcn-style tooling configuration: TSX, style preset, CSS location, aliases, and Lucide icons. This is not a list of runtime document fields or a server setting.

**`frontend/public/favicon.svg`** — Small vector icon displayed in the browser tab. Vite copies public assets into the production output.

## Frontend source: screen, controls, and results

**`frontend/src/main.tsx`** — Finds the HTML `root`, creates a React root, imports global CSS, and renders `<App />` inside `StrictMode`. This is the frontend execution entry point.

**`frontend/src/App.tsx`** — Main page composition. State contains front/back files, options, current side, crop/comparison/help visibility, and highlighted field. It connects `useBackendHealth`, `useScan`, and preview URLs to child components. `changeFile()` clears stale results and resets relevant options; replacing the front clears the old back. `rotate()` updates rotation and invalidates results. `applyCrop()` saves corner coordinates and requires rescanning. `clear()` clears files, options, and results. A page-hide effect clears document state. `canScan` requires a front file, a ready engine, and no running scan. The JSX composes navigation, explanations, upload controls, preview, progress/errors, results, and crop dialog. PDF originals become viewable after backend rendering. This file coordinates UI behavior; it does not run OCR.

**`frontend/src/components/UploadArea.tsx`** — Reusable front/back file picker. `choose()` accepts one supported file, checks MIME type and size, and passes it to `onFile`. A hidden file input supports browsing; drag/drop handlers provide another path. Local state controls drag/error appearance. Existing files expose replace/remove actions. These browser checks improve feedback; backend byte validation remains independent.

**`frontend/src/components/DocumentViewer.tsx`** — Displays original or corrected image, zoom/Fit controls, rotation/crop actions, and field evidence. It uses transferred preview blobs when supplied and has a fetch fallback. An effect resets preview/zoom on scan changes and cancels obsolete fetches. Evidence polygons are drawn in an SVG whose coordinate system matches corrected-image dimensions. Only source boxes for the selected side/type are highlighted. A PDF placeholder explains that scanning renders its page.

**`frontend/src/components/CropEditor.tsx`** — Native modal dialog with four corners. `full` defines normalized image corners. `move()` clamps positions to 0–1. Pointer handlers convert cursor position into normalized coordinates; keyboard handlers allow fine adjustments. Apply sends corners to `App`; reset restores the full rectangle; cancel closes without applying. It chooses coordinates, while Python performs the actual image warp and validates the polygon.

**`frontend/src/components/Progress.tsx`** — Maps backend stages into four readable UI steps: detect/align, read, validate, prepare. `Progress()` identifies the current group and marks earlier steps complete. Accessible status announcements describe real stages; no estimated completion percentage is invented.

**`frontend/src/components/Results.tsx`** — Main result view. `FieldRow()` renders one field, copy button, editing controls, relevant warnings, and source highlighting. It manages editing draft/error/copied state. `Results()` keeps an edits map, derives a reviewed result, separates personal/document fields, shows MRZ, and places diagnostic details in a collapsed panel. `copyText()` uses the browser clipboard. `copyAll`, `copyMRZ`, and `copyOCR` prepare their respective text. `exportJson()` adds English/display labels, creates a JSON Blob, triggers a download through `documentElement()`, then releases the temporary URL. Printed assembled names remain in diagnostics/export; explicitly marked MRZ name assemblies can appear in main results. Editing does not write to a backend database.

**`frontend/src/components/TechnicalDetails.tsx`** — Detailed evidence view: document-type reasons, MRZ check state, interpreted corrections, warnings, printed headings, normalized values, OCR confidence, source side, caption fragments, raw transcript, and reread observations. Absence of MRZ is distinguished from an actual failed MRZ. It displays provided evidence rather than rerunning validation.

**`frontend/src/components/ui/button.tsx`** — Shared `Button` control. `buttonVariants` selects primary/secondary/ghost/outline/destructive styling and normal/small/icon sizing. `asChild` uses Radix `Slot` to apply behavior/styles to a child element. `cn()` merges class names. This prevents every component from implementing its own button styling.

## Frontend hooks, API client, types, and helpers

**`frontend/src/hooks/useScan.ts`** — Scan lifecycle. State holds busy/stage/result/error/previews. Refs hold the active abort controller, known server scan ID, and generation counter. `dispose()` invalidates stale work, aborts requests, and attempts cleanup. `reset()` restores empty state; `cancel()` preserves an explanatory cancellation message. `scan()` creates the request, enforces a 180-second client deadline, polls every 250 ms, displays completed extraction, transfers previews, and attempts server deletion. Raster originals reuse uploaded files; PDFs need rendered originals. A generation comparison prevents late responses from replacing a newer scan. Failed preview transfer does not silently discard already available extraction. Reset/unmount and server expiry provide cleanup fallbacks.

**`frontend/src/hooks/useBackendHealth.ts`** — Backend connection state. Attempts readiness four times, with delays 0/500/1000/2000 ms and a four-second per-request timeout. Differentiates an unreachable backend from a responding service whose OCR is not ready. `reconnect()` increments a generation to rerun the effect. Cleanup aborts active requests and cancels timers.

**`frontend/src/hooks/useObjectUrl.ts`** — Converts a `Blob`/`File` into a temporary `blob:` URL for image display. The effect revokes the previous URL when the file changes or the component unmounts. These URLs are browser resources, not public server image links.

**`frontend/src/hooks/useMotion.ts`** — Optional animation behavior. Lazily imports GSAP, scopes selectors to a root element, respects reduced-motion preferences, and cleans up on rerender/unmount. Supports page/upload/progress/results/highlight/scan modes. A late import after unmount does not start a new animation. Animation failure does not hide document content or block OCR.

**`frontend/src/services/api.ts`** — The single HTTP client layer. `checked()` turns unsuccessful responses into useful errors. `health()` fetches uncached readiness. `startScan()` creates a session, builds `FormData`, and uploads front/back/options. `getScan()` polls; `deleteScan()` uses DELETE with keepalive; `imageBlob()` fetches protected previews. `isAbort()` recognizes request cancellation; `delay()` is an abort-aware timer. All routes use `/api/v1` and same-origin credentials. This is where frontend requests meet backend routes.

**`frontend/src/types/scan.ts`** — TypeScript interfaces/type unions corresponding to backend data: points/corners, rotations, options, evidence, field values/status, OCR lines, MRZ, image metadata, results, stages, jobs, health, and uploads. Includes client-only `user_edited`, `extracted_value`, and export-label metadata. TypeScript types are compile-time descriptions, not runtime validation of arbitrary server JSON; `api.ts` casts responses to these shapes.

**`frontend/src/lib/format.ts`** — `fieldHeading()` chooses readable English headings while preserving distinctions such as first/given/middle/surname and passport/card numbers. `fullDate()` validates and formats established dates. `isMRZDate()` identifies short-year MRZ dates without an established full date. `dateOrderWarning()` explains chronology problems. `displayValue()` chooses appropriate presentation without guessing a century. `copyValue()` includes uncertainty/conflict/assembly/MRZ notes rather than silently exporting a questionable value as verified text.

**`frontend/src/lib/review.ts`** — `editField()` trims input, rejects empty values and invalid/non-ISO date edits, uppercases names, records the original extracted value, retains evidence, marks the field user-edited/uncertain, and removes OCR-confidence claims. `reviewedResult()` overlays edits, invalidates affected agreement checks, and recalculates available date-order comparisons. It returns client-side data used by display/copy/export; there is no server save request.

**`frontend/src/lib/utils.ts`** — Two small helpers. `cn()` combines conditional classes with `clsx` and resolves conflicting Tailwind classes through `twMerge`. `label()` turns snake_case into a readable capitalized phrase. Neither performs extraction.

**`frontend/src/styles/index.css`** — Imports Tailwind and defines theme variables, fonts, page/header/hero layout, upload controls, viewer, crop dialog, progress, fields, MRZ, diagnostic panels, buttons, and review/highlight styling. Media queries adapt layouts to narrow/short/touch viewports and reduced motion. Later rules adjust the comparison panel and review controls; the CSS cascade means later matching rules can override earlier ones. This file changes appearance, not OCR data.

## Every backend test file

Tests state intended behavior. Some assertions predate current code; a test's presence does not mean it currently passes. Helpers named `row`, `line`, or similar construct fictional OCR lines with coordinates. Parametrization runs one test against multiple cases. Monkeypatches/fake engines isolate behavior without invoking a real model.

| File | What its code tests |
| --- | --- |
| `backend/tests/test_api.py` | Uses an injected test OCR engine and API client to check uploads, front/back options, sessions/ownership, image access, deletion, invalid requests, safe errors, cancellation, expiry, and capacity. |
| `backend/tests/test_authorized_samples.py` | Opt-in real pipeline tests using an external `DOCULENS_SAMPLE_MANIFEST`. Compares configured expected fields on original/mildly blurred images and clears storage. It does not bundle a user's private documents. |
| `backend/tests/test_caption_association.py` | First/given/middle/name distinctions, split/translated captions, preserved fragment boxes, cross-side rejection, wrapped names, country semantics, and noisy-heading constraints. |
| `backend/tests/test_date_chronology.py` | Birth/issue/expiry order, pairwise comparisons, unknown/missing dates, and avoiding silent reassignment of values. |
| `backend/tests/test_document_routing.py` | Passport/ID/Emirates ID classification without requiring MRZ, distinct number roles, misleading headings, damaged MRZ, and conflicting document families. |
| `backend/tests/test_extraction.py` | Broad date normalization, aliases, geometric association, ID patterns, conflicts, confidence, MRZ/print interactions, additional fields, names, and retained evidence. |
| `backend/tests/test_field_selection.py` | Print-first selection, retained MRZ conflicts, unreadable evidence, and tightly constrained MRZ fallback using an explicit matching printed year. |
| `backend/tests/test_imaging.py` | Invalid data, EXIF, transparency, size limits, crop/perspective/rotation, ambiguous/multiple boundaries, Hough fallback, manual corners, quality warnings, and non-mutating enhancement. |
| `backend/tests/test_layout_fallback.py` | Required Indian-layout anchors, disagreement handling, uncertain dates, compact-date parsing, and preserving name-field boundaries. |
| `backend/tests/test_medium_models.py` | Missing explicit Medium model rejection, dictionary-order mismatch rejection, and detector-versus-recognizer tensor compatibility. |
| `backend/tests/test_mrz.py` | Check-digit arithmetic, TD1/TD2/TD3 parsing, source preservation, incomplete records, extensions, invalid sex/calendar data, and separation of distant/opposite-side zones. |
| `backend/tests/test_multilingual_printed_fields.py` | Supported Dutch/bilingual dates and labels, agreeing/disagreeing translated month/sex markings, and refusal to promote arbitrary colon text into fields. |
| `backend/tests/test_ocr.py` | OCR output normalization, coordinate rotation, model configuration, dictionary validation, retry evidence, guarded changed readings, and orientation voting. Mostly isolates OCR behavior with test doubles. |
| `backend/tests/test_prd_output.py` | Output normalization: uppercase names with raw preservation, country metadata, date display/ISO values, and unresolved-date expectations. Some older expectations differ from current output behavior. |
| `backend/tests/test_real_ocr.py` | Opt-in real model inference on fictional text/documents: right-angle rotation, Arabic logical text, wrapped names, tilted/blurred documents, and unrecoverable blank pixels. Enabled by `DOCULENS_TEST_REAL_OCR=1`. |
| `backend/tests/test_tilted_fields.py` | Rotated OCR box geometry, parallel columns, name continuations, damaged translated labels, and preserving an invalid inline date rather than stealing a nearby date. |

## Every frontend test/support file

| File | What its code does |
| --- | --- |
| `frontend/src/test/setup.ts` | Loads DOM assertions and cleanup; mocks browser facilities absent/incomplete in jsdom: matchMedia, object URLs, clipboard, and dialog open/close. |
| `frontend/src/test/fixtures.ts` | Fictional health and scan-result objects reused by tests. A sample surname is test data, not the production result-generation mechanism. |
| `frontend/src/test/ApiHealth.test.ts` | Same-origin uncached health requests and unsuccessful proxy responses. |
| `frontend/src/test/App.test.tsx` | Upload/preview/scan/result lifecycle, keyboard/accessibility controls, comparison, failures, cancellation, cleanup, and timeout behavior using mocked APIs. |
| `frontend/src/test/BackendHealth.test.tsx` | Immediate readiness, transient failure recovery, four-attempt bound, manual reconnect, StrictMode cleanup, unmount cancellation, and hung requests. |
| `frontend/src/test/DocumentRouting.test.tsx` | ID results without MRZ, unavailable versus failed MRZ checks, separate printed passport references, and visible date-order warnings. |
| `frontend/src/test/FieldFormat.test.ts` | English headings, date display/copy, MRZ century uncertainty, explicit printed-year fallback, and chronology notes. |
| `frontend/src/test/Motion.test.tsx` | Scoped animation cleanup, reduced-motion behavior, and avoiding animation after unmount. |
| `frontend/src/test/Results.test.tsx` | Fields/MRZ/diagnostics, copy/export, evidence, date/name/ID presentation, empty states, and crop keyboard controls. Several assertions reflect earlier presentation contracts. |
| `frontend/src/test/Review.test.ts` | Retaining original extraction/evidence when editing and rejecting impossible/ambiguous date edits. |

## Every development script

**`scripts/generate_fixture.py`** — Creates fictional passport-like images. `font()` selects available normal/monospaced fonts. `specimen_image()` draws the document outline, specimen notice, fictional fields, and public fictional MRZ example. The command-line block accepts an output path and saves the image. It is a test utility, not a fake production OCR engine.

**`scripts/download_arabic_model.py`** — Downloads the optional Arabic recognizer from a pinned model URL. `download()` verifies an already-installed file or streams into a temporary `.part`, limits size, computes SHA-256, compares the expected digest, then replaces the destination. `finally` removes an incomplete temporary file. The CLI accepts `--output`. It downloads weights; it does not train them.

**`scripts/evaluate_accuracy.py`** — `EXPECTED` defines six fictional field answers. `cases()` produces clear, blurred, reduced-resolution, and tilted variants. `main()` warms OCR, reads each case, extracts fields, compares exact values, records elapsed time and OCR observations, and writes JSON to `--output`. Its results describe those synthetic cases, not universal document accuracy.

**`scripts/compare_ocr_models.py`** — Compares a chosen detector/recognizer pair in a fresh process. `fixture()` draws TD1/TD2/TD3 examples and applies selected distortions; nested `write()` records expected text/boxes. `corrected_boxes()` maps expected regions through image correction. `region_metrics()` matches expected/detected regions by overlap and counts character edits. `main()` selects models, runs six full-pipeline cases plus tilted regressions, compares fields/MRZ, measures timing and Windows peak working set where supported, and writes JSON. S/M report letters mean detector first, recognizer second.

**`scripts/benchmark.py`** — Measures real OCR through an in-process ASGI API client. `percentile()` computes latency percentiles. `main()` creates a fictional JPEG, warms the service, runs repeated scans, exercises concurrent clients, collects timings/version/hardware information and an end-of-run RSS snapshot, and writes a report. Nested `scan_once()` submits/polls/deletes one scan. `context_client()` supplies an independent cookie jar while sharing the app lifespan. The report date is currently hardcoded to 26 October 2026; rerunning it does not automatically correct that date. It is not an internet/network-latency benchmark.

**`scripts/smoke_http.py`** — Tests an already-running server using `httpx`. `main()` generates a fictional image, checks the page/health/session, uploads, polls, checks an expected field and JPEG preview, verifies another session cannot access the scan, then deletes it. `--base` selects the server URL. Unlike `benchmark.py`, this exercises actual HTTP to a running process.

**`scripts/package_project.py`** — `EXCLUDED` lists runtime/generated directories. `package()` traverses the active project and writes a ZIP under a `doculens/` prefix while excluding environments, caches, credentials, models, bytecode, builds, logs, and other specified outputs. The CLI takes the destination and reports file count. This explains why a source archive is smaller than the development workspace.

## Every documentation, measurement, and local asset file

These are descriptions or recorded outputs. The application does not load these reports to generate scan results.

| File | Meaning |
| --- | --- |
| `docs/contract.md` | Internal request/result contract and historical extraction/presentation amendments. Useful background, but incomplete for newer endpoints and metadata. |
| `docs/implementation-review.md` | Historical 17-section implementation/requirement review, verification evidence, and limits. |
| `docs/verification.md` | Dated record of commands/checks, observations, performance, and unverified items. Historical passing counts are not today's test result. |
| `docs/enhancement-2026-10-27.md` | Notes on MRZ, document comparison, connectivity changes, commands, and manual acceptance still needed. |
| `docs/document-routing-review-2026-10-29.md` | Explains passport/ID routing changes and boundaries; explicitly identifies later superseding behavior. |
| `docs/field-association-review-2026-10-29.md` | Explains caption reconstruction, spatial ownership, wrapped names, dates, and verification limits. |
| `docs/prd-implementation-2026-10-31.md` | Product requirement implementation notes covering output, review, PDF/endpoint changes, and unresolved acceptance requirements. Contains the later full-month date display override. |
| `docs/codebase-study-2026-11-02.md` | Previous architecture/source study with module maps, caveats, and the test results recorded on that date. |
| `docs/accuracy-before.json` | Earlier synthetic evaluation: expected fields and four cases with selected fields, exact matches, timing, and OCR evidence. |
| `docs/accuracy-after.json` | Corresponding later synthetic evaluation snapshot. The name does not prove current universal accuracy. |
| `docs/benchmark.json` | Saved benchmark methodology, hardware/package versions, startup/latency/RSS measurements, sample timings, and observed extraction. |
| `docs/ocr-medium-SS.json` | Saved Small detector / Small recognizer comparison, six cases plus tilted regressions. |
| `docs/ocr-medium-SM.json` | Saved Small detector / Medium recognizer comparison. |
| `docs/ocr-medium-MS.json` | Saved Medium detector / Small recognizer comparison. |
| `docs/ocr-medium-MM.json` | Saved Medium detector / Medium recognizer comparison. |
| `docs/tilted-field-comparison.json` | Small recorded before/after-style field-count comparison for synthetic tilted cases; inspect its case data rather than assuming broad coverage. |
| `docs/specimen.png` | Saved fictional document fixture for examples/testing. Not an uploaded-user scan database. |
| `docs/arabic-specimen.png` | Saved synthetic Arabic test image. |
| `models/arabic-synthetic-test.png` | Local synthetic Arabic fixture; its bytes match the documented Arabic specimen in this workspace. |
| `models/arabic_PP-OCRv4_rec_mobile.onnx` | Optional pretrained Arabic recognizer weights, automatically discoverable by `OCRService`. Binary model data, not editable Python source. |

This new `docs/every-file-explained-2026-11-03.md` is the guide you are reading. The appendix records all original project paths and snapshot comparisons.

## Generated and installed files you also see in the workspace

The following categories can contain thousands of files. They are not thousands of separate DocuLens features. Their individual vendor/internal implementations are outside this project-file explanation.

| Location/file | Why it exists and how it is used |
| --- | --- |
| `.venv/` | Isolated Python installation environment. `Scripts/python.exe` runs Python; `Lib/site-packages/` contains installed FastAPI/OpenCV/RapidOCR/etc.; `pyvenv.cfg` identifies environment configuration. |
| `frontend/node_modules/` | Installed JavaScript packages and executable wrappers under `.bin`. Recreated from package manifests/lockfile; app source imports these packages. |
| `frontend/dist/index.html`, `frontend/dist/assets/*`, copied favicon | Generated browser output from `npm run build`. JS/CSS filenames may contain hashes. FastAPI serves this folder in production mode. Edit `src`, then rebuild, rather than editing generated bundles. |
| `frontend/tsconfig.app.tsbuildinfo` | Generated TypeScript build bookkeeping for application compilation. |
| `frontend/tsconfig.node.tsbuildinfo` | Generated TypeScript build bookkeeping for Vite/config compilation. |
| `backend/doculens.egg-info/` | Generated Python package metadata such as `PKG-INFO`, `SOURCES.txt`, `requires.txt`, and package names. It is not document data. |
| `__pycache__/`, `*.pyc` | Python's compiled bytecode caches for imported modules. |
| `.pytest_cache/` | pytest's cached run information, such as collected nodes or failures. |
| `.ruff_cache/` | Ruff's analysis cache. |
| `.uv-cache/` | Python package-manager cache. |
| `frontend/.npm-cache/` | npm package downloads/cache/log material. |
| `.cache/` | Local scratch/test/diagnostic artifacts. Its contents are historical/local material, not the production document store. |
| `.git/` | Version-control objects, refs, index, configuration, and logs. It stores source history/staging metadata. |

The default production scan store is RAM in `core/store.py`. Generated logs, package caches, and test scratch directories must not be confused with a durable application scan database. Local custom Small/Medium OCR bundles on the `D:` drive are external resources, not files inside this project tree; `.env` points to them.

## How to read the code without getting lost

1. Open `frontend/index.html`, `src/main.tsx`, and `src/App.tsx` to see how the page starts.
2. Follow `useScan.ts` into `services/api.ts` to see the outgoing request and polling.
3. Match that request with the route in `backend/app/main.py`.
4. Follow the job into `services/pipeline.py`.
5. Read `schemas/models.py` before the large extraction module so the data structures are familiar.
6. Read `imaging.py`, then the main methods of `ocr.py`.
7. Read `extract_fields()` first, then the smaller matcher/pattern modules it calls.
8. Follow the completed result into `Results.tsx`, `format.ts`, and `review.ts`.
9. Read a nearby test to see a small fictional example of each rule.

Python `def` defines a function; a `class` groups data/behavior; an underscore prefix marks a helper conventionally internal to its module. React props are values passed to a component; state is changing UI data; `useEffect` starts/cleans up work tied to component lifetime; `useRef` retains a mutable reference without itself requesting a rerender. `async`/`await` coordinates waiting for requests, while the backend thread pool runs heavier scan work away from the event loop.

## Verification boundary

This guide is a source explanation, not a new claim of passing tests or measured OCR accuracy. The prior 2 November study recorded 251 backend passes, 20 failures, and 12 deselected cases; frontend results were 52 passes and nine failures. Some failures concern older expectations, but they still need adjudication. Current source, test intent, historical documentation, and observed runtime results are distinct kinds of evidence.

The 120-file coverage and archive comparisons below were checked by filesystem inventory and byte comparison. The guide covers project-owned source/configuration/tests/docs and known local model/fixture assets; it does not claim a line-by-line review of third-party packages or binary model internals.


## Complete snapshot comparison

Each row is one active file already explained above. **Identical** means byte-identical to that snapshot. **Different** means the same path has an earlier/different implementation or content. **Absent** means that snapshot has no corresponding file. Every file in the older folder and ZIP maps to one of these rows. Thus the table also inventories all 86 older files and all 93 ZIP members without implying their code is current.

This table is the retained inventory. The redundant generated `project-file-inventory-2026-11-03.json` was removed during cleanup; the file and function explanations remain in this guide.

| Current file | Older extracted copy | Source ZIP |
| --- | --- | --- |
| [`.dockerignore`](../.dockerignore) | Different | Different |
| [`.env.example`](../.env.example) | Different | Different |
| [`.gitignore`](../.gitignore) | Identical | Identical |
| [`Dockerfile`](../Dockerfile) | Identical | Identical |
| [`README.md`](../README.md) | Different | Different |
| [`backend/.env`](../backend/.env) | Absent | Absent |
| [`backend/app/__init__.py`](../backend/app/__init__.py) | Identical | Identical |
| [`backend/app/core/__init__.py`](../backend/app/core/__init__.py) | Identical | Identical |
| [`backend/app/core/config.py`](../backend/app/core/config.py) | Different | Different |
| [`backend/app/core/middleware.py`](../backend/app/core/middleware.py) | Different | Different |
| [`backend/app/core/security.py`](../backend/app/core/security.py) | Identical | Identical |
| [`backend/app/core/store.py`](../backend/app/core/store.py) | Identical | Identical |
| [`backend/app/extractors/__init__.py`](../backend/app/extractors/__init__.py) | Identical | Identical |
| [`backend/app/extractors/caption_context.py`](../backend/app/extractors/caption_context.py) | Absent | Absent |
| [`backend/app/extractors/document_context.py`](../backend/app/extractors/document_context.py) | Absent | Absent |
| [`backend/app/extractors/field_extractor.py`](../backend/app/extractors/field_extractor.py) | Different | Different |
| [`backend/app/extractors/label_matcher.py`](../backend/app/extractors/label_matcher.py) | Different | Different |
| [`backend/app/extractors/layout_fallback.py`](../backend/app/extractors/layout_fallback.py) | Different | Different |
| [`backend/app/extractors/mrz_parser.py`](../backend/app/extractors/mrz_parser.py) | Different | Different |
| [`backend/app/extractors/regions.py`](../backend/app/extractors/regions.py) | Absent | Absent |
| [`backend/app/extractors/spatial_matcher.py`](../backend/app/extractors/spatial_matcher.py) | Different | Different |
| [`backend/app/main.py`](../backend/app/main.py) | Different | Different |
| [`backend/app/patterns/__init__.py`](../backend/app/patterns/__init__.py) | Identical | Identical |
| [`backend/app/patterns/common.py`](../backend/app/patterns/common.py) | Different | Different |
| [`backend/app/patterns/dates.py`](../backend/app/patterns/dates.py) | Different | Different |
| [`backend/app/patterns/emirates_id.py`](../backend/app/patterns/emirates_id.py) | Identical | Identical |
| [`backend/app/patterns/passports.py`](../backend/app/patterns/passports.py) | Identical | Identical |
| [`backend/app/schemas/__init__.py`](../backend/app/schemas/__init__.py) | Identical | Identical |
| [`backend/app/schemas/models.py`](../backend/app/schemas/models.py) | Different | Different |
| [`backend/app/services/__init__.py`](../backend/app/services/__init__.py) | Identical | Identical |
| [`backend/app/services/imaging.py`](../backend/app/services/imaging.py) | Different | Different |
| [`backend/app/services/medium_models.py`](../backend/app/services/medium_models.py) | Absent | Absent |
| [`backend/app/services/ocr.py`](../backend/app/services/ocr.py) | Different | Different |
| [`backend/app/services/output.py`](../backend/app/services/output.py) | Absent | Absent |
| [`backend/app/services/pipeline.py`](../backend/app/services/pipeline.py) | Different | Different |
| [`backend/pyproject.toml`](../backend/pyproject.toml) | Different | Different |
| [`backend/requirements-lock.txt`](../backend/requirements-lock.txt) | Identical | Identical |
| [`backend/tests/test_api.py`](../backend/tests/test_api.py) | Different | Different |
| [`backend/tests/test_authorized_samples.py`](../backend/tests/test_authorized_samples.py) | Different | Identical |
| [`backend/tests/test_caption_association.py`](../backend/tests/test_caption_association.py) | Absent | Absent |
| [`backend/tests/test_date_chronology.py`](../backend/tests/test_date_chronology.py) | Absent | Absent |
| [`backend/tests/test_document_routing.py`](../backend/tests/test_document_routing.py) | Absent | Absent |
| [`backend/tests/test_extraction.py`](../backend/tests/test_extraction.py) | Different | Different |
| [`backend/tests/test_field_selection.py`](../backend/tests/test_field_selection.py) | Different | Different |
| [`backend/tests/test_imaging.py`](../backend/tests/test_imaging.py) | Identical | Identical |
| [`backend/tests/test_layout_fallback.py`](../backend/tests/test_layout_fallback.py) | Different | Different |
| [`backend/tests/test_medium_models.py`](../backend/tests/test_medium_models.py) | Absent | Absent |
| [`backend/tests/test_mrz.py`](../backend/tests/test_mrz.py) | Different | Different |
| [`backend/tests/test_multilingual_printed_fields.py`](../backend/tests/test_multilingual_printed_fields.py) | Absent | Absent |
| [`backend/tests/test_ocr.py`](../backend/tests/test_ocr.py) | Different | Different |
| [`backend/tests/test_prd_output.py`](../backend/tests/test_prd_output.py) | Absent | Absent |
| [`backend/tests/test_real_ocr.py`](../backend/tests/test_real_ocr.py) | Different | Identical |
| [`backend/tests/test_tilted_fields.py`](../backend/tests/test_tilted_fields.py) | Absent | Identical |
| [`docs/accuracy-after.json`](../docs/accuracy-after.json) | Identical | Identical |
| [`docs/accuracy-before.json`](../docs/accuracy-before.json) | Identical | Identical |
| [`docs/arabic-specimen.png`](../docs/arabic-specimen.png) | Identical | Identical |
| [`docs/benchmark.json`](../docs/benchmark.json) | Identical | Identical |
| [`docs/codebase-study-2026-11-02.md`](../docs/codebase-study-2026-11-02.md) | Absent | Absent |
| [`docs/contract.md`](../docs/contract.md) | Different | Identical |
| [`docs/document-routing-review-2026-10-29.md`](../docs/document-routing-review-2026-10-29.md) | Absent | Absent |
| [`docs/enhancement-2026-10-27.md`](../docs/enhancement-2026-10-27.md) | Absent | Identical |
| [`docs/field-association-review-2026-10-29.md`](../docs/field-association-review-2026-10-29.md) | Absent | Absent |
| [`docs/implementation-review.md`](../docs/implementation-review.md) | Different | Identical |
| [`docs/ocr-medium-MM.json`](../docs/ocr-medium-MM.json) | Absent | Absent |
| [`docs/ocr-medium-MS.json`](../docs/ocr-medium-MS.json) | Absent | Absent |
| [`docs/ocr-medium-SM.json`](../docs/ocr-medium-SM.json) | Absent | Absent |
| [`docs/ocr-medium-SS.json`](../docs/ocr-medium-SS.json) | Absent | Absent |
| [`docs/prd-implementation-2026-10-31.md`](../docs/prd-implementation-2026-10-31.md) | Absent | Absent |
| [`docs/specimen.png`](../docs/specimen.png) | Identical | Identical |
| [`docs/tilted-field-comparison.json`](../docs/tilted-field-comparison.json) | Absent | Identical |
| [`docs/verification.md`](../docs/verification.md) | Different | Identical |
| [`frontend/components.json`](../frontend/components.json) | Identical | Identical |
| [`frontend/eslint.config.js`](../frontend/eslint.config.js) | Identical | Identical |
| [`frontend/index.html`](../frontend/index.html) | Identical | Identical |
| [`frontend/package-lock.json`](../frontend/package-lock.json) | Identical | Identical |
| [`frontend/package.json`](../frontend/package.json) | Identical | Identical |
| [`frontend/public/favicon.svg`](../frontend/public/favicon.svg) | Identical | Identical |
| [`frontend/src/App.tsx`](../frontend/src/App.tsx) | Different | Different |
| [`frontend/src/components/CropEditor.tsx`](../frontend/src/components/CropEditor.tsx) | Identical | Identical |
| [`frontend/src/components/DocumentViewer.tsx`](../frontend/src/components/DocumentViewer.tsx) | Different | Different |
| [`frontend/src/components/Progress.tsx`](../frontend/src/components/Progress.tsx) | Identical | Identical |
| [`frontend/src/components/Results.tsx`](../frontend/src/components/Results.tsx) | Different | Different |
| [`frontend/src/components/TechnicalDetails.tsx`](../frontend/src/components/TechnicalDetails.tsx) | Absent | Different |
| [`frontend/src/components/UploadArea.tsx`](../frontend/src/components/UploadArea.tsx) | Different | Different |
| [`frontend/src/components/ui/button.tsx`](../frontend/src/components/ui/button.tsx) | Identical | Identical |
| [`frontend/src/hooks/useBackendHealth.ts`](../frontend/src/hooks/useBackendHealth.ts) | Absent | Identical |
| [`frontend/src/hooks/useMotion.ts`](../frontend/src/hooks/useMotion.ts) | Different | Different |
| [`frontend/src/hooks/useObjectUrl.ts`](../frontend/src/hooks/useObjectUrl.ts) | Identical | Identical |
| [`frontend/src/hooks/useScan.ts`](../frontend/src/hooks/useScan.ts) | Different | Different |
| [`frontend/src/lib/format.ts`](../frontend/src/lib/format.ts) | Different | Different |
| [`frontend/src/lib/review.ts`](../frontend/src/lib/review.ts) | Absent | Absent |
| [`frontend/src/lib/utils.ts`](../frontend/src/lib/utils.ts) | Identical | Identical |
| [`frontend/src/main.tsx`](../frontend/src/main.tsx) | Identical | Identical |
| [`frontend/src/services/api.ts`](../frontend/src/services/api.ts) | Different | Identical |
| [`frontend/src/styles/index.css`](../frontend/src/styles/index.css) | Different | Different |
| [`frontend/src/test/ApiHealth.test.ts`](../frontend/src/test/ApiHealth.test.ts) | Absent | Identical |
| [`frontend/src/test/App.test.tsx`](../frontend/src/test/App.test.tsx) | Different | Identical |
| [`frontend/src/test/BackendHealth.test.tsx`](../frontend/src/test/BackendHealth.test.tsx) | Absent | Identical |
| [`frontend/src/test/DocumentRouting.test.tsx`](../frontend/src/test/DocumentRouting.test.tsx) | Absent | Absent |
| [`frontend/src/test/FieldFormat.test.ts`](../frontend/src/test/FieldFormat.test.ts) | Absent | Absent |
| [`frontend/src/test/Motion.test.tsx`](../frontend/src/test/Motion.test.tsx) | Identical | Identical |
| [`frontend/src/test/Results.test.tsx`](../frontend/src/test/Results.test.tsx) | Different | Different |
| [`frontend/src/test/Review.test.ts`](../frontend/src/test/Review.test.ts) | Absent | Absent |
| [`frontend/src/test/fixtures.ts`](../frontend/src/test/fixtures.ts) | Identical | Identical |
| [`frontend/src/test/setup.ts`](../frontend/src/test/setup.ts) | Identical | Identical |
| [`frontend/src/types/scan.ts`](../frontend/src/types/scan.ts) | Different | Different |
| [`frontend/tsconfig.app.json`](../frontend/tsconfig.app.json) | Identical | Identical |
| [`frontend/tsconfig.json`](../frontend/tsconfig.json) | Identical | Identical |
| [`frontend/tsconfig.node.json`](../frontend/tsconfig.node.json) | Identical | Identical |
| [`frontend/vite.config.ts`](../frontend/vite.config.ts) | Identical | Identical |
| [`models/arabic-synthetic-test.png`](../models/arabic-synthetic-test.png) | Absent | Absent |
| [`models/arabic_PP-OCRv4_rec_mobile.onnx`](../models/arabic_PP-OCRv4_rec_mobile.onnx) | Absent | Absent |
| [`scripts/benchmark.py`](../scripts/benchmark.py) | Different | Different |
| [`scripts/compare_ocr_models.py`](../scripts/compare_ocr_models.py) | Absent | Absent |
| [`scripts/download_arabic_model.py`](../scripts/download_arabic_model.py) | Identical | Identical |
| [`scripts/evaluate_accuracy.py`](../scripts/evaluate_accuracy.py) | Different | Different |
| [`scripts/generate_fixture.py`](../scripts/generate_fixture.py) | Identical | Identical |
| [`scripts/package_project.py`](../scripts/package_project.py) | Identical | Identical |
| [`scripts/smoke_http.py`](../scripts/smoke_http.py) | Identical | Identical |
| [`start.ps1`](../start.ps1) | Identical | Identical |
