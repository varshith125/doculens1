# Run each # %% section in order using Run Cell or Shift+Enter.
# Select doculens/.venv/Scripts/python.exe as the Python interpreter.


# %% [markdown]
# # Run the Python cells in order
# Select the project's `.venv/Scripts/python.exe` kernel. Run each Python cell using its play button or **Shift+Enter**. Its pictures and text appear directly below it.
#
# Use **Run All** to refresh every output. Cell 2 reloads the latest backend extraction rules, even in an already-open Python session. If this notebook was open while its file changed, reopen it first. Start with the image path, then setup, then the reading steps. After changing the image, run all cells again from the top. The manually checked reference is used only for the supplied sample image.
#
# If you see JSON instead of cells in VS Code, right-click the file tab, select **Reopen Editor With...**, and choose **Jupyter Notebook**.
#
#
# **Two-digit year rule:** Years 00-26 use 2000-2026 and years 27-99 use 1927-1999. This applies to MRZ birth/expiry dates when no printed full year is established, and to printed issue dates with two-digit years. Four-digit years stay unchanged. The original readings remain available for comparison.
#
# **Matching the website:** This notebook now explicitly loads `backend/.env` and the default scan settings. The website and notebook must use the same image, language, crop and rotation for a fair comparison. The printed reference table is separate from actual OCR results.

# %% [markdown]
# ## Cell 1 - Choose the image path

# %%
IMAGE_PATH = 'C:\\Users\\varsh\\OneDrive\\Desktop\\Paasports\\WhatsApp Image 2026-10-28 at 17.34.47 (6).jpeg'
print("Image path:", IMAGE_PATH)

# %% [markdown]
# ## Cell 2 - Load the tools
# Run this once before reading the image.

# %%
from pathlib import Path
import sys
import cv2
import numpy as np
from PIL import Image
from IPython.display import display

project = next(p for base in [Path.cwd(), *Path.cwd().parents]
               for p in (base, base / "doculens") if (p / "backend/app").is_dir())
sys.path.insert(0, str(project / "backend"))
# Reload changed backend code even when this notebook's Python session is already open.
import importlib
importlib.invalidate_caches()
for module_name in (
    "app.patterns.common",
    "app.patterns.dates",
    "app.extractors.label_matcher",
    "app.extractors.spatial_matcher",
    "app.extractors.caption_context",
    "app.extractors.mrz_parser",
    "app.extractors.field_extractor",
    "app.services.output",
):
    importlib.reload(importlib.import_module(module_name))

# Do not reuse results calculated before this setup cell was rerun.
for old_result in ("result", "fields", "comparison"):
    globals().pop(old_result, None)

from app.services.imaging import decode_image, process_image, text_region_for_ocr
from app.services.ocr import OCRService
from app.extractors.caption_context import prepare_captions
from app.extractors.label_matcher import match_labels
from app.extractors.field_extractor import extract_fields
from app.services.output import prepare_output

def show(image):
    picture = Image.fromarray(cv2.cvtColor(image, cv2.COLOR_BGR2RGB))
    picture.thumbnail((1000, 850))
    display(picture)

def mark(image, rows):
    picture = image.copy()
    for row in rows:
        box = np.asarray(row.bounding_box, dtype=np.int32)
        cv2.polylines(picture, [box], True, (0, 150, 0), 2)
    return picture



import hashlib
from html import escape
from IPython.display import HTML

def details_table(headers, rows):
    def safe(value):
        return escape(str(value))
    display(HTML('<table style="border-collapse:collapse;text-align:left">'
        + '<tr>' + ''.join('<th style="border:1px solid #aaa;padding:8px">' + safe(h) + '</th>' for h in headers) + '</tr>'
        + ''.join('<tr>' + ''.join('<td style="border:1px solid #aaa;padding:8px">' + safe(v) + '</td>' for v in row) + '</tr>' for row in rows)
        + '</table>'))

# Read by a person from this particular photo. These values are never sent to OCR.
# Reference dates keep exactly the year visible in the photo; the actual output may expand it.
reference = [
    ("Document heading", "Refugee Travel Document", []),
    ("Document type printed on the page", "TP", ["document_code"]),
    ("Country printed on the page (meaning needs review)", "VIETN", []),
    ("Document number", "00000000", ["document_number"]),
    ("Surname", "DOE", ["surname"]),
    ("Given name", "JOHN", ["given_names", "first_name"]),
    ("Middle name", "JOSEPH", ["middle_names"]),
    ("Sex", "M", ["sex"]),
    ("Date of birth", "01 AUG/AOUT 62", ["date_of_birth"]),
    ("Nationality wording", "ADMIT AS REFUGEE", ["nationality"]),
    ("Date of issue", "03 SEP/SEPT 93", ["date_of_issue"]),
    ("Date of expiry", "03 SEP/SEPT 93", ["date_of_expiry"]),
    ("Restriction", "SAMPLE COPY - NOT LEGAL", ["restrictions", "restriction"]),
]
REFERENCE_IMAGE_SHA256 = "0a08a4408c025909fed672c950a2ef33d684f7778a6b75fc26d4f91e0e49a995"
if hashlib.sha256(Path(IMAGE_PATH).read_bytes()).hexdigest() != REFERENCE_IMAGE_SHA256:
    reference = []  # A different photo needs its own manually checked reference.

