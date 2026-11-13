import { displayValue } from "./format";
import { editField } from "./review";
import type { FieldValue, ScanResult } from "@/types/scan";

export function canSuggestIndianNationality(result: ScanResult): boolean {
  const nationality =
    result.fields.nationality ??
    result.other_fields.find((field) => field.field_name === "nationality");
  if (
    nationality &&
    (displayValue(nationality) || nationality.status === "conflicting")
  )
    return false;
  const issuers = [
    result.fields.country_code,
    result.fields.issuing_country,
  ].filter((field): field is FieldValue => Boolean(field));
  if (issuers.some((field) => field.status === "conflicting")) return false;
  const values = issuers
    .filter((field) => field.value && field.value_kind !== "unresolved")
    .map((field) => (field.code || field.value || "").trim().toUpperCase());
  if (result.issuing_country)
    values.push(result.issuing_country.trim().toUpperCase());
  return (
    values.length > 0 &&
    values.every((value) => ["IND", "INDIA", "IN"].includes(value))
  );
}

export function missingNationality(): FieldValue {
  return {
    field_name: "nationality",
    value: null,
    status: "uncertain",
    value_kind: "unresolved",
    confidence: null,
    source: null,
    bounding_box: null,
    evidence: [],
    reason:
      "Nationality was not read. The issuing country can suggest a nationality but does not establish citizenship.",
  };
}

export function confirmIndianNationality(field: FieldValue): FieldValue {
  return {
    ...editField(field, "Indian"),
    reason:
      "User confirmed Indian after a suggestion based on issuing country India (IND). Nationality was not verified by OCR or MRZ; original evidence is retained.",
    normalization_basis:
      "User-confirmed suggestion based on issuing country IND",
    validation: {
      user_edited: true,
      user_confirmed_suggestion: true,
      suggested_from_issuer: true,
    },
  };
}
