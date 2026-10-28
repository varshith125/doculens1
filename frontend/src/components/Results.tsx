import { useState } from "react";
import {
  AlertCircle,
  Check,
  ChevronDown,
  Copy,
  Download,
  FileCheck2,
  Fingerprint,
  ScanText,
} from "lucide-react";
import { Button } from "@/components/ui/button";
import { label } from "@/lib/utils";
import { displayValue } from "@/lib/format";
import { TechnicalDetails } from "@/components/TechnicalDetails";
import { useMotion } from "@/hooks/useMotion";
import type { FieldValue, ScanResult } from "@/types/scan";

async function copyText(text: string) {
  await navigator.clipboard.writeText(text);
}

function fieldHeading(field: FieldValue, documentType?: string) {
  return (
    field.display_label ||
    (field.field_name === "document_number" && documentType === "passport"
      ? "Passport Number"
      : label(field.field_name))
  );
}

function FieldRow({
  field,
  documentType,
}: {
  field: FieldValue;
  documentType?: string;
}) {
  const [copied, setCopied] = useState(false);
  const [copyError, setCopyError] = useState(false);
  const value = displayValue(field);
  const fieldLabel = fieldHeading(field, documentType);
  return (
    <div className="field-row" data-result-field>
      <div className="field-topline">
        <span className="field-label">{fieldLabel}</span>
        {(field.status === "uncertain" || field.status === "conflicting") && (
          <span className={`status status-${field.status}`}>
            <AlertCircle size={11} />
            {value ? "Uncertain" : "Unreadable"}
          </span>
        )}
      </div>
      <div className="field-value-line">
        <strong dir="auto">
          {value ||
            (field.status === "conflicting"
              ? "Multiple readings available"
              : field.status === "uncertain"
                ? "Unreadable"
                : "Not available")}
        </strong>
        {field.value && (
          <Button
            size="icon"
            variant="ghost"
            aria-label={`Copy ${fieldLabel}`}
            onClick={() => {
              void copyText(value)
                .then(() => {
                  setCopied(true);
                  setTimeout(() => setCopied(false), 1800);
                })
                .catch(() => setCopyError(true));
            }}
          >
            {copied ? <Check size={14} /> : <Copy size={14} />}
          </Button>
        )}
      </div>
      {copyError && (
        <p className="field-reason" role="alert">
          Clipboard unavailable. Select the value to copy it.
        </p>
      )}
    </div>
  );
}

