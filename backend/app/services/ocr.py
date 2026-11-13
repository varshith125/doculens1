from __future__ import annotations

import math
import os
import re
import threading
from collections import Counter
from pathlib import Path
from typing import Any

import cv2
import numpy as np

from app.core.config import Settings
from app.extractors.caption_context import prepare_captions
from app.extractors.label_matcher import match_label
from app.extractors.mrz_parser import detect_mrz, parse_mrz, passport_name_slots
from app.extractors.spatial_matcher import SpatialScores, bounds, spatial_candidates
from app.extractors.typography import measure_appearance
from app.patterns.dates import date_context_warning, normalize_date
from app.schemas.models import OCRLine, OCRObservation, Side
from app.services.imaging import enhance_for_ocr, rotate_image, text_region_for_ocr
from app.services.tesseract import TesseractService


class OCRUnavailableError(RuntimeError):
    pass


class OCRCancelled(BaseException):
    """Stop between inference calls, including optional recovery handlers."""


def _interruptible(engine: Any, cancelled: threading.Event | None) -> Any:
    if cancelled is None:
        return engine

    def read(*args, **kwargs):
        if cancelled.is_set():
            raise OCRCancelled
        output = engine(*args, **kwargs)
        if cancelled.is_set():
            raise OCRCancelled
        return output

    return read


def _clear_labeled_reading(lines: list[OCRLine]) -> bool:
    """A short, clearly labeled document need not pay for four full-page reads."""
    return len({matched.field_name for line in lines if line.confidence >= 0.90
                and (matched := match_label(line.text)) is not None}) >= 2


def _malformed_named_date(text: str) -> bool:
    # A digit inside a three-character month can receive another actual OCR reading.
    match = re.fullmatch(r"\d{1,2}\s+([A-Z0-9]{3})\s+\d{4}", text.upper())
    return bool(match and any(c.isdigit() for c in match[1]) and any(c.isalpha() for c in match[1]))


def _malformed_numeric_date(text: str) -> bool:
    """Schedule a reread of date-like digits without assigning them to a field."""
    text = text.strip()
    if (not re.fullmatch(r"\d{1,5}(?:\s*[-/.]\s*\d{1,4}){1,2}", text)
            or not 4 <= sum(char.isdigit() for char in text) <= 10):
        return False
    # Do not let date normalization silently repair a merged day/month token
    # before OCR has had an opportunity to reread the actual printed digits.
    if any(len(part) > 4 for part in re.split(r"\s*[-/.]\s*", text)):
        return True
    _, error = normalize_date(text)
    return error is not None and "ambiguous" not in error


def _observed_month_reading(original: str, retries: list[OCRObservation]) -> OCRObservation | None:
    if not _malformed_named_date(original):
        return None
    day, damaged, year = original.upper().split()
    readings = {}
    lookalikes = {"0": "O", "1": "IL", "2": "Z", "5": "S", "6": "G", "8": "B"}
    for retry in retries:
        parts = retry.text.upper().split()
        if (len(parts) != 3 or parts[0] != day or parts[2] != year
                or len(parts[1]) != len(damaged) or retry.confidence < 0.9):
            continue
        if any(a != b and b not in lookalikes.get(a, "") for a, b in zip(damaged, parts[1], strict=True)):
            continue
        normalized, error = normalize_date(retry.text)
        if error is None:
            readings[normalized] = retry
    return next(iter(readings.values())) if len(readings) == 1 else None


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
        # Rotation changes which corner starts the polygon. Restore the geometric
        # top edge so downstream baseline matching uses the corrected image frame.
        center = box.mean(axis=0)
        box = box[np.argsort(np.arctan2(box[:, 1] - center[1], box[:, 0] - center[0]))]
        box = np.roll(box, -int(np.argmin(box.sum(axis=1))), axis=0)
        rotated.append(line.model_copy(update={"bounding_box": box.tolist()}))
    return _reading_order(rotated)


