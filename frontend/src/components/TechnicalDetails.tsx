import { Copy } from "lucide-react";
import { Button } from "@/components/ui/button";
import { label } from "@/lib/utils";
import { fieldHeading } from "@/lib/format";
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
      {result.document_type_reason && <p>{result.document_type_reason}</p>}
      <p>
        {result.mrz.raw_lines.length > 0
          ? `${result.mrz.format || "MRZ format unavailable"} · ${
              result.mrz.checksum_valid === true ? "Checks passed"
                : result.mrz.checksum_valid === false ? "Review needed"
                  : "Validation unavailable"
            }`
          : "No MRZ was read. MRZ validation was not performed; printed fields are evaluated separately."}
      </p>
      <p>
        Checks validate transcription, not identity or document authenticity.
        Confidence measures the OCR reading, not verified accuracy. Established full dates
        display and copy as DD-MMMM-YYYY. JSON keeps normalized dates as YYYY-MM-DD and separates observed_value,
        display_value and normalized_value; value retains the existing machine-value
        role. A normalized date is available only when its interpretation is known.
        Dates without a known full year or date order retain their source reading and
        an uncertainty state. For MRZ birth and expiry dates, years 00-26 use 2000-2026
        and years 27-99 use 1927-1999 unless a printed full year was established.
        Printed issue dates with two-digit years use the same century rule.
        Printed four-digit years stay unchanged; ambiguous day/month order still requires review.
      </p>
      {!!result.mrz.corrections?.length && <div>
        <h4>Interpreted MRZ — OCR substitutions require review</h4>
        <pre className="mrz-text">{result.mrz.interpreted_lines?.join("\n")}</pre>
        <ul>{result.mrz.corrections.map((correction) => <li key={correction}>{correction}</li>)}</ul>
      </div>}
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
            {fieldHeading(field, result.document_type)} ·{" "}
            {label(field.status)}
          </h4>
          {field.reason && <p>{field.reason}</p>}
          {field.value_kind === "assembled" && field.value && (
            <p>Derived name (not a printed field): <code dir="auto">{field.value}</code></p>
          )}
          {field.display_label && (
            <p>Printed heading: <span dir="auto">{field.display_label}</span></p>
          )}
          {field.normalized_value && (
            <p>
              Normalized value: <code>{field.normalized_value}</code>
              {field.normalization_basis && <> · {field.normalization_basis}</>}
            </p>
          )}
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
                {item.associated_label && (
                  <span>Associated heading: {item.associated_label}</span>
                )}
                {item.label_fragments && item.label_fragments.length > 1 && (
                  <span>Caption fragments: {item.label_fragments.map((part) => part.raw_text).join(" · ")}</span>
                )}
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
