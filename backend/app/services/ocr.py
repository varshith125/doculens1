from __future__ import annotations

import math
import os
import re
import threading
from pathlib import Path
from typing import Any

import cv2
import numpy as np

from app.patterns.dates import normalize_date
from app.schemas.models import OCRLine, OCRObservation, Side
from app.services.imaging import enhance_for_ocr, rotate_image


class OCRUnavailableError(RuntimeError):
    pass


def _malformed_named_date(text: str) -> bool:
    # A digit inside a three-character month can receive another actual OCR reading.
    match = re.fullmatch(r"\d{1,2}\s+([A-Z0-9]{3})\s+\d{4}", text.upper())
    return bool(match and any(c.isdigit() for c in match[1]) and any(c.isalpha() for c in match[1]))


def normalize_output(
    output: Any, side: Side = "front", offset: tuple[int, int] = (0, 0)
) -> list[OCRLine]:
    boxes = getattr(output, "boxes", None)
    texts = getattr(output, "txts", None)
    scores = getattr(output, "scores", None)
    if boxes is None or texts is None or scores is None:
        return []
    lines = []
    for box, text, score in zip(boxes, texts, scores, strict=True):
        points = np.asarray(box, dtype=float)
        confidence = float(score)
        if points.shape != (4, 2) or not np.isfinite(points).all() or not math.isfinite(confidence):
            continue
        if not isinstance(text, str) or not text.strip():
            continue
        points += np.asarray(offset)
        lines.append(
            OCRLine(
                text=text.strip(),
                confidence=max(0, min(1, confidence)),
                bounding_box=np.round(points, 2).tolist(),
                side=side,
            )
        )
    return _reading_order(lines)


def _reading_order(lines: list[OCRLine]) -> list[OCRLine]:
    if not lines:
        return []
    heights = [np.ptp(np.asarray(line.bounding_box)[:, 1]) for line in lines]
    row_height = max(8, float(np.median(heights)) * 0.65)
    return sorted(
        lines,
        key=lambda line: (
            round(min(point[1] for point in line.bounding_box) / row_height),
            min(point[0] for point in line.bounding_box),
        ),
    )


def _rotate_lines(lines: list[OCRLine], width: int, height: int, rotation: int) -> list[OCRLine]:
    rotated = []
    for line in lines:
        points = np.asarray(line.bounding_box)
        x, y = points[:, 0], points[:, 1]
        if rotation == 90:
            box = np.column_stack((height - 1 - y, x))
        elif rotation == 180:
            box = np.column_stack((width - 1 - x, height - 1 - y))
        else:
            box = np.column_stack((y, width - 1 - x))
        rotated.append(line.model_copy(update={"bounding_box": box.tolist()}))
    return _reading_order(rotated)


