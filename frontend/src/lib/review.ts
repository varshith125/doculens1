import { displayValue } from "./format";
import type { FieldValue, ScanResult } from "@/types/scan";

const dates = ["date_of_birth", "date_of_issue", "date_of_expiry"];

export function editField(field: FieldValue, input: string): FieldValue {
  let value = input.trim();
  if (!value) throw new Error("Enter a value or cancel the edit.");
  const isDate = dates.includes(field.field_name);
  if (isDate && (!/^\d{4}-\d{2}-\d{2}$/.test(value)
      || Number.isNaN(Date.parse(value)) || new Date(value).toISOString().slice(0, 10) !== value)) {
    throw new Error("Enter a valid calendar date as YYYY-MM-DD.");
  }
  if (["surname", "given_names", "first_name", "middle_names", "full_name"].includes(field.field_name)) {
    value = value.toUpperCase();
  }
  return { ...field, value,
    display_value: isDate ? displayValue({ ...field, value, normalized_value: value, value_kind: "printed" }) : value,
    normalized_value: isDate ? value : null,
    extracted_value: field.extracted_value ?? field.value, user_edited: true,
    source: "user", value_kind: "printed", confidence: null, status: "uncertain",
    code: null, code_source: null, country_name: null,
    reason: "Manually edited; original extraction remains in evidence. Not machine-verified.",
    selection_basis: null, normalization_basis: "User-entered value",
    validation: isDate ? { calendar_date: true, user_edited: true } : { user_edited: true } };
}

export function reviewedResult(original: ScanResult, edits: Record<string, FieldValue>): ScanResult {
  const fields = Object.fromEntries(Object.entries(original.fields).map(([key, field]) =>
    [key, { ...(edits[key] ?? field), validation: { ...(edits[key] ?? field).validation } }]));
  if (dates.some((key) => edits[key])) {
    for (const key of dates) {
      if (fields[key]) fields[key].validation = { ...fields[key].validation,
        chronological_order: null, birth_on_or_before_issue: null,
        issue_on_or_before_expiry: null, birth_on_or_before_expiry: null };
    }
    for (const [a, b, check] of [
      [dates[0], dates[1], "birth_on_or_before_issue"],
      [dates[1], dates[2], "issue_on_or_before_expiry"],
      [dates[0], dates[2], "birth_on_or_before_expiry"],
    ]) {
      const first = fields[a]?.normalized_value, second = fields[b]?.normalized_value;
      if (!first || !second) continue;
      for (const key of [a, b]) {
        fields[key].validation![check] = first <= second;
        if (first > second) { fields[key].status = "uncertain"; fields[key].validation!.chronological_order = false; }
      }
    }
  }
  return { ...original, fields,
    checks: Object.keys(edits).length ? { ...original.checks, mrz_matches_printed: null, user_edited: true } : original.checks,
    other_fields: original.other_fields.map((field) => edits[field.field_name] ?? field) };
}
