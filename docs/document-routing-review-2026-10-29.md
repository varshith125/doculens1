> Historical review. Date formatting and MRZ selection rules are superseded by [the 31 October PRD implementation](prd-implementation-2026-10-31.md).

# Passport and Emirates ID routing review

Implemented in the existing `DOCULENS/doculens` source on 29 October 2026. The packaged `DocuLens-source` copy was not changed. Processing remains local; no cloud OCR, external identity upload, new dependency or database was introduced.

## What the reference description means for DocuLens

The existing application reads images with local OCR, extracts printed (VIZ) fields and separately parses supported MRZ layouts. These are complementary paths: a missing, cropped or unreadable MRZ must not prevent extraction of readable printed fields. An Emirates ID image does not become a passport merely because it contains a passport-number field.

ICAO publishes separate specifications for TD3 passports, TD1/TD2 official travel documents and electronic chip data. This change preserves the existing TD1/TD2/TD3 parser; it is not a claim of complete ICAO conformance. [ICAO Doc 9303](https://www.icao.int/publications/doc-series/doc-9303)

The UAE government describes Emirates ID as an identity card with a 15-digit identity number. Its classification and the readability of a particular number are different questions. No DOB is inferred from the number. [UAE government overview](https://u.ae/en/information-and-services/visa-and-emirates-id/emirates-id), [Emirates Identity Authority statement via WAM](https://www.wam.ae/en/article/hszjujia-emirates-id-the-number-may-not-amended-and-does)

NFC/RFID chip reading is a separate hardware and protocol capability. DocuLens still reads the photographed page of an e-passport, not its chip. Automatic portrait/signature extraction and chip authentication were not implemented in this focused change. The supplied vendor reference likewise treats VIZ, MRZ and NFC as separate sources. [NFC reference](https://ocrstudio.ai/blog/zero-trust-india-passport-scanner-nfc-chip-reading-and-advanced-on-device-id-ocr-designed-for-real-world-conditions/)

## Confirmed source-code problems and fixes

| Confirmed code path | Change applied |
| --- | --- |
| Emirates ID classification required an ID-number field with `detected` status. An uncertain or missing number could lose the specific card type. | Document type now uses observed document headings independently of number validity or MRZ availability. |
| Generic ID Number became Emirates ID Number only after successful numeric normalization. An OCR error changed the field's identity. | On a recognized Emirates ID side, the ID Number heading maps consistently to `emirates_id_number`, including unreadable/uncertain values. Observed digits and uncertainty are retained. |
| A global search for the word passport could classify an ID card with a passport reference as a passport. | Only supported document-title phrases count as title evidence. Number captions, instructions and values associated with other fields do not count as titles. |
| Country wording in a nationality value could supply UAE classification context. | Inline captions and spatially associated values are excluded from document-heading evidence. Nationality never determines the document issuer. |
| The unlabeled Emirates number-pattern fallback could reuse a separately labeled card number. | Pattern recovery checks competing caption ownership and only accepts an entire standalone number row in Emirates ID context. Unlabeled pattern candidates remain uncertain. |
| A card MRZ's document number could compete with a separately printed passport number. | Those readings remain separate: `mrz_document_number` versus the printed passport field. Card, personal and Emirates ID numbers retain their existing independent keys. |
| An unrelated TD3 passport MRZ could populate identity-card fields. | With established identity-card headings, such a zone is kept in raw/parsed MRZ evidence with a warning but is not merged into card fields. Passport-only layout fallback is also skipped on established IDs. |
| Diagnostics treated a missing MRZ as “Review needed.” | No raw MRZ now means validation was not performed. Actual failed MRZ checks still request review. |

Printed fields were already extracted before MRZ processing; there was no general requirement that every scan contain an MRZ. That working behavior was retained rather than replaced.

## Result behavior

- **Emirates ID without MRZ:** show readable printed name, nationality, DOB, ID number, issue/expiry and supported back-side fields. Show “MRZ not available”; no failed-MRZ badge. A damaged ID number remains under Emirates ID Number with uncertainty.
- **Other identity card without MRZ:** retain printed details without passport-only number validation.
- **Passport without MRZ:** keep printed passport details; no invented MRZ data.
- **Supported MRZ present:** keep raw lines visible, retain structure/checksum results, and compare supported fields with printed evidence. No O/0 repairs or MRZ-only century inference were added.
- **Incomplete MRZ:** preserve the recognized lines and readable VIZ fields; do not fill missing MRZ characters.
- **Different printed document types across uploads:** use an unknown type with a review explanation instead of forcing passport validation.
- **Dates:** the existing shared DD-MMMM-YYYY display/copy behavior remains. Raw observed text, normalized ISO dates and display strings stay separate in JSON.

New `document_type_reason` and `document_type_evidence` metadata record why classification was selected. Main headings use clean English; the title spells Emirates ID correctly. A passport-number caption on an ID is still presented as Passport Number, while the card MRZ number is labeled MRZ Document Number.

## Files changed

- `backend/app/extractors/document_context.py`: new shared heading-based classification.
- `backend/app/extractors/field_extractor.py`: consistent ID-number mapping, guarded pattern fallback, MRZ/printed number separation, classification metadata, passport-layout guard.
- `backend/app/schemas/models.py` and `frontend/src/types/scan.ts`: additive classification metadata.
- `frontend/src/lib/format.ts`: distinct passport and MRZ document-number headings on IDs.
- `frontend/src/components/Results.tsx`: document titles and absent-MRZ explanation.
- `frontend/src/components/TechnicalDetails.tsx`: separate unavailable, failed and successful MRZ validation states.
- `backend/tests/test_document_routing.py` and `frontend/src/test/DocumentRouting.test.tsx`: synthetic regression cases, **not executed**.

## Verification and remaining limits

Performed source inspection and `git diff --check`. No automated tests, OCR scans, builds, typechecks, browser acceptance checks, server startup or restart were performed, in accordance with the existing instruction. Existing edits were preserved. The regression cases cover no-MRZ IDs/passports, damaged/missing ID numbers, unrelated passport references, number separation, nationality-versus-issuer evidence, incomplete/incompatible MRZ and conflicting titles.

These are implemented code corrections, not measured extraction results. Available user samples were not rescanned. Unsupported or unreadable document titles can still leave the document type unknown while readable labeled fields remain available. Classification is not authenticity verification. Matching arbitrary unrelated documents uploaded as front/back is not guaranteed, and manual review remains necessary for conflicting evidence. Existing older tests were not comprehensively reconciled with all prior-turn behavior changes.

Manual acceptance after restarting the backend: scan an ID front with no MRZ; repeat with its back; scan a clear passport; then repeat with an incomplete MRZ crop. Check that printed fields remain available, number headings are distinct, established dates use DD-MMMM-YYYY in display/copy/export, and only actual MRZ evidence receives validation results.