class OCRService:
    """One reusable ONNX pipeline per selected language, serialized per worker."""

    def __init__(
        self, arabic_model_path: str | None = None, arabic_dictionary_path: str | None = None
    ) -> None:
        self._lock = threading.RLock()
        self._engines: dict[str, Any] = {}
        self._ready = False
        self._arabic_model = arabic_model_path or os.environ.get("DOCULENS_ARABIC_MODEL_PATH", "")
        if not self._arabic_model:
            local_model = (
                Path(__file__).resolve().parents[3] / "models" / "arabic_PP-OCRv4_rec_mobile.onnx"
            )
            if local_model.is_file():
                self._arabic_model = str(local_model)
        self._arabic_dictionary = arabic_dictionary_path or os.environ.get(
            "DOCULENS_ARABIC_DICTIONARY_PATH", ""
        )

    @property
    def ready(self) -> bool:
        return self._ready

    @property
    def languages(self) -> list[str]:
        languages = ["latin"]
        if self._arabic_model and Path(self._arabic_model).is_file():
            languages.append("arabic")
        return languages

    def _get_engine(self, language: str) -> Any:
        if language not in self.languages:
            raise OCRUnavailableError("This OCR language model is not installed.")
        if language in self._engines:
            return self._engines[language]
        try:
            import rapidocr
            from rapidocr import ModelType, OCRVersion, RapidOCR

            models = Path(rapidocr.__file__).parent / "models"
            paths = {
                "Det": models / "PP-OCRv6_det_small.onnx",
                "Cls": models / "ch_ppocr_mobile_v2.0_cls_mobile.onnx",
                "Rec": models / "PP-OCRv6_rec_small.onnx",
            }
            if not all(path.is_file() for path in paths.values()):
                raise OCRUnavailableError(
                    "Bundled OCR models are missing. Reinstall the pinned RapidOCR package."
                )
            parameters: dict[str, Any] = {
                "Global.log_level": "error",
                "Global.text_score": 0.35,
                "Global.max_side_len": 2400,
                "EngineConfig.onnxruntime.intra_op_num_threads": 2,
                "EngineConfig.onnxruntime.inter_op_num_threads": 1,
                **{f"{stage}.model_path": str(path) for stage, path in paths.items()},
            }
            if language == "arabic":
                # The explicit Arabic model embeds its alphabet. Keep logical Unicode;
                # RapidOCR's Arabic display reordering would reverse text a second
                # time when the browser applies its own Unicode bidi layout.
                parameters.update(
                    {
                        "Rec.model_path": self._arabic_model,
                        "Rec.lang_type": "en",
                        "Rec.model_type": ModelType.MOBILE,
                        "Rec.ocr_version": OCRVersion.PPOCRV4,
                    }
                )
                if self._arabic_dictionary:
                    parameters["Rec.rec_keys_path"] = self._arabic_dictionary
            engine = RapidOCR(params=parameters)
            self._engines[language] = engine
            return engine
        except OCRUnavailableError:
            raise
        except Exception as exc:
            raise OCRUnavailableError("The local OCR models could not be initialized.") from exc

    def warmup(self) -> None:
        # Synthetic text forces lazy detection, orientation, and recognition sessions to load.
        sample = np.full((100, 500, 3), 255, dtype=np.uint8)
        cv2.putText(
            sample,
            "DOCULENS READY",
            (12, 65),
            cv2.FONT_HERSHEY_SIMPLEX,
            1.3,
            (0, 0, 0),
            2,
            cv2.LINE_AA,
        )
        with self._lock:
            engine = self._get_engine("latin")
            try:
                output = engine(sample, use_det=True, use_cls=True, use_rec=True)
                if not normalize_output(output):
                    raise OCRUnavailableError("OCR startup self-test did not recognize text.")
                self._ready = True
            except OCRUnavailableError:
                raise
            except Exception as exc:
                raise OCRUnavailableError(
                    "The local OCR engine failed its startup self-test."
                ) from exc

    def _read(self, engine: Any, image: np.ndarray, side: Side) -> list[OCRLine]:
        recognition_image = enhance_for_ocr(image)
        output = engine(
            recognition_image, use_det=True, use_cls=True, use_rec=True, text_score=0.35
        )
        lines = normalize_output(output, side)
        self._retry_uncertain_regions(engine, recognition_image, lines)
        return lines

    @staticmethod
    def _retry_uncertain_regions(engine: Any, image: np.ndarray, lines: list[OCRLine]) -> None:
        candidates = sorted(
            (
                line
                for line in lines
                if 0.35 <= line.confidence < 0.88 or _malformed_named_date(line.text)
            ),
            key=lambda line: line.confidence,
        )[:6]
        for line in candidates:
            points = np.asarray(line.bounding_box)
            left, top = np.floor(points.min(axis=0)).astype(int)
            right, bottom = np.ceil(points.max(axis=0)).astype(int)
            crop = image[
                max(0, top - 3) : min(image.shape[0], bottom + 4),
                max(0, left - 3) : min(image.shape[1], right + 4),
            ]
            if crop.size == 0 or min(crop.shape[:2]) < 8:
                continue
            if crop.shape[0] > crop.shape[1] * 1.6:
                crop = cv2.rotate(crop, cv2.ROTATE_90_COUNTERCLOCKWISE)
            scale = min(2.0, 2400 / max(crop.shape[:2]))
            enlarged = cv2.resize(crop, None, fx=scale, fy=scale, interpolation=cv2.INTER_CUBIC)
            gray = cv2.cvtColor(enlarged, cv2.COLOR_BGR2GRAY)
            contrast = cv2.createCLAHE(clipLimit=1.5, tileGridSize=(8, 8)).apply(gray)
            sharpened = cv2.addWeighted(
                contrast, 1.4, cv2.GaussianBlur(contrast, (0, 0), 1), -0.4, 0
            )
            variants = [
                ("Enlarged crop", enlarged),
                ("Contrast and sharpening", cv2.cvtColor(sharpened, cv2.COLOR_GRAY2BGR)),
            ]
            line.observations = [
                OCRObservation(text=line.text, confidence=line.confidence, method="Initial reading")
            ]
            for method, variant in variants:
                retried = engine(variant, use_det=False, use_cls=True, use_rec=True)
                texts, scores = getattr(retried, "txts", None), getattr(retried, "scores", None)
                if texts is None or scores is None or len(texts) != 1 or len(scores) != 1:
                    continue
                score = float(scores[0])
                if isinstance(texts[0], str) and texts[0].strip() and math.isfinite(score):
                    line.observations.append(
                        OCRObservation(
                            text=texts[0].strip(), confidence=max(0, min(1, score)), method=method
                        )
                    )
            retries = line.observations[1:]
            malformed_date = _malformed_named_date(line.text)
            if any(item.text != line.text for item in retries):
                line.review_required = True
                line.recognition_note = "OCR rereads produced different text."
                # Only accept a changed reading corroborated by both preprocessing variants.
                if len(retries) == 2 and retries[0].text == retries[1].text:
                    confidence = min(item.confidence for item in retries)
                    if confidence >= 0.85 and confidence >= line.confidence + 0.08:
                        line.text = retries[0].text
                        line.confidence = confidence
                        line.recognition_note = "Two enhanced crop readings agree; the original reading is preserved in details."
                if malformed_date:
                    readable = [
                        item
                        for item in retries
                        if item.confidence >= 0.90 and normalize_date(item.text)[1] is None
                    ]
                    if readable and len({normalize_date(item.text)[0] for item in readable}) == 1:
                        best = max(readable, key=lambda item: item.confidence)
                        line.text, line.confidence = best.text, best.confidence
                        line.recognition_note = "An enhanced crop produced a readable calendar date; other readings differed and remain in details."
            elif retries:
                line.confidence = max(line.confidence, min(item.confidence for item in retries))

    def read(
        self, image: np.ndarray, side: Side = "front", language: str = "latin"
    ) -> list[OCRLine]:
        with self._lock:
            engine = self._get_engine(language)
            try:
                return self._read(engine, image, side)
            except Exception as exc:
                raise OCRUnavailableError("Text recognition failed. Try a clearer image.") from exc

    @staticmethod
    def _orientation(engine: Any, image: np.ndarray, lines: list[OCRLine]) -> int:
        votes: dict[int, int] = {}
        for line in sorted(lines, key=lambda value: value.confidence, reverse=True)[:8]:
            if line.confidence < 0.8 or len(line.text) < 5:
                continue
            points = np.asarray(line.bounding_box)
            left, top = np.floor(points.min(axis=0)).astype(int)
            right, bottom = np.ceil(points.max(axis=0)).astype(int)
            crop = image[
                max(0, top) : min(image.shape[0], bottom + 1),
                max(0, left) : min(image.shape[1], right + 1),
            ]
            if crop.size == 0 or min(crop.shape[:2]) < 8:
                continue
            vertical = crop.shape[0] > crop.shape[1] * 1.6
            if vertical:
                crop = rotate_image(crop, 90)
            classified = engine(crop, use_det=False, use_cls=True, use_rec=False)
            predictions = getattr(classified, "cls_res", None)
            if not predictions:
                continue
            label, confidence = predictions[0]
            if confidence < 0.94:
                continue
            rotation = ((90 if vertical else 0) + (180 if str(label) == "180" else 0)) % 360
            votes[rotation] = votes.get(rotation, 0) + 1
        if not votes:
            return 0
        rotation = max(votes, key=lambda key: votes[key])
        return (
            rotation
            if votes[rotation] >= 2 and votes[rotation] / sum(votes.values()) >= 0.75
            else 0
        )

    def read_oriented(
        self,
        image: np.ndarray,
        side: Side = "front",
        language: str = "latin",
        auto_rotate: bool = True,
    ) -> tuple[np.ndarray, list[OCRLine], int]:
        with self._lock:
            engine = self._get_engine(language)
            try:
                lines = self._read(engine, image, side)
                rotation = self._orientation(engine, image, lines) if auto_rotate else 0
                if rotation:
                    height, width = image.shape[:2]
                    return (
                        rotate_image(image, rotation),
                        _rotate_lines(lines, width, height, rotation),
                        rotation,
                    )
                return image, lines, 0
            except Exception as exc:
                raise OCRUnavailableError("Text recognition failed. Try a clearer image.") from exc