export function Results({ result }: { result: ScanResult }) {
  const motion = useMotion("results", result.scan_id);
  const [notice, setNotice] = useState<string | null>(null);
  const fields = Object.values(result.fields).filter(
    (field) => field.status !== "not_detected",
  );
  const allFields = [
    ...fields,
    ...result.other_fields.filter((field) => field.status !== "not_detected"),
  ];
  const fieldCount = allFields.filter((field) => field.value).length;
  const hasText = result.ocr_lines.length > 0;
  const mrzLines = result.mrz.raw_lines;
  const copyMRZ = () => {
    void copyText(mrzLines.join("\n"))
      .then(() => setNotice("MRZ copied."))
      .catch(() =>
        setNotice("Clipboard unavailable. Select the MRZ to copy it."),
      );
  };
  const personal = allFields
    .filter((field) =>
      [
        "surname",
        "family_name",
        "given_names",
        "given_name",
        "middle_names",
        "full_name",
        "nationality",
        "date_of_birth",
        "place_of_birth",
        "sex",
      ].includes(field.field_name),
    )
    .sort(
      (a, b) =>
        Number(b.field_name === "full_name") -
        Number(a.field_name === "full_name"),
    );
  const document = allFields.filter((field) => !personal.includes(field));
  const copyAll = () => {
    void copyText(
      allFields
        .map(
          (field) =>
            `${fieldHeading(field, result.document_type)}: ${displayValue(field) || (field.status === "uncertain" ? "Unreadable" : "Not available")}${field.value && field.status === "conflicting" ? " (multiple readings)" : field.value && field.status === "uncertain" ? " (uncertain)" : ""}`,
        )
        .join("\n"),
    )
      .then(() => setNotice("Extracted fields copied."))
      .catch(() =>
        setNotice("Clipboard unavailable. You can export the results instead."),
      );
  };
  const copyOCR = () => {
    void copyText(result.ocr_lines.map((line) => line.text).join("\n"))
      .then(() => setNotice("OCR text copied."))
      .catch(() =>
        setNotice("Clipboard unavailable. Select the OCR text to copy it."),
      );
  };
  const exportJson = () => {
    const url = URL.createObjectURL(
      new Blob([JSON.stringify(result, null, 2)], { type: "application/json" }),
    );
    const anchor = documentElement(url, "doculens-results.json");
    anchor.click();
    anchor.remove();
    setTimeout(() => URL.revokeObjectURL(url), 1000);
    setNotice(
      "JSON export prepared. It contains sensitive document data; store it carefully.",
    );
  };
  return (
    <div className="results-content" ref={motion}>
      <div className="result-summary">
        <span className="result-icon">
          <FileCheck2 size={25} strokeWidth={1.6} />
        </span>
        <div>
          <span className="eyebrow">DOCUMENT DETAILS</span>
          <h3>
            {result.document_type === "unknown"
              ? "Document image"
              : label(result.document_type)}
          </h3>
          <p>
            {result.issuing_country
              ? `Issuing country: ${result.issuing_country}`
              : "Review the extracted information below"}
          </p>
        </div>
        <span className="field-count" role="status" aria-live="polite">
          {fieldCount}
          <small>fields read</small>
        </span>
      </div>
      <p className="extracted-text-note">
        Details found in your document appear below. Check any marked for
        verification against the original.
      </p>
      {fieldCount === 0 && !hasText && (
        <div className="no-fields">
          <ScanText size={25} />
          <h4>No readable text found</h4>
          <p>Try a sharper image with even lighting, or adjust the crop.</p>
        </div>
      )}
      {allFields.length === 0 && hasText && (
        <div className="no-fields">
          <h4>Text found, but fields could not be matched</h4>
          <p>
            Try a closer, evenly lit image or adjust the crop. The original text
            is available below.
          </p>
        </div>
      )}
      {personal.length > 0 && (
        <section className="field-section">
          <h4>
            <Fingerprint size={14} />
            Personal information
          </h4>
          <div className="fields-grid">
            {personal.map((field) => (
              <FieldRow
                key={field.field_name}
                field={field}
                documentType={result.document_type}
              />
            ))}
          </div>
        </section>
      )}
      {document.length > 0 && (
        <section className="field-section">
          <h4>
            <FileCheck2 size={14} />
            Document details
          </h4>
          <div className="fields-grid">
            {document.map((field) => (
              <FieldRow
                key={field.field_name}
                field={field}
                documentType={result.document_type}
              />
            ))}
          </div>
        </section>
      )}
      <section className="visible-mrz" aria-labelledby="mrz-heading">
        <h4 id="mrz-heading">Machine-readable Zone (MRZ)</h4>
        {mrzLines.length > 0 ? (
          <>
            <pre
              className="mrz-text"
              tabIndex={0}
              aria-label="Recognized MRZ"
              dir="ltr"
            >
              {mrzLines.join("\n")}
            </pre>
            <Button variant="outline" size="sm" onClick={copyMRZ}>
              <Copy size={14} />
              Copy MRZ
            </Button>
          </>
        ) : (
          <p>MRZ not available</p>
        )}
      </section>
      <details className="technical-details">
        <summary>
          Technical details <ChevronDown size={14} />
        </summary>
        <TechnicalDetails
          result={result}
          fields={allFields}
          onCopyOCR={copyOCR}
        />
      </details>
      <div className="result-actions">
        {fieldCount > 0 && (
          <Button variant="outline" size="sm" onClick={copyAll}>
            <Copy size={15} /> Copy fields
          </Button>
        )}
        <Button size="sm" onClick={exportJson}>
          <Download size={15} /> Export JSON
        </Button>
      </div>
      {notice && (
        <p role="status" className="action-notice">
          {notice}
        </p>
      )}
    </div>
  );
}

function documentElement(url: string, filename: string) {
  const anchor = window.document.createElement("a");
  anchor.href = url;
  anchor.download = filename;
  window.document.body.appendChild(anchor);
  return anchor;
}
