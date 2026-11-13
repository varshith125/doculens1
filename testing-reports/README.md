# DocuLens testing reports

Results from testing DocuLens, a local passport and ID-card reader, on **12 November 2026**.
Each report is a Jupyter notebook: it explains the tests in plain language, re-runs them, and
shows the results. The saved notebooks already contain the results below.

## At a glance

| Notebook | What it checks | Result |
|---|---|---|
| [01 Unit tests](01_unit_tests.ipynb) | Each part of the code on its own, plus the real OCR models and code checks | **752 passed, 0 failed** (665 backend + 87 frontend); integration and code checks all clean |
| [02 Functional tests](02_functional_tests.ipynb) | The running app, used the way the website uses it | **23 / 23 passed** |
| [03 Regression tests](03_regression_tests.ipynb) | 24 generated passports in 8 photo conditions | **99.7 %** of fields correct (766 / 768); 100 % on clean pages |
| [04 Real documents](04_real_documents.ipynb) | 16 real-world sample images, checked by hand | **80 %** of fields correct (172 / 215) |

## What this means

- **The software is reliable.** Every automated test passes, and bad input (wrong file type,
  oversized file, blank or tiny image) is refused with a clear message instead of crashing.
- **Clean documents are read almost perfectly**, including rotated, tilted, blurred,
  compressed and low-resolution versions.
- **Real photos are harder.** On real-world samples it reads 4 out of 5 fields correctly.
  Very small or blurred images and unusual captions cause most of the mistakes. Every
  result shows which fields are uncertain, so a person can check them.
- **Privacy holds under test.** Uploads are kept only in memory, never written to disk,
  and each scan is deleted as soon as its result is delivered.

## Running the notebooks

1. Install the project as described in the main [README](../README.md).
2. Open this folder in Jupyter or VS Code and choose the project's `.venv` as the kernel.
3. Run a notebook from top to bottom. Times on a laptop CPU: unit tests about 2 minutes,
   functional tests about 2 minutes, regression tests about 8 minutes, real documents instant.

The notebooks share small helpers from [`report_helpers.py`](report_helpers.py). The
hand-checked scores behind notebook 04 are in [`real-document-review.csv`](real-document-review.csv).

## Test environment

- Windows 11, 12-thread Intel CPU, 15.7 GB RAM, no GPU
- Python 3.12, Node.js 24, OCR on CPU with ONNX Runtime
- PP-OCRv6 Medium text detector, PP-OCRv6 small and Medium recognisers,
  multilingual MiniLM caption model, Tesseract 5.5 as a fallback

## Privacy note

No personal data appears in these reports. Real-world samples are identified only by
number and country; their names, document numbers and images are not published.
Generated test passports use invented people and carry a SPECIMEN watermark.