class OCRService:
    """One reusable ONNX pipeline per selected language, serialized per worker."""

    def __init__(
        self,
        arabic_model_path: str | None = None,
        arabic_dictionary_path: str | None = None,
        *,
        ocr_models_dir: str | None = None,
        medium_det_path: str | None = None,
        medium_rec_path: str | None = None,
        fast_text: bool | None = None,
        enable_tesseract: bool | None = None,
        tesseract_cmd: str | None = None,
        tessdata_dir: str | None = None,
        tesseract_language: str | None = None,
        tesseract_timeout: float | None = None,
        tesseract_service: TesseractService | None = None,
    ) -> None:
        self._lock = threading.RLock()
        self._engines: dict[str, Any] = {}
        self._ready = False
        settings = Settings()
        self._fast_text = settings.ocr_fast_text if fast_text is None else fast_text
        # Measured on a 12-thread CPU: 4 threads was fastest and 8-12 were slower,
        # so the automatic value never exceeds 4. An explicit setting overrides it.
        self._threads = settings.ocr_threads or min(4, max(2, (os.cpu_count() or 4) // 2))
        self._tesseract = tesseract_service or TesseractService(
            tesseract_cmd=settings.tesseract_cmd if tesseract_cmd is None else tesseract_cmd,
            tessdata_dir=settings.tessdata_dir if tessdata_dir is None else tessdata_dir,
            language=settings.tesseract_language if tesseract_language is None else tesseract_language,
            enabled=settings.enable_tesseract_backup if enable_tesseract is None else enable_tesseract,
            timeout=settings.tesseract_timeout_seconds if tesseract_timeout is None else tesseract_timeout,
        )
        directory = settings.ocr_models_dir if ocr_models_dir is None else ocr_models_dir
        self._medium_paths = {
            stage: Path(path).expanduser().resolve()
            for stage, path in (
                ("Det", settings.ocr_medium_det_path if medium_det_path is None else medium_det_path),
                ("Rec", settings.ocr_medium_rec_path if medium_rec_path is None else medium_rec_path),
            ) if path
        }
        self._models_dir = Path(directory).expanduser().resolve() if directory else None
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
    def tesseract(self) -> TesseractService:
        return self._tesseract

    @property
    def languages(self) -> list[str]:
        languages = ["latin"]
        if self._arabic_model and Path(self._arabic_model).is_file():
            languages.append("arabic")
        return languages

    def _get_engine(self, language: str, *, detailed: bool = False) -> Any:
        if language not in self.languages:
            raise OCRUnavailableError("This OCR language model is not installed.")
        key = language + (":detailed" if detailed else "")
        if key in self._engines:
            return self._engines[key]
        try:
            import rapidocr
            from rapidocr import ModelType, OCRVersion, RapidOCR

            from app.services.medium_models import check_medium_signature, medium_parameters

            models = self._models_dir or Path(rapidocr.__file__).parent / "models"
            paths = {
                "Det": models / "PP-OCRv6_det_small.onnx",
                "Cls": models / "ch_ppocr_mobile_v2.0_cls_mobile.onnx",
                "Rec": models / "PP-OCRv6_rec_small.onnx",
            }
            dictionary = models / "ppocrv6_dict.txt"
            active_medium = {stage: path for stage, path in self._medium_paths.items()
                             if stage != "Rec" or not self._fast_text or detailed}
            paths.update(active_medium)
            required = [*paths.values(), dictionary] if self._models_dir else paths.values()
            missing = [path.name for path in required if not path.is_file()]
            if missing:
                absent = [str(path) for path in self._medium_paths.values() if not path.is_file()]
                if absent:
                    raise OCRUnavailableError(f"Configured Medium ONNX file missing: {', '.join(absent)}")
                if self._models_dir:
                    raise OCRUnavailableError(
                        f"DOCULENS_OCR_MODELS_DIR ({models}) is missing: {', '.join(missing)}"
                    )
                raise OCRUnavailableError(
                    "Bundled OCR models are missing. Reinstall the pinned RapidOCR package."
                )
            num_threads = self._threads
            parameters: dict[str, Any] = {
                "Global.log_level": "error",
                "Global.text_score": 0.35,
                "Global.max_side_len": 1536,
                "EngineConfig.onnxruntime.intra_op_num_threads": num_threads,
                "EngineConfig.onnxruntime.inter_op_num_threads": 1,
                **{f"{stage}.model_path": str(path) for stage, path in paths.items()},
            }
            for stage, path in active_medium.items():
                if stage == "Rec" and language == "arabic":
                    continue
                try:
                    parameters.update(medium_parameters(path, stage, dictionary))
                except (ValueError, KeyError, OSError, TypeError) as exc:
                    raise OCRUnavailableError(f"Invalid Medium {stage} configuration: {exc}") from exc
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
            elif self._models_dir:
                parameters["Rec.rec_keys_path"] = str(dictionary)
            engine = RapidOCR(params=parameters)
            # Both languages use identical detection/orientation stages under this service's lock.
            for loaded in self._engines.values():
                engine.text_det = loaded.text_det
                engine.text_cls = loaded.text_cls
            if "Det" in self._medium_paths:
                check_medium_signature("Det", engine._load_det_model().session.session)
            if (self._models_dir or "Rec" in active_medium) and language == "latin":
                # RapidOCR 3.10 prefers ONNX metadata to rec_keys_path. Validate
                # its actual decoder and output width on the same cached session.
                recognizer = engine._load_rec_model()
                with dictionary.open(encoding="utf-8") as entries:
                    alphabet = ["blank", *(line.rstrip("\n") for line in entries), " "]
                classes = recognizer.session.session.get_outputs()[0].shape[-1]
                if "Rec" in active_medium:
                    check_medium_signature("Rec", recognizer.session.session, len(alphabet))
                if alphabet != recognizer.postprocess_op.character or len(alphabet) != classes:
                    raise OCRUnavailableError(
                        "ppocrv6_dict.txt does not match the PP-OCRv6 recognition alphabet or class count."
                    )
            self._engines[key] = engine
            return engine
        except OCRUnavailableError:
            raise
        except Exception as exc:
            message = "The local OCR models could not be initialized."
            if self._medium_paths:
                message = f"Configured Medium OCR stages could not be initialized: {exc}"
            raise OCRUnavailableError(message) from exc

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
                if self._fast_text and "Rec" in self._medium_paths:
                    # Validate and warm the configured recovery model now, not
                    # while a user waits for their first uncertain text crop.
                    self._get_engine("latin", detailed=True)(
                        sample, use_det=False, use_cls=False, use_rec=True,
                    )
                self._ready = True
            except OCRUnavailableError:
                raise
            except Exception as exc:
                raise OCRUnavailableError(
                    "The local OCR engine failed its startup self-test."
                ) from exc

    def _read(
        self, engine: Any, image: np.ndarray, side: Side,
        *, initial_lines: list[OCRLine] | None = None,
        refine_regions: bool = True,
        recovery_engine: Any = None,
    ) -> list[OCRLine]:
        if initial_lines is None:
            output = engine(
                image, use_det=True, use_cls=True, use_rec=True, text_score=0.35
            )
            lines = normalize_output(output, side)
        else:
            lines = initial_lines
        # A poor quality score alone never rejects the image. One conditional
        # detection retry can recover faint text when few regions were detected.
        if len(lines) < 6 and not _clear_labeled_reading(lines):
            enhanced = enhance_for_ocr(image)
            if enhanced is not image:
                try:
                    retried = engine(
                        enhanced, use_det=True, use_cls=True, use_rec=True, text_score=0.35
                    )
                    recovered = normalize_output(retried, side)
                    for line in recovered:
                        left, top, right, bottom = bounds(line)
                        area = max(1, (right - left) * (bottom - top))
                        overlaps = False
                        for original in lines:
                            x1, y1, x2, y2 = bounds(original)
                            intersection = max(0, min(right, x2) - max(left, x1)) * max(0, min(bottom, y2) - max(top, y1))
                            if intersection / min(area, max(1, (x2 - x1) * (y2 - y1))) > 0.2:
                                overlaps = True
                                break
                        if overlaps:
                            continue
                        line.observations = [OCRObservation(
                            text=line.text, confidence=line.confidence,
                            method="Conditional contrast detection retry",
                        )]
                        line.review_required = True
                        line.recognition_note = "Text was detected only after contrast adjustment; verify against the original."
                        lines.append(line)
                    lines = _reading_order(lines)
                except Exception:
                    # Optional recovery failure does not turn an empty reading into a server error.
                    pass
        if refine_regions:
            self._recover_small_captions(engine, image, lines, side)
            lines = _reading_order(lines)
            measure_appearance(image, lines)
            self._retry_uncertain_regions(
                recovery_engine or engine, image, lines,
                tesseract=self._tesseract,
            )
            self._retry_mrz_names(recovery_engine or engine, image, lines, tesseract=self._tesseract)
        return lines

    @staticmethod
    def _retry_mrz_names(
        engine: Any, image: np.ndarray, lines: list[OCRLine],
        tesseract: TesseractService | None = None,
    ) -> None:
        """Bounded OCR of damaged passport name rows and their observed name spans."""
        anchors = [line for line in lines
                   if 25 <= len(line.text.replace(" ", "")) <= 48
                   and re.match(r"^P[A-Z<][A-Z]{3}", line.text.upper().replace(" ", ""))]
        for line in anchors[:2]:
            parsed = parse_mrz([line.text])
            if (all(parsed.fields.get(key) for key in ("surname", "given_names"))
                    and not line.review_required and line.confidence >= 0.90):
                continue
            x1, y1, x2, y2 = bounds(line)
            if x2 - x1 < 80 or y2 - y1 < 4:
                continue
            if abs(line.bounding_box[1][1] - line.bounding_box[0][1]) > (x2 - x1) * 0.08:
                continue  # Do not estimate character columns on a steeply tilted row.
            height, width = image.shape[:2]
            top, bottom = max(0, int(y1) - 2), min(height, int(np.ceil(y2)) + 2)
            left, right = max(0, int(x1) - 2), min(width, int(np.ceil(x2)) + 2)
            if not line.observations:
                line.observations = [OCRObservation(text=line.text, confidence=line.confidence,
                                                    method="Initial reading")]

            def recognize(crop, method, interpolation, field_name=None, box=None, target=line):
                if crop.size == 0 or min(crop.shape[:2]) < 4:
                    return
                scale = min(8.0, 48 / crop.shape[0], 2400 / crop.shape[1])
                enlarged = cv2.resize(crop, None, fx=scale, fy=scale, interpolation=interpolation)
                try:
                    output = engine(enlarged, use_det=False, use_cls=False, use_rec=True)
                    texts, scores = getattr(output, "txts", None), getattr(output, "scores", None)
                    if texts is None or scores is None or len(texts) != 1 or len(scores) != 1:
                        return
                    text, score = str(texts[0]).strip(), float(scores[0])
                    if not text or not math.isfinite(score):
                        return
                    target.observations.append(OCRObservation(
                        text=text, confidence=max(0, min(1, score)), method=method,
                        field_name=field_name, bounding_box=box,
                    ))
                except Exception:
                    return  # Recovery is optional; preserve earlier observations.

            row_crop = image[top:bottom, left:right]
            recognize(row_crop, "MRZ original row crop: cubic", cv2.INTER_CUBIC)
            alternate = cv2.INTER_NEAREST if y2 - y1 >= 16 else cv2.INTER_LINEAR
            recognize(row_crop, "MRZ original row crop: alternate", alternate)
            full = [obs for obs in line.observations if obs.field_name is None]
            for name in ("surname", "given_names"):
                spans = Counter(slot[1:] for obs in full
                                if obs.confidence >= 0.65
                                and (slot := passport_name_slots(obs.text).get(name)))
                ranked = spans.most_common()
                if (not ranked or ranked[0][1] < 2
                        or (len(ranked) > 1 and ranked[0][1] == ranked[1][1])):
                    continue
                start, end = ranked[0][0]
                # TD3 name rows have 44 character columns. Use the original
                # detected coordinates, without repeatedly warping tiny glyphs.
                pitch = (x2 - x1) / 44
                a, b = max(0, round(x1 + start * pitch)), min(width, round(x1 + end * pitch))
                box = [[a, top], [b, top], [b, bottom], [a, bottom]]
                crop = image[top:bottom, a:b]
                recognize(crop, f"MRZ {name} crop: linear", cv2.INTER_LINEAR, name, box)
                recognize(crop, f"MRZ {name} crop: cubic", cv2.INTER_CUBIC, name, box)
                if tesseract and tesseract.is_available():
                    tess_rec = tesseract.recognize_line(crop, psm=7, whitelist="ABCDEFGHIJKLMNOPQRSTUVWXYZ<")
                    if tess_rec:
                        t_text, t_score = tess_rec
                        t_clean = t_text.replace(" ", "")
                        if t_clean:
                            line.observations.append(OCRObservation(
                                text=t_clean, confidence=max(0.0, min(1.0, t_score)),
                                method=f"Tesseract fallback: MRZ {name} crop",
                                field_name=name, bounding_box=box,
                            ))
            if len(line.observations) > 1:
                line.review_required = True
                line.recognition_note = "MRZ name crops were reread; compare the selected components with the original and alternative readings."

    @staticmethod
    def _recover_small_captions(
        engine: Any, image: np.ndarray, lines: list[OCRLine], side: Side,
    ) -> None:
        """One bounded detection pass when MRZ is readable but biodata labels are sparse."""
        anchors = [row for row in lines if re.match(r"^P[A-Z<][A-Z<]{3}", row.text.upper().replace(" ", ""))
                   and "<<" in row.text and len(row.text) >= 25]
        if len(anchors) != 1:
            return
        anchor = bounds(anchors[0])
        page_rows = [row for row in lines if bounds(row)[1] < anchor[1]
                     and anchor[0] <= (bounds(row)[0] + bounds(row)[2]) / 2 <= anchor[2]]
        caption_rows, _ = prepare_captions(page_rows)
        captions = [row for row in caption_rows if match_label(row.text)]
        if len(captions) >= 5 or len(page_rows) < 3:
            return
        # The anchor establishes a document column, not any identity value.
        # Keep the original full-image reading and map this crop back to it.
        margin = max(8, (anchor[3] - anchor[1]) * 2)
        height, width = image.shape[:2]
        left = max(0, int(anchor[0] - margin))
        right = min(width, int(anchor[2] + margin))
        top = max(0, int(min(bounds(row)[1] for row in page_rows) - margin))
        bottom = min(height, int(anchor[1]))
        crop = image[top:bottom, left:right]
        if crop.size == 0 or min(crop.shape[:2]) < 32:
            return
        # Tiny captions need more enlargement than already-readable value rows.
        # Scale from detected text height, retaining a bounded pixel budget.
        small_heights = [bounds(row)[3] - bounds(row)[1] for row in page_rows
                         if len(row.text) >= 3 and 4 <= bounds(row)[3] - bounds(row)[1] <= 20]
        target_scale = min(4.0, max(2.0, 36 / float(np.median(small_heights)))) if small_heights else 2.0
        scale = min(target_scale, 2400 / max(crop.shape[:2]),
                    (3_000_000 / (crop.shape[0] * crop.shape[1])) ** 0.5)
        if scale <= 1.05:
            return
        enlarged = cv2.resize(crop, None, fx=scale, fy=scale, interpolation=cv2.INTER_CUBIC)
        try:
            output = engine(enlarged, use_det=True, use_cls=True, use_rec=True, text_score=0.35)
            recovered = normalize_output(output, side)
        except Exception:
            return
        # Use actual rounded resize dimensions for coordinate restoration.
        sx, sy = enlarged.shape[1] / crop.shape[1], enlarged.shape[0] / crop.shape[0]
        method = "Biodata caption detection at enlarged scale"
        for row in recovered:
            row.bounding_box = [[x / sx + left, y / sy + top] for x, y in row.bounding_box]
            x1, y1, x2, y2 = bounds(row)
            area = max(1, (x2 - x1) * (y2 - y1))
            overlapping = []
            for original in lines:
                a, b, c, d = bounds(original)
                intersection = max(0, min(x2, c) - max(x1, a)) * max(0, min(y2, d) - max(y1, b))
                other_area = max(1, (c - a) * (d - b))
                if intersection / min(area, other_area) > 0.3:
                    overlapping.append((original, intersection / max(area, other_area)))
            if overlapping:
                if len(overlapping) != 1:
                    continue
                original, overlap = overlapping[0]
                # Only recover an unrecognized caption in the same text box.
                # A different reading of a value is left to regional recognition.
                if overlap < 0.75 or match_label(original.text) or not match_label(row.text) or row.confidence < 0.65:
                    continue
                if not original.observations:
                    original.observations = [OCRObservation(text=original.text, confidence=original.confidence, method="Initial reading")]
                original.observations.append(OCRObservation(text=row.text, confidence=row.confidence, method=method))
                original.text = row.text
                original.confidence = row.confidence
                original.review_required = True
                original.recognition_note = "An enlarged detection pass recovered a caption; the original reading is retained for review."
            else:
                row.observations = [OCRObservation(text=row.text, confidence=row.confidence, method=method)]
                row.review_required = True
                row.recognition_note = "Text was detected only in the enlarged biodata region; verify against the original."
                lines.append(row)

    @staticmethod
    def _retry_uncertain_regions(
        engine: Any, image: np.ndarray, lines: list[OCRLine],
        tesseract: TesseractService | None = None,
    ) -> None:
        important: set[int] = set()
        # A damaged numeric date may be confidently wrong while its tiny
        # heading is unreadable. Do not require that heading to retry the text.
        invalid_dates: set[int] = {id(line) for line in lines if _malformed_numeric_date(line.text)}
        incomplete_mrz: set[int] = set()
        date_fields: dict[int, set[str]] = {}
        scores: SpatialScores = {}
        association_lines, caption_sources = prepare_captions(lines)
        # A long MRZ-looking row that is not a legal ICAO row length is a
        # high-value crop retry, even when the recognizer reports high
        # confidence. A single missed filler can hide the surname/given-name
        # boundary and prevent safe field-level fallback.
        mrz_rows = [
            line for line in lines
            if 25 <= len(line.text.strip().replace(" ", "")) <= 48
            and "<" in line.text
        ]
        for line in mrz_rows:
            text = line.text.strip().upper().replace(" ", "")
            box = bounds(line)
            height = max(1, box[3] - box[1])
            adjacent_rows = []
            for other in mrz_rows:
                if other is line or other.side != line.side:
                    continue
                other_box = bounds(other)
                other_height = max(1, other_box[3] - other_box[1])
                gap = max(0, max(box[1], other_box[1]) - min(box[3], other_box[3]))
                overlap = min(box[2], other_box[2]) - max(box[0], other_box[0])
                if gap <= 4 * max(height, other_height) and overlap >= 0.5 * min(
                    box[2] - box[0], other_box[2] - other_box[0]
                ):
                    adjacent_rows.append(other)
            is_mrz_start = bool(re.match(r"^[PACI]<[A-Z]{3}", text) and "<<" in text)
            has_complete_neighbor = any(
                len(other.text.strip().replace(" ", "")) == len(text)
                for other in adjacent_rows
            )
            if (is_mrz_start and (len(text) not in {44, 36, 30} or not has_complete_neighbor)):
                incomplete_mrz.add(id(line))
        for line in association_lines:
            label = match_label(line.text)
            if label:
                important.update(id(part) for part in caption_sources.get(id(line), [line]))
                associated = spatial_candidates(line, association_lines, scores) if not label.value else [line]
                important.update(id(row) for row in associated)
                if label.field_name in {"date_of_birth", "date_of_issue", "date_of_expiry"}:
                    for row in associated:
                        date_fields.setdefault(id(row), set()).add(label.field_name)
                        text = label.value if row is line else row.text
                        if any(c.isdigit() for c in text):
                            normalized, reason = normalize_date(text)
                            if ((reason and "ambiguous" not in reason)
                                    or (reason is None and date_context_warning(normalized, label.field_name))):
                                invalid_dates.add(id(row))
        candidates = sorted(
            (
                line
                for line in lines
                if 0.35 <= line.confidence < 0.88
                or _malformed_named_date(line.text)
                or id(line) in invalid_dates
                or id(line) in incomplete_mrz
                or (id(line) in important and line.confidence < 0.95
                    and min(np.linalg.norm(np.asarray(line.bounding_box)[1] - line.bounding_box[0]),
                            np.linalg.norm(np.asarray(line.bounding_box)[3] - line.bounding_box[0])) < 24)
            ),
            key=lambda line: (
                id(line) not in invalid_dates,
                not (id(line) in important or "<<" in line.text), line.confidence,
            ),
        )[:6]
        for line in candidates:
            if id(line) in invalid_dates:
                line.review_required = True
                line.recognition_note = "The date-like reading failed format or calendar checks; crop rereads are retained for review."
            try:
                crop = text_region_for_ocr(image, line.bounding_box)
            except (cv2.error, ValueError):
                line.review_required = True
                line.recognition_note = "The text region could not be aligned for rereading; the original reading is retained."
                continue
            if crop is None or crop.size == 0 or min(crop.shape[:2]) < 8:
                continue
            scale = min(3.0, max(1.0, 48 / crop.shape[0]), 2400 / max(crop.shape[:2]))
            enlarged = (
                crop if scale == 1.0 else
                cv2.resize(crop, None, fx=scale, fy=scale, interpolation=cv2.INTER_CUBIC)
            )
            if not line.observations:
                line.observations = [OCRObservation(
                    text=line.text, confidence=line.confidence, method="Initial reading",
                )]
            previous_count = len(line.observations)
            for attempt in range(2):
                if attempt == 0:
                    method, variant = "Aligned original crop at reading scale", enlarged
                else:
                    # Prepare an alternative only if the first reread did not
                    # corroborate the source. Keep the same recovery settings.
                    gray = cv2.cvtColor(crop, cv2.COLOR_BGR2GRAY)
                    low_contrast = gray.std() < 32 or gray.mean() < 70
                    soft_edges = cv2.Laplacian(gray, cv2.CV_64F).var() < 55
                    if low_contrast or soft_edges:
                        adjusted = cv2.cvtColor(enlarged, cv2.COLOR_BGR2GRAY)
                        if low_contrast:
                            adjusted = cv2.createCLAHE(clipLimit=1.5, tileGridSize=(8, 8)).apply(adjusted)
                        if soft_edges:
                            adjusted = cv2.addWeighted(adjusted, 1.2, cv2.GaussianBlur(adjusted, (0, 0), 1), -0.2, 0)
                        method = "Quality-directed contrast or light sharpening"
                        variant = cv2.cvtColor(adjusted, cv2.COLOR_GRAY2BGR)
                    else:
                        alternate_scale = min(max(1.0, scale * 0.75), 2400 / max(crop.shape[:2]))
                        alternate_size = (round(crop.shape[1] * alternate_scale),
                                          round(crop.shape[0] * alternate_scale))
                        if alternate_size == (enlarged.shape[1], enlarged.shape[0]):
                            break
                        method = "Aligned original crop at alternate scale"
                        variant = cv2.resize(crop, alternate_size, interpolation=cv2.INTER_LINEAR)
                try:
                    retried = engine(variant, use_det=False, use_cls=False, use_rec=True)
                except Exception:
                    line.review_required = True
                    line.recognition_note = "An optional regional reread failed; the earlier reading is retained."
                    continue
                texts = getattr(retried, "txts", None)
                recognition_scores = getattr(retried, "scores", None)
                if texts is None or recognition_scores is None or len(texts) != 1 or len(recognition_scores) != 1:
                    continue
                try:
                    score = float(recognition_scores[0])
                except (TypeError, ValueError):
                    continue
                if isinstance(texts[0], str) and texts[0].strip() and math.isfinite(score):
                    line.observations.append(
                        OCRObservation(
                            text=texts[0].strip(), confidence=max(0, min(1, score)), method=method
                        )
                    )
                    if (texts[0].strip() == line.text and score >= 0.95
                            and id(line) not in invalid_dates
                            and not _malformed_named_date(line.text)):
                        # The original reading is corroborated. Changed or
                        # malformed readings still receive the second variant.
                        break
            retries = line.observations[previous_count:]
            if any(item.text != line.text for item in retries):
                line.review_required = True
                line.recognition_note = "OCR rereads produced different text."
                month_reading = _observed_month_reading(line.text, retries)
                if month_reading:
                    line.text = month_reading.text
                    line.confidence = month_reading.confidence
                    line.recognition_note = "A crop reread resolved a damaged month with the same printed day and year. Verify the original and alternative readings."
                    continue
                # Only accept a changed reading corroborated by both preprocessing variants.
                if len(retries) == 2 and retries[0].text == retries[1].text:
                    confidence = min(item.confidence for item in retries)
                    date_recovered = False
                    contexts = date_fields.get(id(line), set())
                    if id(line) in invalid_dates and len(contexts) <= 1:
                        field_name = next(iter(contexts), None)
                        retry_label = match_label(retries[0].text)
                        original_label = match_label(line.text)
                        # A combined caption/value crop must retain the same
                        # heading. Do not turn a different field into this date.
                        same_label = (
                            retry_label is None if original_label is None else
                            retry_label is not None and retry_label.field_name == field_name
                        )
                        text = retry_label.value if retry_label else retries[0].text
                        normalized, error = normalize_date(text)
                        date_recovered = bool(
                            same_label and confidence >= 0.90 and error is None
                            and (field_name is None or date_context_warning(normalized, field_name) is None)
                        )
                    if date_recovered or (id(line) not in invalid_dates
                                          and confidence >= 0.85 and confidence >= line.confidence + 0.08):
                        line.text = retries[0].text
                        line.confidence = confidence
                        line.recognition_note = (
                            "Two crop rereads agree on a complete calendar date after the original date failed format or date-context checks. The year comes from OCR, not an inferred century; review all readings."
                            if date_recovered else
                            "Two enhanced crop readings agree; the original reading is preserved in details."
                        )
                # Calendar syntax alone cannot justify selecting a different year.
                # Agreement between retries remains uncertain, not independent proof.
            # Last resort: Tesseract, when both OCR models are still uncertain.
            if tesseract and tesseract.is_available():
                is_date = (
                    id(line) in invalid_dates
                    or _malformed_numeric_date(line.text)
                    or _malformed_named_date(line.text)
                    or (id(line) in date_fields)
                )
                is_mrz = id(line) in incomplete_mrz or "<" in line.text
                needs_fallback = (
                    id(line) in invalid_dates
                    or _malformed_named_date(line.text)
                    or line.confidence < 0.85
                    or line.review_required
                    or (is_mrz and len(line.text.replace(" ", "")) not in {30, 36, 44})
                )
                if needs_fallback:
                    if is_date:
                        tess_res = tesseract.recognize_date(crop, psm=7)
                        if tess_res:
                            t_text, t_conf = tess_res
                            contexts = date_fields.get(id(line), set())
                            field_name = next(iter(contexts), None)
                            norm_tess, err_tess = normalize_date(t_text)
                            date_valid = (
                                err_tess is None
                                and (field_name is None or date_context_warning(norm_tess, field_name) is None)
                            )
                            line.observations.append(
                                OCRObservation(
                                    text=t_text,
                                    confidence=t_conf,
                                    method="Tesseract fallback: date crop",
                                )
                            )
                            # Overwrite only when primary/recovery failed date checks and Tesseract produced a verified date
                            if (id(line) in invalid_dates or _malformed_named_date(line.text)) and date_valid and t_conf >= 0.65:
                                line.text = t_text
                                line.confidence = t_conf
                                line.review_required = True
                                line.recognition_note = (
                                    "A valid calendar date was resolved by Tesseract backup engine after primary models failed format checks; original readings preserved in evidence."
                                )
                                invalid_dates.discard(id(line))
                    elif is_mrz:
                        tess_res = tesseract.recognize_mrz_line(crop, psm=7)
                        if tess_res:
                            t_text, t_conf = tess_res
                            t_clean = t_text.replace(" ", "")
                            if len(t_clean) in {30, 36, 44} or "<" in t_clean:
                                line.observations.append(
                                    OCRObservation(
                                        text=t_clean,
                                        confidence=t_conf,
                                        method="Tesseract fallback: MRZ line crop",
                                    )
                                )
                                if len(t_clean) in {30, 36, 44} and (len(line.text.replace(" ", "")) not in {30, 36, 44} or line.confidence < 0.75):
                                    line.text = t_clean
                                    line.confidence = t_conf
                                    line.review_required = True
                                    line.recognition_note = (
                                        "MRZ line was completed by Tesseract backup engine; earlier readings preserved in evidence."
                                    )
                    else:
                        tess_res = tesseract.recognize_line(crop, psm=7)
                        if tess_res:
                            t_text, t_conf = tess_res
                            if t_text:
                                line.observations.append(
                                    OCRObservation(
                                        text=t_text,
                                        confidence=t_conf,
                                        method="Tesseract fallback: line crop",
                                    )
                                )
                                for prior_text in [line.text] + [r.text for r in retries]:
                                    if prior_text.strip().upper() == t_text.strip().upper() and len(t_text.strip()) >= 3:
                                        line.confidence = max(line.confidence, t_conf)
                                        break

    def _recovery_reader(self, language: str, engine: Any, cancelled=None) -> Any:
        if not (self._fast_text and language == "latin" and "Rec" in self._medium_paths):
            return engine

        def read(*args, **kwargs):
            if cancelled is not None and cancelled.is_set():
                raise OCRCancelled
            return _interruptible(self._get_engine(language, detailed=True), cancelled)(*args, **kwargs)

        return read

    def read_plain(
        self, image: np.ndarray, side: Side = "front", language: str = "latin",
        cancelled: threading.Event | None = None,
    ) -> list[OCRLine]:
        """Detect and recognize without regional rereads, serialized with all other inference."""
        with self._lock:
            engine = _interruptible(self._get_engine(language), cancelled)
            return self._read(engine, image, side, refine_regions=False)

    def recognize_crop(
        self, crop: np.ndarray, language: str = "latin",
        cancelled: threading.Event | None = None,
    ) -> tuple[str, float] | None:
        """Recognize one already-located text line, without detection."""
        if crop is None or crop.size == 0 or min(crop.shape[:2]) < 4:
            return None
        with self._lock:
            engine = self._recovery_reader(
                language, _interruptible(self._get_engine(language), cancelled), cancelled)
            output = engine(crop, use_det=False, use_cls=False, use_rec=True)
        texts, scores = getattr(output, "txts", None), getattr(output, "scores", None)
        if texts is None or scores is None or len(texts) != 1 or len(scores) != 1:
            return None
        text, score = str(texts[0]).strip(), float(scores[0])
        return (text, max(0.0, min(1.0, score))) if text and math.isfinite(score) else None

    def read(
        self, image: np.ndarray, side: Side = "front", language: str = "latin"
    ) -> list[OCRLine]:
        with self._lock:
            engine = self._get_engine(language)
            try:
                return self._read(engine, image, side, recovery_engine=self._recovery_reader(language, engine))
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
            try:
                classified = engine(crop, use_det=False, use_cls=True, use_rec=False)
            except Exception:
                # Orientation is optional; retain recovered text if classification fails.
                continue
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
        cancelled: threading.Event | None = None,
    ) -> tuple[np.ndarray, list[OCRLine], int]:
        with self._lock:
            if cancelled is not None and cancelled.is_set():
                raise OCRCancelled
            engine = _interruptible(self._get_engine(language), cancelled)
            recovery = self._recovery_reader(language, engine, cancelled)
            try:
                # Choose orientation before spending regional recovery on a
                # page that may be discarded. Reuse the selected full OCR read.
                lines = self._read(engine, image, side, refine_regions=False)
                mrz, _ = detect_mrz(lines)
                has_good_reading = _clear_labeled_reading(lines) or mrz.checksum_valid is True
                avg_confidence = (sum(row.confidence for row in lines) / max(1, len(lines))) if lines else 0.0

                # Fast orientation detection via the lightweight direction classifier first
                rotation = self._orientation(engine, image, lines) if auto_rotate else 0
                if rotation:
                    # Measured: lines read on a rotated page are unreliable (one
                    # sideways direction and upside-down both misread), so the
                    # upright page is always read again.
                    image = rotate_image(image, rotation)
                    lines = self._read(engine, image, side, refine_regions=False)
                elif auto_rotate and not has_good_reading and (len(lines) < 2 or avg_confidence < 0.65):
                    def score(rows, shape):
                        horizontal = [r for r in rows
                                      if bounds(r)[2] - bounds(r)[0] > bounds(r)[3] - bounds(r)[1]]
                        # A passport MRZ belongs below the biodata. Its text
                        # alone cannot distinguish upright from upside-down.
                        bottom_mrz = sum(
                            1 for r in horizontal
                            if len(r.text.replace(" ", "")) >= 25 and "<<" in r.text
                            and (bounds(r)[1] + bounds(r)[3]) / 2 > shape[0] * 0.55
                        )
                        label_count = len({match_label(r.text).field_name for r in rows if match_label(r.text)})
                        base = sum(row.confidence * min(len(row.text), 44) for row in horizontal if row.confidence >= 0.65)
                        return bottom_mrz, base + label_count * 50

                    best_angle, best_score = 0, score(lines, image.shape)
                    best_lines = lines
                    best_image = image
                    for angle in (90, 180, 270):
                        try:
                            trial = rotate_image(image, angle)
                            rows = normalize_output(engine(trial, use_det=True, use_cls=True,
                                                           use_rec=True, text_score=0.35), side)
                            trial_score = score(rows, trial.shape)
                            if trial_score > best_score:
                                best_angle, best_score = angle, trial_score
                                best_lines = rows
                                best_image = trial
                        except Exception:
                            continue
                    image = best_image
                    lines = best_lines
                    rotation = best_angle
                self._recover_small_captions(engine, image, lines, side)
                lines = _reading_order(lines)
                measure_appearance(image, lines)
                self._retry_uncertain_regions(
                    recovery, image, lines,
                    tesseract=self._tesseract,
                )
                self._retry_mrz_names(recovery, image, lines, tesseract=self._tesseract)
                return image, lines, rotation
            except Exception as exc:
                raise OCRUnavailableError("Text recognition failed. Try a clearer image.") from exc
