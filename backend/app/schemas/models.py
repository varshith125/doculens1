from typing import Literal

from pydantic import BaseModel, ConfigDict, Field

Side = Literal["front", "back"]
FieldStatus = Literal["validated", "detected", "uncertain", "conflicting", "not_detected"]


class OCRObservation(BaseModel):
    text: str
    confidence: float = Field(ge=0, le=1)
    method: str


class OCRLine(BaseModel):
    text: str
    confidence: float = Field(ge=0, le=1)
    bounding_box: list[list[float]]
    side: Side = "front"
    observations: list[OCRObservation] = Field(default_factory=list)
    review_required: bool = False
    recognition_note: str | None = None


class Evidence(BaseModel):
    source: Literal["visual", "mrz", "pattern"]
    raw_text: str
    side: Side = "front"
    confidence: float | None = None
    bounding_box: list[list[float]] | None = None
    recognition_method: str | None = None


class FieldValue(BaseModel):
    field_name: str
    display_label: str | None = None
    value: str | None = None
    status: FieldStatus = "not_detected"
    confidence: float | None = None
    source: str | None = None
    selection_basis: Literal["labeled_print", "checked_mrz", "ocr_reading"] | None = None
    bounding_box: list[list[float]] | None = None
    reason: str | None = None
    evidence: list[Evidence] = Field(default_factory=list)


class MRZResult(BaseModel):
    detected: bool = False
    format: str | None = None
    raw_lines: list[str] = Field(default_factory=list)
    checksum_valid: bool | None = None
    checks: dict[str, bool | None] = Field(default_factory=dict)
    fields: dict[str, str] = Field(default_factory=dict)
    warnings: list[str] = Field(default_factory=list)


class ImageResult(BaseModel):
    side: Side
    width: int
    height: int
    corners: list[list[float]]
    crop_applied: bool
    rotation: int
    quality: dict[str, float]
    warnings: list[str]
    original_url: str = ""
    corrected_url: str = ""


class ScanResult(BaseModel):
    scan_id: str
    status: Literal["completed"] = "completed"
    document_type: str = "unknown"
    issuing_country: str | None = None
    fields: dict[str, FieldValue] = Field(default_factory=dict)
    mrz: MRZResult = Field(default_factory=MRZResult)
    other_fields: list[FieldValue] = Field(default_factory=list)
    warnings: list[str] = Field(default_factory=list)
    images: list[ImageResult] = Field(default_factory=list)
    ocr_lines: list[OCRLine] = Field(default_factory=list)
    timings_ms: dict[str, float] = Field(default_factory=dict)


class SideOptions(BaseModel):
    model_config = ConfigDict(extra="forbid")
    rotation: Literal[0, 90, 180, 270] = 0
    corners: list[list[float]] | None = None


class ScanOptions(BaseModel):
    model_config = ConfigDict(extra="forbid")
    front: SideOptions = Field(default_factory=SideOptions)
    back: SideOptions = Field(default_factory=SideOptions)
    language: Literal["latin", "arabic"] = "latin"
    date_order: Literal["auto", "dmy", "mdy"] = "dmy"


class JobResponse(BaseModel):
    scan_id: str
    status: Literal["queued", "processing", "completed", "failed"]
    stage: Literal[
        "queued",
        "detecting_document",
        "correcting_alignment",
        "reading_text",
        "validating_fields",
        "preparing_results",
        "completed",
        "failed",
    ]
    result: ScanResult | None = None
    error: str | None = None


class HealthResponse(BaseModel):
    status: Literal["ok", "degraded"]
    ocr_ready: bool
    languages: list[str]
    retention_seconds: int
    max_upload_mb: int
    version: str
