import { useState } from "react";
import {
  Check,
  ChevronDown,
  Copy,
  Download,
  FileCheck2,
  Fingerprint,
  PencilLine,
  ScanText,
} from "lucide-react";
import { motion } from "framer-motion";
import { Button } from "@/components/ui/button";
import { pop, rise, stagger, useEntrance } from "@/lib/motion";
import {
  copyValue,
  dateOrderWarning,
  displayValue,
  fieldHeading,
  isMRZDate,
  missingValueMessage,
} from "@/lib/format";
import { TechnicalDetails } from "@/components/TechnicalDetails";
import { useMotion } from "@/hooks/useMotion";
import type { FieldValue, ScanResult } from "@/types/scan";
import { editField, reviewedResult } from "@/lib/review";
import {
  canSuggestIndianNationality,
  confirmIndianNationality,
  missingNationality,
} from "@/lib/nationalitySuggestion";

// Display sequence; fields not listed keep their place after these.
const FIELD_ORDER = [
  "full_name",
  "surname",
  "family_name",
  "given_names",
  "given_name",
  "first_name",
  "middle_names",
  "sex",
  "nationality",
  "date_of_birth",
  "date_of_issue",
  "date_of_expiry",
  "country_code",
  "issuing_country",
  "document_code",
  "document_number",
  "authority_code",
];

function fieldRank(field: FieldValue): number {
  const index = FIELD_ORDER.indexOf(field.field_name);
  return index < 0 ? FIELD_ORDER.length : index;
}

const documentTitles: Record<string, string> = {
  passport: "Passport",
  emirates_id: "Emirates ID",
  identity_card: "Identity Card",
  travel_document: "Travel Document",
};

async function copyText(text: string) {
  await navigator.clipboard.writeText(text);
}

