> Historical review. Date formatting and MRZ selection rules are superseded by [the 31 October PRD implementation](prd-implementation-2026-10-31.md).

# DocuLens field-association implementation review

Date: 29 October 2026. Working source: `DOCULENS/doculens`. The packaged `DocuLens-source` directory was not edited.

The subsequent passport/Emirates ID and optional-MRZ changes are documented separately in [Document routing review](document-routing-review-2026-10-29.md). That follow-up also remains unverified at runtime.

## Scope and verification boundary

This work changes the existing local extraction and presentation implementation. React/TypeScript, FastAPI, RapidOCR/ONNX, image preparation, upload/crop controls, cancellation, and local storage remain in place. No dependency, endpoint, cloud service, external upload, or database was added.

Verification was source inspection and Git diff/whitespace review only. Automated tests, OCR scans, browser acceptance checks, lint, typecheck, build, and application-server startup were **not run**. Regression cases were added but are unexecuted. Nothing in this report is a measured accuracy improvement or a claim that the manager's documents now pass.

## Confirmed by source inspection

| Finding before this change | Implemented change |
| --- | --- |
| `First name` aliases produced `given_names`, losing the printed distinction. | Explicit first-name captions now produce `first_name`; given, middle, surname and generic name captions remain separate. |
| Country-code captions and issuing-country captions shared one field key. | Printed code captions now produce `country_code`; issuing-country wording remains `issuing_country`. Nationality has its own source and normalization. |
| English labels after unrecognized Latin/noisy translated prefixes had no geometry-aware fallback; separate caption fragments were processed independently. | Added bounded adjacent-fragment reconstruction and a contextual English-caption fallback. |
| Name continuation could skip unrecognized intervening text because it only treated recognized labels as boundaries. | Intervening text in the association corridor blocks both ordinary association and name continuation. Wrapped names also require closer spacing and comparable text height. |
| Combined-row parsing searched for additional captions inside values without consistently requiring a delimiter. | One-box field splits now require explicit caption/value punctuation or field separators. Separate boxes use geometry. |
| Printed/MRZ name comparison removed all spaces, allowing differently divided names to appear equivalent. | Comparison retains existing word boundaries while allowing accent and punctuation representations; original spelling is unchanged. |
| Automatically assembled full names appeared among primary fields and copied results. | Derived names remain marked `assembled` in diagnostics and JSON, outside the primary printed fields and Copy fields output. |
| Main heading formatting flattened some name-label distinctions. | Clean English headings distinguish Name, Full Name, First Name, Given Name(s), Middle Name(s), Family Name and Last Name when established by the printed caption. Original captions remain visible in Technical details. |

These are confirmed code paths, not proof that each path caused each reported sample failure. Recognition errors, missed or merged boxes, stamps, and crop/orientation failures remain possible causes requiring actual scan evidence.

## Association and fallback rules

| Field | Association and fallback |
| --- | --- |
| Name / Full Name | Direct printed caption. No splitting into surname/first/middle. A generic Name heading remains Name. Explicit surname translations can disambiguate a multilingual surname caption; generic Name/Nom alone does not establish surname. |
| Given names | Printed given-name caption or MRZ given-name position. Multiword values remain intact. |
| First name | Explicit printed first-name caption. MRZ given names can cross-check printed first/middle components but are not copied wholesale into First Name or split to manufacture components. |
| Middle names | A separately recognized printed middle-name caption. No automatic splitting of given names. |
| Surname / family / last name | Printed caption or MRZ surname position; not the last word of a full name. |
| Nationality | Printed nationality caption or MRZ nationality position only. Printed wording is retained; supported code normalization is separate. No name, birthplace, language or issuer inference. |
| Issuing country / country code | Separate printed fields. MRZ issuing-state code cross-checks the matching code field and any separately observed issuing-country wording. Supported aliases are compared without changing either printed string. |
| Passport / ID / personal / optional numbers | Existing distinct label keys and MRZ positions. Leading zeros and observed characters remain; no O/0 or I/1 correction. Optional MRZ data is not relabeled personal number without evidence. |
| DOB / issue / expiry | Own printed caption and spatial association, followed by calendar parsing. MRZ supplies DOB/expiry only. Issue date is not derived from MRZ. |

Existing selection remains field-specific: clearly associated printed readings outrank conflicting MRZ; checked MRZ may resolve weaker printed numeric evidence, with the mismatch retained. Equally supported conflicting readings remain unresolved. OCR confidence alone does not settle a conflict. Missing or incomplete MRZ does not suppress printed extraction.

MRZ raw lines remain separate from parsed fields. Existing exact-length, alphabet and checksum handling was inspected, not rewritten in this change. Name transliteration/truncation differences remain reviewable rather than forcing printed spelling into MRZ spelling. Checksums are transcription checks, not verification of names or identity.

## Bilingual and split captions

`caption_context.py` joins at most three adjacent caption fragments that form a supported caption. Fragments must share a side, baseline direction and similar text size; multiple plausible adjacent fragments are not arbitrarily selected. The joined box stays in the same corrected-image coordinate system.

