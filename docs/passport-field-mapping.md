# Passport issuer fields

The existing OCR, extraction, output and UI pipeline is unchanged. These fields now
have separate meanings throughout that pipeline:

| Field key | Display | Evidence allowed |
| --- | --- | --- |
| `issuing_country` | Country name, such as India | Printed country label, or lookup of the MRZ issuer code |
| `country_code` | Issuing Country Code, such as IND | Explicit printed country-code label or MRZ issuer slot |
| `issuing_authority` | Printed office or department | Printed authority label and associated value only |
| `authority_code` | Printed authority identifier | Explicit authority-code label and associated value only |
| `nationality` | Printed nationality wording, with code when recognized | Nationality label or the separate MRZ nationality slot |
| `place_of_issue` | Printed location | Place-of-issue label and associated value only |

`nationality.code` contains the recognized nationality code. It is not copied from
the issuing country. The top-level `issuing_country` remains a code for existing
document routing; `fields.issuing_country.value` now contains the country name.
The existing `country_code` field key is retained. This change to the country field's
display/value is intentional; consumers needing the code should use `country_code`
or the country field's `code` metadata.

For example, `P<IND` starts with the passport type (`P<`), followed by the issuing
state (`IND`). It contains no passport-office field. Germany's MRZ issuer is `D<<`,
with the fillers removed to produce `D`; ISO's `DEU` is not substituted into this
MRZ output. ICAO organization codes and special nationality codes are recognized
independently. Unknown codes remain in raw evidence, with no selected MRZ country.

References: [ICAO Doc 9303, Part 3, section 5](https://www.icao.int/sites/default/files/publications/DocSeries/9303_p3_cons_en.pdf)
and [Part 4, TD3 MRZ layout](https://www.icao.int/sites/default/files/publications/DocSeries/9303_p4_cons_en.pdf).
Country-code vocabulary checks are separate from check digits: issuer and
nationality codes do not have individual MRZ check digits.

## How labels and values are matched

Specific aliases are matched before shorter labels, so “Issuing Authority Code”
does not become “Authority” or “Issuing Country”. English, French, Spanish, German,
Italian and Arabic aliases cover these issuer labels. A bare “Code” or “Código”
does not establish whether a value is a country code or an office identifier.

The existing geometric matcher considers aligned rows/columns, rotation,
intervening text, candidate types and competing headings. Arabic issuer labels
also support values on the left. Similar competing associations remain unresolved;
OCR confidence alone does not choose the owner. Wrapped authority text can continue
across aligned rows until another caption or competing field interrupts it.

MRZ comparisons preserve printed values and mark disagreements as conflicts.
The UI shows a review message for conflicting issuer/nationality fields. Missing
passport authority and authority-code fields have null values and display
“Not available”. Neither nationality nor the MRZ fills an authority or place of issue.

## Verification

`backend/tests/test_passport_issuer_mapping.py` uses synthetic OCR boxes and valid
MRZ examples, with India, UAE, USA, UK, Canada and Germany examples in columns,
stacked rows and inline layouts. It covers multilingual labels, Arabic direction,
independent nationality, conflicts, unknown codes, missing authority data and
wrapped authority text. These are extraction regressions, not a claim of complete
OCR accuracy on real international passport photographs.

`frontend/src/test/PassportIssuerDisplay.test.tsx` checks field headings, values,
missing-authority messages and visible conflict notes.

The notebook and `test_steps.py` import these backend modules, including reloading
the country aliases and MRZ parser. Restart the notebook kernel and Run All to
refresh an already-open notebook. Restart a backend started without `--reload`
before checking a new website scan; old scan results are not recomputed.

Real-photo country-by-country acceptance testing still needs authorized images
and manually verified expected fields. The existing opt-in authorized-sample
integration suite can be used for that validation.

Verification on 2026-11-03: 70 new backend issuer-mapping cases pass; the focused
backend regression selection passes 182 tests. The complete non-integration
backend run has 375 passes and the same 20 failing tests recorded before this
change (no additional failures). The targeted frontend selection passes 23 tests,
and TypeScript type checking passes. The broader existing Results test file still
has seven failures involving its other display/copy expectations. The supplied
photo's notebook executes all nine code cells with no errors and 16 image outputs.
