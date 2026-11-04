> Latest user override: established DOB, issue and expiry dates display and copy as DD-MMMM-YYYY (for example 25-March-2005). API value and normalized_value remain YYYY-MM-DD; raw observed text remains unchanged.

# PRD implementation review — 31 October 2026

Source: the user-supplied `PRD Passport & ID OCR Extraction System.docx`, dated 31 October 2026. Active source is `DOCULENS/doculens`; the packaged `DocuLens-source` copy was not changed. This document supersedes the date-format and source-priority descriptions in the October 29 reviews.

## Implemented changes

| PRD area | Implementation |
| --- | --- |
| Standard output | `services/output.py` normalizes names to uppercase, established dates to ISO YYYY-MM-DD, and Emirates IDs to 3-4-7-1 groups. Raw text and evidence remain separate. Unknown full dates are null with uncertainty; no century is guessed. |
| Country data | Local pycountry lookup supplies ISO alpha-3 codes and country names separately from observed nationality wording. Unknown/special codes remain uncertain rather than being invented. |
| MRZ priority | A structurally valid MRZ with passing applicable checks takes priority on disagreement, with a conflict flag and retained printed evidence. Matching printed full-year dates still supply the century. Names themselves are not check-digit verified. |
| MRZ OCR confusions | At most four replacements in compulsory numeric date/check positions, accepted only if all structure/checks pass. No arbitrary number/name substitutions or character completion. Raw lines, raw checks, raw fields, interpreted lines and changes are separate. Changes stay uncertain. |
| Labels | Existing multilingual/spatial logic retained. RapidFuzz replaces the duplicate handwritten edit-distance routine. Label fuzziness never alters a person's value. |
| Difficult images | Existing perspective, contrast, bounded regional retries retained. Weak recognition can compare 90/180/270 degrees; clear reads avoid those passes. Rotated results retain matching image coordinates. |
| PDF | One page per uploaded side, rendered in memory using PDFium with a bounded raster allocation and a render lock. Multi-page/encrypted/damaged files produce a readable error. Rendered originals support the existing crop workflow after the first scan. |
| API | New POST `/api/v1/extract` accepts multipart `file` and optional JSON `options`, using the same queue/worker and validation. Returns uppercase document type and complete result. 415 unsupported, 422 unreadable, 429 capacity/rate limits, 504 deadline. Session creation is still required. |
| Existing API | `/api/v1/scans` remains for cancellable progress and original/corrected image review. No existing endpoint was deleted. |
| UI | Existing branding, colors and two-panel structure retained. Per-field confidence indicators, accessible edit/save/cancel controls, original-value preservation, and hover/focus evidence highlighting added. Copy and export use reviewed values. |
| Animation | Existing lazy/scoped GSAP retained; scan and evidence highlights use the same reduced-motion-aware cleanup. |
| Privacy | Processing remains local. No cloud calls or disk document storage. One-shot extract deletes its job on completion/error/cancellation. Existing UI previews expire from RAM. POST rate limits added; secure cookies and an HTTPS-required setting are available for deployment. |

## Explicit limits and unresolved requirements

- The PRD does not specify an authoritative Emirates ID checksum algorithm. Pattern validation is implemented; `id_check_digit` remains null. A checksum must not be fabricated or advertised as passed. An authoritative algorithm/test vector source is needed for that part.
- HTTPS certificates/hostname were not supplied. Local development remains HTTP on loopback. For production terminate TLS at a trusted reverse proxy, restrict forwarded-header trust and frontend origins, set `DOCULENS_REQUIRE_HTTPS=true` and `DOCULENS_COOKIE_SECURE=true`. TLS deployment has not been performed.
- PDFs are explicitly single-page per side, since multi-page handling remains an open question in the PRD. There is no silent first-page-only extraction.
- ISO has country names, not a comprehensive multilingual nationality/demonym dictionary. Existing explicit nationality aliases remain; unknown text is preserved for review.
- MRZ-only two-digit years do not establish a century. A full ISO date requires supporting printed evidence or a manual edit. Formatting is not an excuse to guess a year.
- Manual edits are marked as user-entered and are not machine-verified; original OCR confidence is not assigned to edited values. Date edits require ISO calendar dates. Source-agreement checks are invalidated after edits.
- Automatic correction covers compulsory numeric MRZ positions, not arbitrary confusions inside alphanumeric document numbers or names.
- Performance and accuracy targets (including 99/95/85 percent and 5/8 seconds) are unmeasured. Four-direction recovery is bounded but may increase latency on difficult inputs. Severe blur and unfamiliar scripts/layouts remain limitations.

## Verification and acceptance

Executed: dependency installation into the existing virtual environment, Python source syntax parsing, TypeScript compilation, frontend production build, and whitespace diff checks. An initial typecheck found an HTMLElement annotation error in an earlier regression file; it was corrected. Automated tests, OCR sample runs and browser/device acceptance were not performed. Browser automation was unavailable in this session. No passport accuracy improvement is claimed.

Regression definitions added/updated for ISO output, source selection, country metadata, unknown full dates and manual editing. They are not reported as passing until run.

Manual acceptance after restarting the backend:

1. Scan a clear passport and compare all field labels, raw values and ISO dates; compare a conflicting MRZ and printed field and inspect both sources.
2. Scan a moderately blurred image and a rotated image. Confirm uncertainty is retained and highlight boxes align with the corrected preview.
3. Scan an Emirates ID without MRZ. Check its number grouping and that nationality is separate from issuing country.
4. Upload a single-page PDF, scan, compare the rendered page, rotate and crop. Confirm multi-page PDF rejection is explicit.
5. Edit a field using the keyboard, save/cancel, copy and export. Verify edits and original evidence both remain in JSON; impossible dates are rejected.
6. Check desktop/mobile panels, touch zoom, focus highlighting, reduced motion and cancellation.
7. Start a session then call `/api/v1/extract` with `file` and `options`. Check unsupported/unreadable/timeout responses and absence of retained one-shot previews.

References used for library integration: [pycountry](https://github.com/pycountry/pycountry) and [PDFium Python API](https://pypdfium2.readthedocs.io/en/stable/python_api.html).
