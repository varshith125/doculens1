from typing import Literal

from pydantic import BaseModel, ConfigDict, Field

Side = Literal["front", "back"]
FieldStatus = Literal["validated", "detected", "uncertain", "conflicting", "not_detected"]


class OCRObservation(BaseModel):
    text: str
    confidence: float = Field(ge=0, le=1)
    method: str
    field_name: Literal["surname", "given_names"] | None = None
    bounding_box: list[list[float]] | None = None


class TextAppearance(BaseModel):
    """Optional image measurements in the OCR box's original pixel scale."""

    ink_height: float = Field(gt=0)
    stroke_ratio: float = Field(gt=0, le=1)


class OCRLine(BaseModel):
    text: str
    confidence: float = Field(ge=0, le=1)
    bounding_box: list[list[float]]
    side: Side = "front"
    observations: list[OCRObservation] = Field(default_factory=list)
    review_required: bool = False
    recognition_note: str | None = None
    appearance: TextAppearance | None = Field(default=None, exclude=True)
    text_height: float | None = Field(default=None, exclude=True)
    text_width: float | None = Field(default=None, exclude=True)


class CaptionFragment(BaseModel):
    raw_text: str
    bounding_box: list[list[float]]


class Evidence(BaseModel):
    source: Literal["visual", "mrz", "pattern"]
    raw_text: str
    side: Side = "front"
    confidence: float | None = None
    bounding_box: list[list[float]] | None = None
    recognition_method: str | None = None
    associated_label: str | None = None
    label_bounding_box: list[list[float]] | None = None
    label_fragments: list[CaptionFragment] = Field(default_factory=list)
    candidate_value: str | None = None
    normalized_value: str | None = None
    validation: dict[str, bool | None] = Field(default_factory=dict)


class FieldValue(BaseModel):
    code: str | None = None
    code_source: str | None = None
    country_name: str | None = None
    raw: str | None = None
    box: list[float] | None = None
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
    observed_value: str | None = None
    display_value: str | None = None
    normalized_value: str | None = None
    normalization_basis: str | None = None
    value_kind: Literal["printed", "mrz", "assembled", "unresolved"] | None = None
    validation: dict[str, bool | None] = Field(default_factory=dict)


class MRZResult(BaseModel):
    interpreted_lines: list[str] = Field(default_factory=list)
    corrections: list[str] = Field(default_factory=list)
    raw_checks: dict[str, bool | None] = Field(default_factory=dict)
    raw_fields: dict[str, str] = Field(default_factory=dict)
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
    checks: dict[str, bool | None] = Field(default_factory=dict)
    scan_id: str
    status: Literal["completed"] = "completed"
    document_type: str = "unknown"
    document_type_reason: str | None = None
    document_type_evidence: list[Evidence] = Field(default_factory=list)
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
    # Optional engines actually usable in this process, discovered at runtime.
    optional_engines: dict[str, bool] = Field(default_factory=dict)