function FieldRow({
  field,
  documentType,
  onEdit,
  onHighlight,
  suggestIndianNationality = false,
}: {
  field: FieldValue;
  documentType?: string;
  onEdit: (field: FieldValue) => void;
  onHighlight?: (field: FieldValue | null) => void;
  suggestIndianNationality?: boolean;
}) {
  const [editing, setEditing] = useState(false);
  const [draft, setDraft] = useState("");
  const [editError, setEditError] = useState<string | null>(null);
  const [copied, setCopied] = useState(false);
  const [copyError, setCopyError] = useState(false);
  const value = displayValue(field);
  const isDate = ["date_of_birth", "date_of_issue", "date_of_expiry"].includes(
    field.field_name,
  );
  const fieldLabel = fieldHeading(field, documentType);
  const dateWarning = dateOrderWarning(field);
  const issuerField = [
    "issuing_country",
    "country_code",
    "issuing_authority",
    "authority_code",
    "nationality",
    "place_of_issue",
  ].includes(field.field_name);
  const missingAuthority =
    ["issuing_authority", "authority_code"].includes(field.field_name) &&
    !field.value &&
    field.evidence.length === 0;
  const readingNotes = [
    suggestIndianNationality
      ? "Suggested from issuing country India (IND). Confirm against the document; issuing country alone does not establish nationality."
      : null,
    field.reason,
    (field.value_kind === "mrz" || isMRZDate(field)) && value
      ? isMRZDate(field)
        ? "MRZ source · YYMMDD; full date unavailable, century not recorded"
        : "MRZ reading"
      : null,
    issuerField && field.status === "conflicting" && value
      ? "Conflicting readings — compare with the document. Both readings are kept in Technical details."
      : null,
  ].filter((note): note is string => Boolean(note));
  return (
    <motion.div
      className="field-row"
      data-result-field
      variants={rise}
      data-status={field.status}
      data-empty={value ? undefined : "true"}
      onMouseEnter={() => onHighlight?.(field)}
      onMouseLeave={() => onHighlight?.(null)}
      onFocus={() => onHighlight?.(field)}
      onBlur={(event) => {
        if (!event.currentTarget.contains(event.relatedTarget as Node | null))
          onHighlight?.(null);
      }}
    >
      <div className="field-topline">
        <span className="field-label">{fieldLabel}</span>
        {field.user_edited && <span className="field-edited">Edited</span>}
      </div>
      {editing ? (
        <form
          className="field-edit"
          onSubmit={(event) => {
            event.preventDefault();
            try {
              onEdit(editField(field, draft));
              setEditing(false);
              setEditError(null);
            } catch (error) {
              setEditError(
                error instanceof Error ? error.message : "Check the value.",
              );
            }
          }}
        >
          <label>
            Edit {fieldLabel}
            <input
              type={isDate ? "date" : "text"}
              autoFocus
              value={draft}
              onChange={(event) => setDraft(event.target.value)}
              onKeyDown={(event) => {
                if (event.key === "Escape") setEditing(false);
              }}
            />
          </label>
          <Button size="sm" type="submit">
            Save
          </Button>
          <Button
            size="sm"
            variant="ghost"
            type="button"
            onClick={() => setEditing(false)}
          >
            Cancel
          </Button>
          {editError && <p role="alert">{editError}</p>}
        </form>
      ) : (
        <Button
          variant="ghost"
          size="icon"
          className="field-edit-trigger"
          aria-label={`Edit ${fieldLabel}`}
          title={`Edit ${fieldLabel}`}
          onClick={() => {
            setDraft(
              isDate ? (field.normalized_value ?? "") : displayValue(field),
            );
            setEditError(null);
            setEditing(true);
          }}
        >
          <PencilLine size={14} aria-hidden="true" />
        </Button>
      )}
      <div className="field-value-line">
        <strong dir="auto">
          {value ||
            (suggestIndianNationality
              ? "Suggested nationality: Indian — please confirm"
              : missingAuthority
                ? "Not available"
                : missingValueMessage(field))}
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
      {dateWarning && <p className="field-reason">{dateWarning}</p>}
      {suggestIndianNationality && !editing && (
        <Button
          size="sm"
          variant="outline"
          onClick={() => onEdit(confirmIndianNationality(field))}
        >
          Confirm Indian nationality
        </Button>
      )}
      {readingNotes.length > 0 && (
        <details className="field-notes">
          <summary aria-label={`Reading notes for ${fieldLabel}`}>
            Reading notes <ChevronDown size={14} aria-hidden="true" />
          </summary>
          <div className="field-notes-body">
            {[...new Set(readingNotes)].map((note) => (
              <p className="field-reason" key={note}>
                {note}
              </p>
            ))}
          </div>
        </details>
      )}
      {copyError && (
        <p className="field-reason" role="alert">
          Clipboard unavailable. Select the value to copy it.
        </p>
      )}
    </motion.div>
  );
}

