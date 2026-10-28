import type { FieldValue } from "@/types/scan";

export function displayValue(field: FieldValue): string {
  const value = field.value ?? "";
  if (field.field_name === "emirates_id_number" && /^784\d{12}$/.test(value)) {
    return `${value.slice(0, 3)}-${value.slice(3, 7)}-${value.slice(7, 14)}-${value.slice(14)}`;
  }
  if (
    ["date_of_birth", "date_of_issue", "date_of_expiry"].includes(
      field.field_name,
    )
  ) {
    const iso = /^(\d{4})-(\d{2})-(\d{2})$/.exec(value);
    if (iso) return `${iso[3]}/${iso[2]}/${iso[1]}`;
  }
  return value;
}
