import io

import numpy as np
from PIL import Image, ImageDraw

from app.services.imaging import decode_image


def scanned_pdf(width, height, resolution):
    picture = Image.new("RGB", (width, height), "white")
    ImageDraw.Draw(picture).rectangle((20, 20, width - 20, height - 20), outline="black", width=3)
    buffer = io.BytesIO()
    picture.save(buffer, "PDF", resolution=resolution)
    return buffer.getvalue()


def test_scanned_pdf_keeps_its_own_pixels_at_low_resolution():
    # 96 dpi would previously be redrawn about 2.25 times larger and blurred.
    image = decode_image(scanned_pdf(480, 330, 96))
    assert image.shape[:2] == (330, 480)


def test_scanned_pdf_keeps_its_own_pixels_at_high_resolution():
    # 400 dpi would previously be redrawn smaller, discarding detail.
    image = decode_image(scanned_pdf(2000, 1400, 400))
    assert image.shape[:2] == (1400, 2000)


def test_scanned_pdf_content_survives():
    image = decode_image(scanned_pdf(480, 330, 150))
    assert image.dtype == np.uint8 and image.shape[2] == 3
    assert image[165, 240].min() > 200 and image[21, 240].max() < 120
