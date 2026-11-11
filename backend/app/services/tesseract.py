from __future__ import annotations

import logging
import os
import re
import shutil
import string
import subprocess
from pathlib import Path

import cv2
import numpy as np

# ICAO Doc 9303 machine-readable zone alphabet.
MRZ_ALPHABET = string.digits + string.ascii_uppercase + "<"
DATE_ALPHABET = string.digits + string.ascii_letters + "/-. "

logger = logging.getLogger(__name__)


class TesseractService:
    """Tesseract OCR 5.x integration providing targeted 3rd-tier recognition fallback.

    This service operates purely locally using stdin/stdout streams on cropped bounding boxes.
    It never runs unneeded full-page scans and gracefully handles missing installations
    without disturbing the primary PP-OCR pipeline.
    """

    def __init__(
        self,
        tesseract_cmd: str = "",
        tessdata_dir: str = "",
        language: str = "eng",
        enabled: bool = True,
        timeout: float = 5.0,
    ) -> None:
        self.enabled = enabled
        self.timeout = timeout
        self.language = language or "eng"
        self._configured_cmd = tesseract_cmd
        self._configured_tessdata = tessdata_dir
        self._resolved_cmd: str | None = None
        self._resolved_tessdata: str | None = None
        self._available: bool | None = None

    def _resolve_cmd(self) -> str | None:
        if self._resolved_cmd is not None:
            return self._resolved_cmd

        # 1. Explicitly configured path or DOCULENS_TESSERACT_CMD env
        cmd = self._configured_cmd or os.environ.get("DOCULENS_TESSERACT_CMD", "").strip()
        if cmd:
            candidate = Path(cmd).expanduser()
            if candidate.is_file():
                self._resolved_cmd = str(candidate.resolve())
                return self._resolved_cmd

        # 2. Check system PATH
        found = shutil.which("tesseract")
        if found:
            self._resolved_cmd = found
            return self._resolved_cmd

        # 3. Standard Windows installation paths
        candidates = [
            Path(r"C:\Program Files\Tesseract-OCR\tesseract.exe"),
            Path(r"C:\Program Files (x86)\Tesseract-OCR\tesseract.exe"),
        ]
        local_app_data = os.environ.get("LOCALAPPDATA")
        if local_app_data:
            candidates.append(
                Path(local_app_data) / "Programs" / "Tesseract-OCR" / "tesseract.exe"
            )

        for candidate in candidates:
            if candidate.is_file():
                self._resolved_cmd = str(candidate)
                return self._resolved_cmd

        return None

    def _resolve_tessdata(self) -> str | None:
        if self._resolved_tessdata is not None:
            return self._resolved_tessdata

        # 1. Explicitly configured path or DOCULENS_TESSDATA_DIR env
        d = self._configured_tessdata or os.environ.get("DOCULENS_TESSDATA_DIR", "").strip()
        if d:
            candidate = Path(d).expanduser()
            if candidate.is_dir():
                self._resolved_tessdata = str(candidate.resolve())
                return self._resolved_tessdata

        # 2. Standard TESSDATA_PREFIX env
        prefix = os.environ.get("TESSDATA_PREFIX", "").strip()
        if prefix:
            candidate = Path(prefix).expanduser()
            if candidate.is_dir():
                self._resolved_tessdata = str(candidate.resolve())
                return self._resolved_tessdata

        # 3. Check for tessdata_best (preferred) or tessdata near the tesseract binary
        cmd = self._resolve_cmd()
        if cmd:
            tess_dir = Path(cmd).parent
            # Prefer tessdata_best for higher accuracy recognition
            for folder_name in ("tessdata_best", "tessdata"):
                sub = tess_dir / folder_name
                if sub.is_dir() and (sub / f"{self.language}.traineddata").is_file():
                    self._resolved_tessdata = str(sub)
                    return self._resolved_tessdata

        return None

    def is_available(self) -> bool:
        """Check once that a local Tesseract binary exists and runs."""
        if not self.enabled:
            return False
        if self._available is None:
            cmd = self._resolve_cmd()
            self._available = bool(cmd) and self._run([cmd, "--version"], None, 15.0) is not None
            if not self._available:
                logger.info("Tesseract backup is inactive: no working local installation was found.")
        return self._available

    @staticmethod
    def _run(args: list[str], data: bytes | None, timeout: float) -> str | None:
        """Run Tesseract in memory. A timed-out process is killed, never left running."""
        try:
            done = subprocess.run(
                args, input=data, capture_output=True, timeout=timeout,
                creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0),
            )
        except (OSError, subprocess.SubprocessError) as exc:
            logger.debug("Tesseract invocation failed: %s", exc)
            return None
        if done.returncode != 0:
            return None
        return done.stdout.decode("utf-8", errors="replace")

    @staticmethod
    def _parse_tsv_lines(tsv_output: str) -> list[tuple[str, float]]:
        """Group TSV words into printed lines with their mean word confidence."""
        rows = tsv_output.strip().splitlines()
        if len(rows) <= 1:
            return []
        columns = rows[0].split("\t")
        try:
            conf_at, text_at = columns.index("conf"), columns.index("text")
            keys = [columns.index(name) for name in ("page_num", "block_num", "par_num", "line_num")]
        except ValueError:
            return []
        grouped: dict[tuple[str, ...], list[tuple[str, float]]] = {}
        for row in rows[1:]:
            parts = row.split("\t")
            if len(parts) <= max(conf_at, text_at):
                continue
            word = parts[text_at].strip()
            try:
                confidence = float(parts[conf_at])
            except ValueError:
                continue
            if word and confidence >= 0:
                grouped.setdefault(tuple(parts[i] for i in keys), []).append((word, confidence))
        return [
            (" ".join(word for word, _ in words),
             max(0.0, min(1.0, sum(c for _, c in words) / len(words) / 100.0)))
            for words in grouped.values()
        ]

    @classmethod
    def _parse_tsv(cls, tsv_output: str) -> tuple[str, float] | None:
        """Parse Tesseract TSV output to one text and its mean word confidence."""
        lines = cls._parse_tsv_lines(tsv_output)
        if not lines:
            return None
        return " ".join(text for text, _ in lines), sum(c for _, c in lines) / len(lines)

    def _read_lines(
        self, image: np.ndarray, psm: int, whitelist: str | None, oem: int = 1,
    ) -> list[tuple[str, float]]:
        if image is None or image.size == 0 or min(image.shape[:2]) < 4 or not self.is_available():
            return []
        success, encoded = cv2.imencode(".png", image)
        if not success:
            return []
        args = [self._resolve_cmd(), "stdin", "stdout"]
        tessdata = self._resolve_tessdata()
        if tessdata:
            args += ["--tessdata-dir", tessdata]
        args += ["-l", self.language, "--psm", str(psm), "--oem", str(oem)]
        if whitelist:
            args += ["-c", f"tessedit_char_whitelist={whitelist}"]
        output = self._run([*args, "tsv"], encoded.tobytes(), self.timeout)
        return self._parse_tsv_lines(output) if output else []

    def recognize_crop(
        self,
        image: np.ndarray,
        *,
        psm: int = 7,
        whitelist: str | None = None,
        oem: int = 1,
    ) -> tuple[str, float] | None:
        """Recognize one cropped region; confidence is Tesseract's own word mean."""
        lines = self._read_lines(image, psm, whitelist, oem)
        if not lines:
            return None
        return " ".join(text for text, _ in lines), sum(c for _, c in lines) / len(lines)

    def recognize_line(
        self, crop: np.ndarray, *, psm: int = 7, whitelist: str | None = None,
    ) -> tuple[str, float] | None:
        """Targeted single-line recognition (names, headings, values)."""
        return self.recognize_crop(crop, psm=psm, whitelist=whitelist)

    def recognize_date(self, crop: np.ndarray, *, psm: int = 7) -> tuple[str, float] | None:
        """Targeted date recognition restricted to date characters."""
        return self.recognize_crop(crop, psm=psm, whitelist=DATE_ALPHABET)

    def recognize_mrz_line(self, crop: np.ndarray, *, psm: int = 7) -> tuple[str, float] | None:
        """Targeted recognition of a single MRZ line."""
        return self.recognize_crop(crop, psm=psm, whitelist=MRZ_ALPHABET)

    def recognize_mrz_block(self, crop: np.ndarray, *, psm: int = 6) -> list[tuple[str, float]]:
        """Recognize a whole MRZ block; each row keeps its measured confidence."""
        rows = [(text.replace(" ", ""), confidence)
                for text, confidence in self._read_lines(crop, psm, MRZ_ALPHABET)]
        return [(text, confidence) for text, confidence in rows
                if len(text) >= 20 and ("<" in text or re.fullmatch(r"[A-Z0-9]{20,}", text))]
