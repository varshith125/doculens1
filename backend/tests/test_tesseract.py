"""Tesseract backup engine: parsing, failure handling, and a real local run when installed."""

import io
import subprocess

import cv2
import numpy as np
import pytest
from PIL import Image, ImageDraw, ImageFont

from app.core.config import Settings
from app.core.store import ScanStore
from app.extractors.mrz_parser import check_digit
from app.schemas.models import ScanOptions
from app.services.ocr import OCRService
from app.services.pipeline import run_scan
from app.services.tesseract import MRZ_ALPHABET, TesseractService

HEADER = "level\tpage_num\tblock_num\tpar_num\tline_num\tword_num\tleft\ttop\twidth\theight\tconf\ttext"


def tsv(*words):
    return "\n".join([HEADER, *(
        f"5\t1\t1\t1\t{line}\t{index}\t0\t0\t10\t10\t{conf}\t{text}"
        for index, (line, conf, text) in enumerate(words, 1)
    )])


def text_image(text, scale=1.1):
    image = np.full((70, 60 + int(len(text) * 22 * scale), 3), 255, np.uint8)
    cv2.putText(image, text, (10, 48), cv2.FONT_HERSHEY_SIMPLEX, scale, (0, 0, 0), 2, cv2.LINE_AA)
    return image


def test_tsv_words_are_grouped_by_line_with_measured_confidence():
    lines = TesseractService._parse_tsv_lines(
        tsv((1, 90, "12"), (1, 80, "AUG"), (2, 60, "1988"), (2, -1, ""), (3, "bad", "x")))
    assert lines == [("12 AUG", pytest.approx(0.85)), ("1988", pytest.approx(0.60))]
    assert TesseractService._parse_tsv(tsv((1, 90, "12"), (1, 80, "AUG"))) == (
        "12 AUG", pytest.approx(0.85))
    assert TesseractService._parse_tsv_lines("") == []
    assert TesseractService._parse_tsv_lines("unexpected\theader\nrow\tvalue") == []


def test_disabled_or_missing_engine_never_runs(monkeypatch):
    def forbidden(*_args, **_kwargs):
        raise AssertionError("Tesseract must not be invoked")

    monkeypatch.setattr(subprocess, "run", forbidden)
    assert TesseractService(enabled=False).recognize_line(text_image("ABC")) is None
    missing = TesseractService()
    monkeypatch.setattr(missing, "_resolve_cmd", lambda: None)
    assert missing.is_available() is False
    assert missing.recognize_mrz_block(text_image("ABC")) == []


def test_timeout_and_failure_degrade_to_no_reading(monkeypatch):
    service = TesseractService(timeout=0.5)
    service._available = True
    monkeypatch.setattr(service, "_resolve_cmd", lambda: "tesseract")
    monkeypatch.setattr(service, "_resolve_tessdata", lambda: None)

    def timed_out(args, **kwargs):
        assert kwargs["timeout"] == 0.5
        raise subprocess.TimeoutExpired(args, kwargs["timeout"])

    monkeypatch.setattr(subprocess, "run", timed_out)
    assert service.recognize_date(text_image("12/08/1988")) is None
    monkeypatch.setattr(subprocess, "run", lambda args, **_: subprocess.CompletedProcess(args, 1, b"", b""))
    assert service.recognize_line(text_image("ABC")) is None


def test_mrz_block_keeps_only_mrz_rows_and_their_confidence(monkeypatch):
    service = TesseractService()
    service._available = True
    monkeypatch.setattr(service, "_resolve_cmd", lambda: "tesseract")
    monkeypatch.setattr(service, "_resolve_tessdata", lambda: None)
    row = "P<UTOEXAMPLE<<ALEX<<<<<<<<<<"
    output = tsv((1, 91, row[:12]), (1, 71, row[12:]), (2, 95, "NOISE"))

    def run(args, **_):
        assert args[args.index("-c") + 1] == f"tessedit_char_whitelist={MRZ_ALPHABET}"
        return subprocess.CompletedProcess(args, 0, output.encode(), b"")

    monkeypatch.setattr(subprocess, "run", run)
    assert service.recognize_mrz_block(text_image("X")) == [(row, pytest.approx(0.81))]


@pytest.fixture(scope="module")
def installed():
    service = TesseractService()
    if not service.is_available():
        pytest.skip("Tesseract is not installed on this machine")
    return service


def test_installed_engine_reads_text_dates_and_mrz(installed):
    text, confidence = installed.recognize_line(text_image("SPECIMEN"))
    assert text == "SPECIMEN" and 0 < confidence <= 1
    assert installed.recognize_date(text_image("12/08/1988"))[0] == "12/08/1988"
    assert installed.recognize_mrz_line(text_image("P<UTOEXAMPLE<<ALEX"))[0] == "P<UTOEXAMPLE<<ALEX"


@pytest.mark.integration
def test_scan_reaches_tesseract_when_mrz_checksum_fails(installed):
    """A real scan whose MRZ cannot pass its checksum must consult the backup engine."""
    number = "L898902C3"
    second = number + check_digit(number) + "UTO7408122F3004157" + "<" * 14 + "0"
    second = second[:27] + check_digit(second[21:27]) + second[28:]
    second += "0" if check_digit(second[:10] + second[13:20] + second[21:43]) != "0" else "1"
    first = "P<UTOEXAMPLE<<ALEX<MORGAN".ljust(44, "<")
    page = Image.new("RGB", (1500, 900), "white")
    draw = ImageDraw.Draw(page)
    try:
        font = ImageFont.truetype("consola.ttf", 46)
    except OSError:
        pytest.skip("A monospaced system font is required to draw the MRZ fixture")
    draw.text((60, 120), "Surname: EXAMPLE", fill="black", font=font)
    draw.text((60, 700), first, fill="black", font=font)
    draw.text((60, 770), second, fill="black", font=font)
    encoded = io.BytesIO()
    page.save(encoded, "PNG")

    ocr = OCRService(tesseract_service=installed)
    try:
        ocr.warmup()
    except Exception:
        pytest.skip("Local OCR models are not installed")
    uploads = {"front": encoded.getvalue()}
    store = ScanStore(60, 1, 64 * 1024**2)
    job = store.create("synthetic-owner", uploads)
    run_scan(job, uploads, ScanOptions(), store, ocr, Settings())
    assert job.status == "completed", job.error
    assert job.result.mrz.detected and job.result.mrz.checksum_valid is not True
    assert "tesseract_mrz_recovery" in job.result.timings_ms
