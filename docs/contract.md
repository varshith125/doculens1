# Internal API contract

Same-origin `/api/v1`; Vite proxies to port 8000. `POST /session` creates an HttpOnly cookie (no credentials in JS); use `credentials: 'same-origin'`. GET `/health` public. POST `/scans` multipart `front` required, `back` optional, `options` JSON string optional. Options `{front:{rotation:0,corners:null},back:{rotation:0,corners:null},language:'latin'}`. Rotation clockwise 0/90/180/270; corners normalized [x,y] four points TL,TR,BR,BL relative to the original EXIF-corrected image BEFORE rotation. Language latin or arabic (optional model availability from health).

POST returns 202 `{scan_id,status:'queued',stage:'queued'}`. GET `/scans/{id}` polls actual stages: queued, detecting_document, correcting_alignment, reading_text, validating_fields, preparing_results, completed, failed. Response `{scan_id,status,stage,result:null,error:null,previews:[]}`; completed `result` is ScanResult below. The completed (or failed) reply is delivered once: it carries `previews` `[{side,variant:'original'|'corrected',jpeg_base64}]` (the original only for PDF uploads) and the scan is deleted immediately afterwards. DELETE `/scans/{id}` cancels/deletes. API errors `{detail: 'safe message'}`. Cookie protects all scan endpoints. Images fetched as blobs via GET `/scans/{id}/image?side=front&variant=corrected` (variant original/corrected; side front/back). No public image URLs. Results expire after 15 minutes.

ScanResult `{scan_id,status:'completed',document_type,issuing_country,fields:Record<string,FieldValue>,mrz:MRZResult,other_fields:FieldValue[],warnings:string[],images:ImageResult[],ocr_lines:OCRLine[],timings_ms:Record<string,number>}`.

FieldValue `{field_name,value:string|null,status:'validated'|'detected'|'uncertain'|'conflicting'|'not_detected',confidence:number|null,source:string|null,bounding_box:number[][]|null,reason:string|null,evidence:Evidence[]}`.
Evidence `{source:'visual'|'mrz'|'pattern',raw_text:string,side:'front'|'back',confidence:number|null,bounding_box:number[][]|null}`.
OCRLine `{text:string,confidence:number,bounding_box:number[][],side:'front'|'back'}` (boxes in corrected image pixels).
MRZResult `{detected:boolean,format:string|null,raw_lines:string[],checksum_valid:boolean|null,checks:Record<string,boolean|null>,fields:Record<string,string>,warnings:string[]}`.
ImageResult `{side:'front'|'back',width:number,height:number,corners:number[][],crop_applied:boolean,rotation:number,quality:Record<string,number>,warnings:string[]}`; corners normalized to original image, before rotation.

Health `{status:'ok'|'degraded',ocr_ready:boolean,languages:string[],retention_seconds:number,max_upload_mb:number,version:string,optional_engines:Record<string,boolean>}`.

## Extraction and presentation update — 27 October 2026

`ScanOptions.date_order` accepts `dmy` (default), `mdy`, or `auto`. It controls interpretation of printed numeric dates. Recognized full-year dates remain ISO `YYYY-MM-DD` in the API/JSON; the UI displays/copies `DD/MM/YYYY`. Ambiguous dates in auto mode, invalid dates and MRZ-only dates retain their source form and uncertainty.

`OCRLine` additionally provides `observations: {text,confidence,method}[]`, `review_required: boolean` and `recognition_note: string|null`. `Evidence.recognition_method` is optional/nullable. Changed enhanced readings retain the initial observation and remain uncertain.

Conflicting fields carry a preferred candidate in `value`, while retaining `status:'conflicting'`, its score, a selection reason and all evidence. Selection prefers clearly labeled, non-uncertain print, then checksum-validated MRZ, then OCR confidence. Ties retain the earlier candidate. Additive nullable `selection_basis` records `labeled_print`, `checked_mrz` or `ocr_reading` so later merges preserve the decision. A non-null value does not establish agreement or accuracy. Copy-all annotates uncertain/conflicting values. Aligned wrapped name lines are combined with separate evidence records.

Additive nullable `display_label` preserves recognized English name captions such as `First Name`, `Middle Name`, `Last Name` and `Given Name`. Canonical keys (`given_names`, `middle_names`, `surname`) remain compatible. Assembled full names do not overwrite those components. MRZ agreement preserves the visual caption.

Full-name assembly uses `source:'assembled'` with the component fields' evidence and most conservative status. Existing printed full-name order is retained; absent surname/given-name components are not inferred from a single name string. The UI displays full names first. Emirates ID values remain digit strings in JSON and display as `784-YYYY-NNNNNNN-N`. Passport numbers remain strings. Image acceptance now allows up to 40 megapixels; processing is bounded to 16 megapixels/6000 pixels per edge, with the same normalized coordinate contract.

The UI displays supported fields first, including associated unreadable fields with their headings. It does not synthesize placeholders for every passport field. Main states are Read, Verify, Different readings, Checks passed and Unreadable; numeric confidence, raw text and retry observations are in optional details. Copy OCR text joins selected `OCRLine.text` values with newlines. JSON retains all observations, statuses and confidence.

## Latest MRZ and presentation refinement — 27 October 2026

Endpoints and schema shapes are unchanged. `MRZResult.raw_lines` now preserves source OCR strings exactly (including observed case and spaces), rather than returning the normalized parser input. Parsing still normalizes case/spacing internally and never substitutes characters, pads lines or completes missing text. Incomplete candidate rows can be displayed without accepted MRZ fields. Consumers needing parsed values should continue using `mrz.fields` and validation results.

MRZ text is immediately visible and copyable, independent of validation state. Absence is shown as “MRZ not available”. All raw OCR, confidence, evidence, alternatives, warnings and checksum details are grouped in one collapsed Technical details area below the MRZ. Useful `other_fields` join the normal fields in presentation; both API collections and JSON exports remain unchanged. Main field uncertainty is still visible, without technical scores/checksum labels.

The same-origin health endpoint now uses uncached requests with four bounded startup attempts and cancellable timeouts. Vite proxy, backend CORS and startup commands remain unchanged. No new polling or logging of identity values is added.

For small Indian passport scans with unreadable captions, a conservative layout fallback requires country, partial-MRZ and aligned date/sex/name anchors. It never supplies a hidden number or inferred nationality. Layout associations use `source:'layout'` and remain uncertain; conflicting name evidence yields no selected value. Eight-digit printed dates require an explicit DMY/MDY setting and a valid calendar date. Clear label associations take precedence over fallback.
