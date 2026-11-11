import os
import pytest

# Ensure unit tests run offline in deterministic mode
os.environ["DOCULENS_OCR_FAST_TEXT"] = "true"
