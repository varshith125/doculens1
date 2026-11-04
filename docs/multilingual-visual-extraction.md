# Multilingual captions and visual value association

The extractor maps known document captions to stable English field keys. Results
continue to show an English heading with the printed value underneath. Original
caption spelling, OCR text, and source polygons remain available as evidence.

## Caption semantics

`backend/app/patterns/multilingual.py` extends the shared caption registry with
German, French, Italian, Spanish, Portuguese, Arabic, Chinese, and Japanese
wording. Existing English, Dutch, and other registered aliases remain supported.
The normalization and translation-grouping mechanism now applies to both core
and additional fields, rather than only names and dates. It handles accents,
typographic apostrophes, full-width colons, and translated headings printed in
one box or adjacent/stacked caption-sized boxes.

This is an explicit semantic vocabulary, not unrestricted machine translation.
Add verified aliases for unfamiliar headings. Concepts that differ by country
(such as registered domicile, origin, and birthplace) must not be collapsed
without evidence. No country, example value, or sample coordinates determine
the assignment. `place_of_origin` remains in the existing `other_fields` API
collection with that stable field name; `place_of_birth` remains separate.

## Relative typography and geometry

`typography.py` compares baseline-aligned text height and character advance.
The OCR service also rectifies each polygon against the source image and measures
plausible ink-component height and relative stroke thickness. These estimates
supplement OCR geometry; blank, clipped, or noisy crops use geometry alone.
They do not identify a font family or impose a fixed font-size cutoff.

A bounded prominence score favors larger value text over smaller nearby text.
Candidate selection still requires compatible field content, proximity,
alignment, document side, and no intervening region. Above-caption and
left-of-English-caption values require a clear relative hierarchy; Arabic
captions also allow values to their left and alignment on their right edge.
Similar candidates and competing field owners retain the existing review and
conflict behavior. Font size alone cannot choose an unrelated field's value.

The installed RapidOCR PP-OCRv6 configuration routes Latin languages, Chinese,
and Japanese to the shared recognizer (the API's existing `latin` selection).
Arabic still requires the optional installed Arabic recognizer. Label matching
cannot recover characters that the selected OCR model failed to recognize.

## Verification

`backend/tests/test_visual_label_semantics.py` includes the Swiss heading with
multiple different values, scales, and rotations; native-language captions;
stacked translations; inline values; all four value directions; nearby competing
fields; ambiguous alternatives; and source-image typography measurement.
An opt-in integration test renders a synthetic multilingual document and runs
the installed OCR model before asserting origin, birthplace, and nationality.

Run the focused tests from `backend`:

```powershell
..\.venv\Scripts\python.exe -m pytest tests/test_visual_label_semantics.py tests/test_caption_association.py tests/test_multilingual_printed_fields.py tests/test_tilted_fields.py -q
$env:DOCULENS_TEST_REAL_OCR = '1'
..\.venv\Scripts\python.exe -m pytest tests/test_visual_label_semantics.py -m integration -q
```

Synthetic fixtures verify the mechanism, including the supplied regression.
They do not establish perfect accuracy on every country's physical documents.
