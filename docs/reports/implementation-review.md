# Existing-project enhancement: 17-section review

27 October 2026. This review covers the user's pasted 17-section specification. The React/FastAPI architecture, local OCR models, branding, upload/crop flow and existing endpoints are retained.

The subsequent [MRZ, comparison and backend-connectivity refinement](enhancement-2026-10-27.md) preserves this implementation and supersedes the earlier results-layout details. MRZ is now immediately visible, diagnostics share one collapsed area, and startup health checks recover automatically within a bounded retry window.

## Root causes addressed

- Wrapped names were treated as competing readings when adjacent OCR boxes overlapped. Geometry now joins aligned continuation rows, with every original evidence record retained.
- Multilingual captions and wide bilingual labels could be mistaken for values or point to the wrong row. Caption matching and spatial associations now account for those layouts.
- The highest OCR score previously won every conflict, including an incorrect MRZ reading competing with clear labeled print. Selection now gives clear labeled print priority and keeps the discrepancy visible. Checksummed MRZ can assist when print is uncertain. Scores never establish correctness.
- Large supplied photographs exceeded the former pixel limit; distant passport booklets also needed conservative crop detection. Inputs now accept up to 40 megapixels with bounded processing dimensions. Small-image guards avoid cropping away the header/MRZ.
- Blurred captions caused raw text to replace all structured results. A narrowly anchored Indian passport layout fallback can associate readable text when captions fail, but remains uncertain and does not invent names, dates, nationality or hidden numbers.

## Requirement coverage

| Section | Implemented behavior and evidence | Limits |
| --- | --- | --- |
| 1. Accurate extraction | Actual local OCR, preserved raw observations, conservative normalization and per-field status. Authorized sample comparisons exercise the complete pipeline. | Five images are a regression set, not a population accuracy estimate. |
| 2. Clear-document bugs | Wrapped names, multilingual captions, centered dates, high-resolution handling and print/MRZ selection fixed. Three U.S. samples and the Emirates ID match the checked field values. | A correct selected field can still have conflicting MRZ evidence. |
| 3. Difficult images | Quality metrics, EXIF/orientation handling, perspective correction, selective contrast correction and bounded regional rereads. Clear images bypass contrast enhancement. | Severe blur, glare and masking cannot be reliably reversed. |
| 4. International documents | Existing label aliases and TD1/TD2/TD3 support retained. Passport-number rules are applied only after passport classification. Emirates ID has its own pattern. | No universal layout/script support claim; Arabic remains experimental. |
| 5. Names | Full names are never automatically split. Given/first, middle and surname/last components remain separate, with recognized English printed captions retained. Wrapped rows join in order. | Assembled full names are identified in source details; unreadable components are not guessed. |
| 6. Personal data | Direct label association, country-aware passport patterns and preserved ID/number strings. Confusable characters are not silently substituted. | Pattern matches do not prove the OCR value or document is genuine. |
| 7. Dates | Explicit DMY default, optional MDY/auto, calendar/order checks, ISO JSON and DD/MM/YYYY display/copy. Original text remains in evidence. | MRZ-only dates retain YYMMDD; no century is guessed. |
| 8. MRZ | Line order, length, alphabet, field/composite check digits and format checks; mismatches retained. | Names have no check digit; OCR can still misread them. Incomplete MRZ is never completed artificially. |
| 9. Classification/confidence | Document classification gates document-specific validation. Candidates, evidence and selection reasons remain traceable. | OCR confidence is uncalibrated and stays out of primary results. |
| 10. Results | Supported fields and headings first; Read/Verify/Different readings/Unreadable states. Raw OCR, scores and alternatives are collapsed optional details. | An unmatched transcript is retained with an actionable message, not guessed field headings. |
| 11. Performance | Reused ONNX sessions, bounded images and at most six regional retry candidates; background processing and cancellable polling. | Historical benchmark figures are not new performance guarantees; native inference cannot be forcibly interrupted mid-call. |
| 12. UI | Existing branding/layout preserved; improved result typography, contrast, wrapping, supporting text and error presentation. | Visual browser/device inspection remains outstanding. |
| 13. GSAP | Real GSAP dependency, lazy-loaded page/upload/progress/result motion. Scoped matchMedia lifecycle respects reduced motion and reverts on change/unmount. Tests cover cleanup and late imports. | Main content never waits for the animation chunk; no animation completion gates scanning. |
| 14. Accessibility | Keyboard skip link, focus outlines, error associations, live status, existing keyboard crop controls, mobile single-column results and larger touch controls. | DOM/keyboard tests passed; physical-device, screen-reader and full contrast audits are not claimed. |
| 15. Maintainability | Targeted extractor, schema and hook changes. Additive optional metadata retains canonical API field keys. Lint, strict TypeScript and build checked. | Existing architecture retained rather than replaced. |
| 16. Errors/privacy | File/pixel limits, corrupt-image handling, safe errors, cancellation/timeout cleanup, session ownership and RAM retention preserved. Private samples are excluded from source exports. Frontend dependency audit cleared. | Intended local service; public deployment still needs deployment-specific authentication/HTTPS review. |
| 17. Acceptance | Automated parser, imaging, real OCR, private sample, API and frontend tests; lint/typecheck/build; source package refreshed. | Manual browser/device acceptance is pending; no 100% accuracy claim. |

## Reproducing authorized sample checks

`backend/tests/test_authorized_samples.py` accepts `DOCULENS_SAMPLE_MANIFEST`, a local JSON list of objects with `id`, `image` (absolute path) and `expected_fields`. Keep real documents and expected identity values outside source control. Expected fields must be independently read from the original, not copied from OCR output. The test compares serialized final fields; failures identify field names without printing identity values. It clears the test scan store after each case.

Set `DOCULENS_TEST_REAL_OCR=1` to include the generated-image ONNX tests. The supplied blurred/masked image checks that the unavailable passport number stays empty; it does **not** establish correct extraction of all its blurred fields.

## Motion implementation reference

The scoped lifecycle follows the official [GSAP matchMedia documentation](https://gsap.com/docs/v3/GSAP/gsap.matchMedia/). The animation chunk is loaded separately; import failures leave the interface usable. Existing CSS animations also respect `prefers-reduced-motion`.

See [verification.md](verification.md) for the final executed checks and historical measurements. No application servers were started during this enhancement, as requested.
