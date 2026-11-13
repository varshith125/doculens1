export type Side = "front" | "back";
export type Point = [number, number];
export type Corners = [Point, Point, Point, Point];
export type Rotation = 0 | 90 | 180 | 270;
export interface SideOptions {
  rotation: Rotation;
  corners: Corners | null;
}
export interface ScanOptions {
  front: SideOptions;
  back: SideOptions;
  language: "latin" | "arabic";
  date_order?: "dmy" | "mdy" | "auto";
}
export interface Evidence {
  label_fragments?: { raw_text: string; bounding_box: number[][] }[];
  associated_label?: string | null;
  label_bounding_box?: number[][] | null;
  candidate_value?: string | null;
  normalized_value?: string | null;
  validation?: Record<string, boolean | null>;
  recognition_method?: string | null;
  source: "visual" | "mrz" | "pattern";
  raw_text: string;
  side: Side;
  confidence: number | null;
  bounding_box: number[][] | null;
}
export type FieldStatus =
  "validated" | "detected" | "uncertain" | "conflicting" | "not_detected";
export interface FieldValue {
  code?: string | null;
  code_source?: string | null;
  country_name?: string | null;
  raw?: string | null;
  box?: number[] | null;
  user_edited?: boolean;
  extracted_value?: string | null;
  english_label?: string;
  observed_value?: string | null;
  display_value?: string | null;
  normalized_value?: string | null;
  normalization_basis?: string | null;
  value_kind?: "printed" | "mrz" | "assembled" | "unresolved" | null;
  validation?: Record<string, boolean | null>;
  field_name: string;
  display_label?: string | null;
  value: string | null;
  status: FieldStatus;
  confidence: number | null;
  source: string | null;
  selection_basis?: "labeled_print" | "checked_mrz" | "ocr_reading" | null;
  bounding_box: number[][] | null;
  reason: string | null;
  evidence: Evidence[];
}
export interface OCRLine {
  observations?: { text: string; confidence: number; method: string }[];
  review_required?: boolean;
  recognition_note?: string | null;
  text: string;
  confidence: number;
  bounding_box: number[][];
  side: Side;
}
export interface MRZResult {
  interpreted_lines?: string[];
  corrections?: string[];
  raw_checks?: Record<string, boolean | null>;
  detected: boolean;
  format: string | null;
  raw_lines: string[];
  checksum_valid: boolean | null;
  checks: Record<string, boolean | null>;
  fields: Record<string, string>;
  warnings: string[];
}
export interface ImageResult {
  side: Side;
  width: number;
  height: number;
  corners: Point[];
  crop_applied: boolean;
  rotation: number;
  quality: Record<string, number>;
  warnings: string[];
}
export interface ScanResult {
  checks?: Record<string, boolean | null>;
  scan_id: string;
  status: "completed";
  document_type: string;
  document_type_reason?: string | null;
  document_type_evidence?: Evidence[];
  issuing_country: string | null;
  fields: Record<string, FieldValue>;
  mrz: MRZResult;
  other_fields: FieldValue[];
  warnings: string[];
  images: ImageResult[];
  ocr_lines: OCRLine[];
  timings_ms: Record<string, number>;
}
export type Stage =
  | "queued"
  | "detecting_document"
  | "correcting_alignment"
  | "reading_text"
  | "validating_fields"
  | "preparing_results"
  | "completed"
  | "failed";
export interface Preview {
  side: Side;
  variant: "original" | "corrected";
  jpeg_base64: string;
}
export interface ScanJob {
  scan_id: string;
  status: "queued" | "processing" | "completed" | "failed";
  stage: Stage;
  result: ScanResult | null;
  error: string | null;
  /** Sent once with the final reply; the server keeps no copy afterwards. */
  previews?: Preview[];
}
export interface Health {
  status: "ok" | "degraded";
  ocr_ready: boolean;
  languages: string[];
  retention_seconds: number;
  max_upload_mb: number;
  version: string;
  optional_engines?: Record<string, boolean>;
}
export interface Uploads {
  front: File | null;
  back: File | null;
}