The noisy-prefix fallback accepts a clear English caption at the end of a short heading only when nearby recognized fields and a larger aligned value below support the interpretation. It does not globally search arbitrary value text for label substrings. Such associations remain uncertain because the prefix was not recognized reliably.

Unrecognized translation fragments after a name caption separator are not accepted as inline name values. An explicit colon can still establish a value. Supported non-English aliases continue to work.

The original OCR lines are unchanged by caption reconstruction. Evidence includes the original heading and additive `label_fragments` with each source fragment's text and coordinates. Reconstruction is used for association, not to create recognized identity text.

## Wrapped names, blurred images and coordinates

Wrapped names require close aligned rows with comparable size, compatible characters, and no competing caption or intervening text in their corridor. A small missed caption is still a boundary even if it cannot be translated. There is no nationality/country-word blacklist for personal names.

The existing image-correction and regional crop transformations were inspected. No new coordinate defect was established by inspection, so they were not changed. Original-first OCR, bounded contrast/detection recovery, up to six regional rereads with two variants, and preserved alternative readings remain in place.

The OCR retry prioritization now uses the same reconstructed caption associations as final extraction. Split captions can therefore identify important regions for the existing retry budget. No extra unbounded passes or generated text were introduced. Severe blur, an entirely absent caption, or a background annotation resembling a field can still require review.

## Dates, copy and export

The existing date parser and formatter were inspected and retained. Established full dates use `DD-MMMM-YYYY`, including a two-digit day, full English month and four-digit year. Results and copy use the same frontend formatter; JSON export also uses that display function.

The representations remain explicit:

- `observed_value`: selected source reading before normalization.
- `normalized_value`: established ISO date (`YYYY-MM-DD`), when available.
- `display_value`: `DD-MMMM-YYYY` when established; otherwise the source reading.
- `value`: existing machine-value role.
- `validation`, `reason`, `evidence`: calendar/order checks, source conflicts and alternatives.

Numeric order uses the explicit setting or reliable evidence. The UI's existing day-first default and user-selectable order remain. An MRZ-only YYMMDD value does not establish a century. Invalid or ambiguous dates are not silently swapped, rewritten or assigned a four-digit year. Chronology warnings do not modify the observed date.

## Files changed in this turn

| File | Purpose |
| --- | --- |
| `backend/app/extractors/caption_context.py` | New association-only caption reconstruction and contextual fallback. |
| `backend/app/extractors/label_matcher.py` | Translation separators, explicit first-name distinction, uncertain name-caption fragments, bounded combined-row splitting. |
| `backend/app/patterns/common.py` | Separate first-name and country-code aliases. |
| `backend/app/extractors/spatial_matcher.py` | Intervening-row barriers, wrapped-name constraints and country-code value type. |
| `backend/app/extractors/field_extractor.py` | Caption evidence, separate field semantics, printed/MRZ component comparison, meaningful name boundaries, issuer/code comparison. |
| `backend/app/services/ocr.py` | Reuse caption associations for existing bounded retry selection and caption counting. |
| `backend/app/schemas/models.py` | Additive typed caption-fragment evidence. |
| `frontend/src/lib/format.ts` | English heading distinctions; existing shared date formatting retained. |
| `frontend/src/components/Results.tsx` | Keep derived names out of primary fields and copy; retain them in export/diagnostics. |
| `frontend/src/components/TechnicalDetails.tsx` | Original printed headings, caption fragments and explicitly derived names. |
| `frontend/src/types/scan.ts` | Additive fragment-evidence type. |
| `backend/tests/test_caption_association.py` | Synthetic regression cases, not executed. |
| `backend/tests/test_layout_fallback.py` | Update one first-name key expectation, not executed. |
| `frontend/src/test/FieldFormat.test.ts` | Heading/date/copy regression cases, not executed. |

Earlier uncommitted changes were preserved. The above list describes this turn rather than attributing every existing Git modification to this work. Corrected `first_name` and `country_code` keys are used where those captions are printed; response containers and endpoints remain unchanged. Consumers that assumed every first-name caption used `given_names`, or every printed code used `issuing_country`, should use the distinct keys. The frontend still understands older given-name entries bearing a First Name caption.

## Remaining confirmation

The previously supplied Swiss, Czech, Emirates ID and two-page passport examples remain available locally; they were not rescanned in this task. No additional personal documents are needed just to continue source analysis. The supplied examples are useful for checking multilingual captions, column separation, wrapped names, contact sections and MRZ differences when sample execution is authorized.

To confirm a manager-specific failure, the useful evidence is the actual failing original, crop/rotation settings if used, that scan's JSON including OCR boxes, verified expected field associations, and intended numeric order. This is validation evidence, not a request to hardcode those documents or a claim that supporting a few samples covers every layout.

Unverified areas include end-to-end extraction, type/lint/build checks, actual OCR quality and latency, mobile/browser rendering, all other languages and layouts, and performance of the new heuristics on representative clear/blurred samples. No runtime success or accuracy percentage is claimed. A backend process without automatic reload must be restarted by the user before new scans use the Python changes.
