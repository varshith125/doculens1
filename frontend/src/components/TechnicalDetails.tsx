import { Copy } from "lucide-react";
import { Button } from "@/components/ui/button";
import { label } from "@/lib/utils";
import type { FieldValue, ScanResult } from "@/types/scan";

export function TechnicalDetails({
  result,
  fields,
  onCopyOCR,
}: {
  result: ScanResult;
  fields: FieldValue[];
  onCopyOCR: () => void;
}) {
  return (
    <div className="technical-body">
      <h4>Reading and validation notes</h4>
      <p>
        {result.mrz.format || "MRZ format unavailable"} ·{" "}
        {result.mrz.checksum_valid ? "Checks passed" : "Review needed"}
      </p>
      <p>
        Checks validate transcription, not identity or document authenticity.
        Confidence measures the OCR reading, not verified accuracy. Full-year
        dates display as DD/MM/YYYY; JSON retains ISO dates.
      </p>
      <ul>
        {[...new Set([...result.warnings, ...result.mrz.warnings])].map(
          (warning, i) => (
            <li key={i}>{warning}</li>
          ),
        )}
      </ul>
      <div className="checksum-list">
        {Object.entries(result.mrz.checks).map(([name, valid]) => (
          <span key={name}>
            {label(name)}:{" "}
            {valid === null ? "Unavailable" : valid ? "Passed" : "Failed"}
          </span>
        ))}
      </div>
      {fields.map((field, index) => (
        <section
          className="field-evidence"
          key={`${field.field_name}-${index}`}
        >
          <h4>
            {field.display_label || label(field.field_name)} ·{" "}
            {label(field.status)}
          </h4>
          {field.reason && <p>{field.reason}</p>}
          {field.confidence !== null && (
            <p>{Math.round(field.confidence * 100)}% OCR confidence</p>
          )}
          <ul>
            {field.evidence.map((item, i) => (
              <li key={i}>
                <span>
                  {label(item.side)} · {label(item.source)}
                  {item.recognition_method
                    ? ` · ${item.recognition_method}`
                    : ""}
                </span>
                <code dir="auto">{item.raw_text}</code>
                {item.confidence !== null && (
                  <span>
                    {Math.round(item.confidence * 100)}% OCR confidence
                  </span>
                )}
              </li>
            ))}
          </ul>
        </section>
      ))}
      {result.ocr_lines.length > 0 && (
        <section aria-label="Extracted OCR text" className="extracted-text">
          <div className="extracted-text-heading">
            <h4>Raw OCR text</h4>
            <Button variant="outline" size="sm" onClick={onCopyOCR}>
              <Copy size={14} />
              Copy OCR text
            </Button>
          </div>
          <pre className="raw-transcript" dir="auto">
            {result.ocr_lines.map((line) => line.text).join("\n")}
          </pre>
          {result.ocr_lines.map((line, i) => (
            <div className="field-evidence" key={i}>
              <code dir="auto">{line.text}</code>
              <span>
                {label(line.side)} · {Math.round(line.confidence * 100)}% OCR
                confidence
              </span>
              {line.recognition_note && <p>{line.recognition_note}</p>}
              {line.observations?.map((item, j) => (
                <p key={j}>
                  {item.method} · {Math.round(item.confidence * 100)}% OCR
                  confidence <code dir="auto">{item.text}</code>
                </p>
              ))}
            </div>
          ))}
        </section>
      )}
    </div>
  );
}