print("Latest backend date rules loaded. Run Cells 3-9 in order to refresh the results.")

# The website starts from backend/. Load the same .env explicitly in the notebook.
from app.core.config import Settings
from app.schemas.models import ScanOptions
settings = Settings()
scan_options = ScanOptions()
print("Website and notebook use the same OCR model configuration from backend/.env.")
print("Date order:", scan_options.date_order, "| Language:", scan_options.language)
print("Detection model:", settings.ocr_medium_det_path or "Bundled small model")
print("Recognition model:", settings.ocr_medium_rec_path or "Bundled small model")


# %% [markdown]
# ## Cell 3 - Show the original image and read its words
# The reference table says what is visible in this sample photo. The OCR output underneath shows what the computer actually reads.

# %%
original = decode_image(Path(IMAGE_PATH).read_bytes())
print("Image path:", IMAGE_PATH)
print("What we do: Open this photo and read the writing. This is called OCR.")
print("The green boxes show where we found writing. Nothing is erased from the photo.")
print("IMAGE 1: Your original document")
show(original)
if reference:
    print("What is visible in this photo: these are the reference readings to compare with the output.")
    details_table(["Detail", "What a person can read in the photo"], [(name, expected) for name, expected, keys in reference])
print("Now the computer reads the same photo.")
ocr = OCRService(
    ocr_models_dir=settings.ocr_models_dir,
    medium_det_path=settings.ocr_medium_det_path,
    medium_rec_path=settings.ocr_medium_rec_path,
    arabic_model_path=settings.arabic_model_path,
    arabic_dictionary_path=settings.arabic_dictionary_path,
)
original_lines = ocr.read(original, language=scan_options.language)
show(mark(original, original_lines))
print("OUTPUT FROM IMAGE 1: These are the actual words extracted by the computer.")
for row in original_lines:
    print(row.text)
if not original_lines:
    print("We could not read any words. Try a clearer photo.")

# %% [markdown]
# ## Cell 4 - Prepare image 1 for easier reading
# We use the same photo from Cell 3. We try to remove the surrounding background and straighten the page.
# **Output:** the before-and-after pictures below. If there is no safe crop, we keep the whole picture. No new personal details are extracted in this cell.

# %%
print("Image path:", IMAGE_PATH)
print("Image used: The original photo from Cell 3.")
print("What we do: Find the document edges, crop the background, and straighten the page when possible.")
processed = process_image(original, side="front", options=scan_options.front)
print("Before:")
show(original)
print("After:")
show(processed.corrected)
print("What happened: We cropped the area around the document." if processed.metadata.crop_applied
      else "What happened: The edges were unclear, so we kept the whole photo.")
print("This new picture is kept in memory for the next cell. The original file is unchanged.")
print("Output from this cell: a picture for the next reading. No new text was extracted here.")

# %% [markdown]
# ## Cell 5 - Read the prepared picture
# Now we read the picture made by Cell 4.
# **Output:** the actual words found this time. Compare the name and dates with Cell 3 to see whether anything changed.

# %%
print("Source image path:", IMAGE_PATH)
print("Image used: The picture prepared in Cell 4.")
print("What we do: Read this picture again and retry unclear writing when needed.")
corrected, lines, rotation = ocr.read_oriented(
    processed.corrected, side="front", language=scan_options.language,
    auto_rotate=scan_options.front.rotation == 0,
)
show(mark(corrected, lines))
print("What we read this time:")
for row in lines:
    print(row.text)
if not lines:
    print("We could not read any words.")
before = [row.text for row in original_lines]
after = [row.text for row in lines]
print("Result: The words and their order are the same as Cell 3." if before == after
      else "Result: Some words or their order changed. Compare this reading with Cell 3.")

# %% [markdown]
# ## Cell 6 - Separate the heading from the answer
# For example, **Surname** is a heading and **DOE** is the answer visible in your photo.
# **Output:** the headings the computer recognized and the words it found with them. An unrecognized heading is not silently filled in from the reference.

# %%
print("Source image path:", IMAGE_PATH)
print("Image used: The picture read in Cell 5.")
print("What we do: Find headings such as Surname and Date of birth. These tell us what the nearby words mean.")
caption_rows, _ = prepare_captions(lines)
found_labels = [(row, label) for row in caption_rows for label in match_labels(row.text)]
show(mark(corrected, [row for row, label in found_labels]))
print("Examples found in this passport:")
for row, label in found_labels:
    name = label.field_name.replace("_", " ")
    print(f'We read "{row.text}".')
    print(f'This tells us the {name} is "{label.value}".' if label.value
          else f'This is a heading for {name}. We still need to find its answer nearby.')
    print()
if not found_labels:
    print("We did not recognize any headings.")

# %% [markdown]
# ## Cell 7 - Show each detail extracted from this document
# We connect the headings to their answers. For example, the visible given name is **JOHN**, and the visible middle name is **JOSEPH**.
# **Output:** the answer the application actually selected and its close-up image, where available. Missing or uncertain answers stay visible as such.

