import type { Health, ScanResult } from "@/types/scan";

export const healthResult: Health = {
  status: "ok",
  ocr_ready: true,
  languages: ["latin"],
  retention_seconds: 900,
  max_upload_mb: 12,
  version: "1.0.0",
};
export const result: ScanResult = {
  scan_id: "test-only-scan",
  status: "completed",
  document_type: "passport",
  issuing_country: null,
  fields: {
    surname: {
      field_name: "surname",
      value: "SPECIMEN",
      status: "detected",
      confidence: 0.96,
      source: "visual",
      bounding_box: null,
      reason: null,
      evidence: [
        {
          source: "visual",
          raw_text: "Surname: SPECIMEN",
          side: "front",
          confidence: 0.96,
          bounding_box: null,
        },
      ],
    },
  },
  mrz: {
    detected: false,
    format: null,
    raw_lines: [],
    checksum_valid: null,
    checks: {},
    fields: {},
    warnings: [],
  },
  other_fields: [],
  warnings: [],
  images: [],
  ocr_lines: [],
  timings_ms: {},
};