export function Results({
  result: original,
  onHighlight,
}: {
  result: ScanResult;
  onHighlight?: (field: FieldValue | null) => void;
}) {
  const [edits, setEdits] = useState<Record<string, FieldValue>>({});
  const offerSuggestion = canSuggestIndianNationality(original);
  const needsNationalityRow =
    offerSuggestion &&
    !original.fields.nationality &&
    !original.other_fields.some((field) => field.field_name === "nationality");
  const result = reviewedResult(
    needsNationalityRow
      ? {
          ...original,
          fields: { ...original.fields, nationality: missingNationality() },
        }
      : original,
    edits,
  );
  const suggestIndianNationality = canSuggestIndianNationality(result);
  const onEdit = (field: FieldValue) =>
    setEdits((previous) => ({ ...previous, [field.field_name]: field }));
  const motionRoot = useMotion("results", result.scan_id);
  const entrance = useEntrance();
  const [notice, setNotice] = useState<string | null>(null);
  const fields = Object.values(result.fields).filter(
    (field) =>
      field.status !== "not_detected" ||
      (suggestIndianNationality && field.field_name === "nationality"),
  );
  const diagnosticFields = [
    ...fields,
    ...result.other_fields.filter(
      (field) =>
        field.status !== "not_detected" ||
        (suggestIndianNationality && field.field_name === "nationality"),
    ),
  ];
  // Derived compatibility values remain in diagnostics/export, not printed fields.
  const allFields = diagnosticFields
    .filter(
      (field) =>
        field.value_kind !== "assembled" ||
        field.validation?.mrz_name_assembly === true,
    )
    .filter(
      (field) =>
        // An authority that was not found is left out, not listed as unavailable.
        !(
          ["issuing_authority", "authority_code"].includes(field.field_name) &&
          !field.value &&
          field.evidence.length === 0
        ),
    )
    .sort((a, b) => fieldRank(a) - fieldRank(b));
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
  const personal = allFields.filter((field) =>
    [
      "surname",
      "family_name",
      "given_names",
      "given_name",
      "first_name",
      "middle_names",
      "full_name",
      "nationality",
      "date_of_birth",
      "place_of_birth",
      "sex",
    ].includes(field.field_name),
  );
  const document = allFields.filter((field) => !personal.includes(field));
  const issuingCountry = allFields.find(
    (f) => f.field_name === "issuing_country",
  );
  const visibleDocument = document.filter((field) => {
    if (field.field_name === "country_code" && issuingCountry) {
      const cc = (displayValue(field) || field.value || "")
        .trim()
        .toUpperCase();
      const ic = (displayValue(issuingCountry) || issuingCountry.value || "")
        .trim()
        .toUpperCase();
      if (cc && ic && cc === ic) return false;
    }
    return true;
  });
  const copyAll = () => {
    void copyText(
      allFields
        .map(
          (field) =>
            `${fieldHeading(field, result.document_type)}: ${copyValue(field)}`,
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
    const payload = Object.keys(edits).length > 0 ? result : original;
    const url = URL.createObjectURL(
      new Blob([JSON.stringify(payload, null, 2)], {
        type: "application/json",
      }),
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
    <div className="results-content" ref={motionRoot}>
      <motion.div className="result-summary" variants={pop} {...entrance}>
        <span className="result-icon">
          <FileCheck2 size={25} strokeWidth={1.6} />
        </span>
        <div>
          <span className="eyebrow">DOCUMENT DETAILS</span>
          <h3>{documentTitles[result.document_type] ?? "Document image"}</h3>
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
      </motion.div>
      <p className="extracted-text-note">
        Details found in your document appear below. Compare them with the
        original; expand Reading notes beside a field for its reading and
        validation details.
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
          <motion.div
            className="fields-grid"
            variants={stagger(0.025)}
            {...entrance}
          >
            {personal.map((field) => (
              <FieldRow
                key={field.field_name}
                field={field}
                documentType={result.document_type}
                onEdit={onEdit}
                suggestIndianNationality={
                  field.field_name === "nationality" && suggestIndianNationality
                }
                onHighlight={onHighlight}
              />
            ))}
          </motion.div>
        </section>
      )}
      {visibleDocument.length > 0 && (
        <section className="field-section">
          <h4>
            <FileCheck2 size={14} />
            Document details
          </h4>
          <motion.div
            className="fields-grid"
            variants={stagger(0.025)}
            {...entrance}
          >
            {visibleDocument.map((field) => (
              <FieldRow
                key={field.field_name}
                field={field}
                documentType={result.document_type}
                onEdit={onEdit}
                onHighlight={onHighlight}
              />
            ))}
          </motion.div>
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
          <>
            <p>MRZ not available</p>
            <p className="field-reason">
              Readable printed fields are shown independently of MRZ
              availability.
            </p>
          </>
        )}
      </section>
      <details className="technical-details">
        <summary>
          Technical details <ChevronDown size={14} />
        </summary>
        <TechnicalDetails
          result={result}
          fields={diagnosticFields}
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