# %%
print("Source image path:", IMAGE_PATH)
print("Image used: The same picture from Cell 5.")
print("What we do: Match each heading with its answer, using the nearby writing and other document details.")
result = prepare_output(extract_fields(lines, date_order=scan_options.date_order))
print("What we found, with close-up pictures:")
for field in result["fields"].values():
    if field.bounding_box:
        crop = text_region_for_ocr(corrected, field.bounding_box)
        if crop is not None:
            show(crop)
    name = field.field_name.replace("_", " ")
    answer = field.display_value or field.value
    print(f'The selected {name} is "{answer}".' if answer
          else f'We could not choose an answer for {name}.')
    if field.status in {"uncertain", "conflicting"}:
        print("Please check this against the photo. The reading is uncertain or the sources disagree.")
    print()
if not result["fields"]:
    print("We could not match any answers reliably.")

# %% [markdown]
# ## Cell 8 - Read the coded lines at the bottom
# We read the lines with letters, numbers, and `<` signs, called the MRZ.
# **Output:** the lines the computer found and the results of the check-digit checks. These results can reveal reading problems; they do not prove the document is genuine.

# %%
print("Source image path:", IMAGE_PATH)
print("Image used: The same picture from Cell 5.")
print("What we do: Read the lines with letters, numbers, and < signs at the bottom. They are called the MRZ.")
show(corrected)
mrz = result["mrz"]
print("What we read from these lines:")
for line in mrz.raw_lines:
    print(line)
if not mrz.detected:
    print("We did not find readable coded lines.")
print("What we check: Special digits help us spot some reading errors.")
for name, passed in mrz.checks.items():
    meaning = "The check passed." if passed is True else "The check did not pass. Please check the reading." if passed is False else "We could not complete this check."
    print(name.replace("_", " ").capitalize() + ": " + meaning)
print("These checks do not tell us whether the document is genuine.")

# %% [markdown]
# ## Cell 9 - What should the output say, and what did we actually get?
# The first answer column is a reference read directly from your photo. The next columns contain the computer's actual output.
# **Not extracted** means the application did not return that detail as a selected field, even if the words appear in the earlier OCR text.
# For the dates, the photo shows two-digit years. The reference preserves them instead of guessing a full year.
#
# The printed Country field and the country that issued the document are different details; they are not treated as the same field here.

# %%
print("Image path:", IMAGE_PATH)
print("What we do: Compare what is visible in your photo with what the application actually extracted.")
show(original)
fields = {field.field_name: field for field in [*result["fields"].values(), *result["other_fields"]]}
comparison = []
for name, expected, keys in reference:
    selected = [fields[key] for key in keys if key in fields]
    readings = " / ".join(f.observed_value or f.raw or "No original reading kept" for f in selected)
    answers = " / ".join(f.display_value or f.value or "No answer selected" for f in selected)
    review = "Please check" if any(f.status in {"uncertain", "conflicting"} for f in selected) else "Compare with photo"
    comparison.append((name, expected, readings or "Not extracted", answers or "Not extracted", review))
if comparison:
    print("EXPECTED READING FROM THE PHOTO AND ACTUAL OUTPUT")
    details_table(["Detail", "Visible in photo (reference)", "Computer's original reading", "Computer's final answer", "Review"], comparison)
else:
    print("This is a different photo, so the old reference answers have been hidden.")
print("ALL DETAILS RETURNED BY THE APPLICATION")
details_table(["Detail", "Answer", "Status"],
    [(("Issuing country code" if f.field_name == "country_code" else f.field_name.replace("_", " ").capitalize()), f.display_value or f.value or "Not extracted",
      "Please check" if f.status in {"uncertain", "conflicting"} else f.status.replace("_", " "))
     for f in fields.values()])
print("The application called this document:", result["document_type"].replace("_", " "))
print("Compare that classification with the printed heading: the reference image says Refugee Travel Document.")
for warning in result["warnings"]:
    print("Note:", warning)

for key, name, flag in (
    ("date_of_birth", "Birth", "birth_century_rule_applied"),
    ("date_of_expiry", "Expiry", "expiry_century_rule_applied"),
    ("date_of_issue", "Issue", "issue_century_rule_applied"),
):
    field = fields.get(key)
    if field and field.validation.get(flag):
        print(name + " date rule applied:", field.observed_value, "->", field.display_value)
print("Two-digit issue years now use the same cutoff: 00-26 becomes 2000-2026; 27-99 becomes 1927-1999.")
if not fields.get("date_of_issue") or not fields["date_of_issue"].value:
    print("No issue date was selected from this image. The year rule cannot recover text that was not read or matched to a heading.")


print("Issuing country is the country name. Issuing country code is its ICAO code, for example India and IND.")
print("Nationality is read separately. It does not have to match the issuing country.")
print("Authority, authority code and place of issue come only from printed labels and values. Missing authority details stay empty.")
print("An MRZ prefix such as P<IND identifies a passport issued by India. It does not identify a passport office.")
