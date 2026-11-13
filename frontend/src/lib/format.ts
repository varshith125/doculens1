import type { FieldValue } from "@/types/scan";

const dateFields = ["date_of_birth", "date_of_issue", "date_of_expiry"];
const monthNames = [
  "January",
  "February",
  "March",
  "April",
  "May",
  "June",
  "July",
  "August",
  "September",
  "October",
  "November",
  "December",
];

const fieldLabels: Record<string, string> = {
  full_name: "Full Name",
  given_names: "Given Names",
  first_name: "First Name",
  middle_names: "Middle Names",
  surname: "Surname",
  family_name: "Family Name",
  nationality: "Nationality",
  issuing_country: "Issuing Country",
  country_code: "Issuing Country Code",
  date_of_birth: "Date of Birth",
  date_of_issue: "Date of Issue",
  date_of_expiry: "Date of Expiry",
  place_of_birth: "Place of Birth",
  place_of_origin: "Place of Origin",
  sex: "Sex",
  document_number: "Document Number",
  national_id_number: "National ID Number",
  mrz_document_number: "MRZ Document Number",
  emirates_id_number: "Emirates ID Number",
  personal_number: "Personal Number",
  card_number: "Card Number",
  previous_passport_number: "Previous Passport Number",
  file_number: "File Number",
  book_number: "Book Number",
  document_code: "Document Type Code",
  issuing_authority: "Issuing Authority",
  authority_code: "Authority Code",
  place_of_issue: "Place of Issue",
  occupation: "Occupation",
  employer: "Employer",
  father_name: "Father's Name",
  mother_name: "Mother's Name",
  spouse_name: "Spouse's Name",
  contact_relationship: "Relationship",
  relationship: "Relationship",
  permanent_address: "Permanent Address",
  address: "Address",
  telephone_number: "Telephone Number",
  optional_data: "MRZ Optional Data",
  optional_data_1: "MRZ Optional Data 1",
  optional_data_2: "MRZ Optional Data 2",
};

export function fieldHeading(field: FieldValue, documentType?: string): string {
  const contact = field.field_name.startsWith("emergency_contact_");
  const key = contact
    ? field.field_name.slice("emergency_contact_".length)
    : field.field_name;
  let heading = fieldLabels[key] ?? "Other Printed Field";
  // Keep the printed name distinction while rendering a clean English caption.
  const printed = field.display_label ?? "";
  if (printed) {
    if (/\bdate\s+of\s+issue\b/i.test(printed)) return "Date of Issue";
    if (/\bdate\s+of\s+birth\b/i.test(printed)) return "Date of Birth";
    if (/\bdate\s+of\s+expiry\b/i.test(printed)) return "Date of Expiry";
  }
  if (
    key === "full_name" &&
    field.value_kind !== "assembled" &&
    !/\bfull\s+name\b/i.test(printed) &&
    /\bname\b/i.test(printed)
  )
    heading = "Name";
  if (key === "surname" && /\bfamily\s+name\b/i.test(printed))
    heading = "Family Name";
  else if (key === "surname" && /\blast\s+name\b/i.test(printed))
    heading = "Last Name";
  if (key === "given_names" && /\bfirst\s+names?\b/i.test(printed))
    heading = "First Name";
  else if (
    key === "given_names" &&
    /\bgiven\s+name\b(?!\s*\(s\))/i.test(printed)
  )
    heading = "Given Name";
  if (key === "middle_names" && /\bmiddle\s+name\b/i.test(printed))
    heading = "Middle Name";
  if (key === "document_number") {
    if (
      documentType === "passport" ||
      /\b(?:passport|passeport|pasaporte)\b/i.test(printed)
    ) {
      heading = "Passport Number";
    } else if (
      (documentType === "emirates_id" || documentType === "identity_card") &&
      field.value_kind === "mrz"
    )
      heading = "MRZ Document Number";
  }
  if (key === "full_name" && field.value_kind === "assembled")
    heading += " (assembled)";
  return contact ? `Emergency Contact — ${heading}` : heading;
}

function fullDate(value: string): string | null {
  const iso = /^(\d{4})-(\d{2})-(\d{2})$/.exec(value);
  const display = /^(\d{2})-([A-Za-z]+)-(\d{4})$/.exec(value);
  if (!iso && !display) return null;
  const year = iso ? iso[1] : display![3];
  const month = iso
    ? iso[2]
    : String(
        monthNames.findIndex(
          (name) => name.toLowerCase() === display![2].toLowerCase(),
        ) + 1,
      );
  const day = iso ? iso[3] : display![1];
  const y = Number(year),
    m = Number(month),
    d = Number(day);
  const leap = y % 4 === 0 && (y % 100 !== 0 || y % 400 === 0);
  const days = [31, leap ? 29 : 28, 31, 30, 31, 30, 31, 31, 30, 31, 30, 31];
  if (y < 1 || m < 1 || m > 12 || d < 1 || d > days[m - 1]) return null;
  return `${day}-${monthNames[m - 1]}-${year}`;
}

export function isMRZDate(field: FieldValue): boolean {
  return (
    dateFields.includes(field.field_name) &&
    !(field.normalized_value && fullDate(field.normalized_value)) &&
    (field.value_kind === "mrz" ||
      (!field.value_kind && field.source === "mrz"))
  );
}

export function dateOrderWarning(field: FieldValue): string | null {
  if (!dateFields.includes(field.field_name)) return null;
  const checks: [string, string][] = [
    ["birth_on_or_before_issue", "Date of birth is later than date of issue."],
    [
      "issue_on_or_before_expiry",
      "Date of issue is later than date of expiry.",
    ],
    [
      "birth_on_or_before_expiry",
      "Date of birth is later than date of expiry.",
    ],
  ];
  const messages = checks
    .filter(([key]) => field.validation?.[key] === false)
    .map(([, message]) => message);
  if (!messages.length && field.validation?.chronological_order === false) {
    messages.push("The extracted dates are in an inconsistent order.");
  }
  return messages.length
    ? `${messages.join(" ")} Review the original document; dates have not been reassigned.`
    : null;
}

export function displayValue(field: FieldValue): string {
  if (field.value === null || field.value_kind === "unresolved") return "";
  if (field.field_name === "emirates_id_number") {
    const raw = field.display_value ?? field.value ?? "";
    if (/^784\d{12}$/.test(raw)) {
      return `${raw.slice(0, 3)}-${raw.slice(3, 7)}-${raw.slice(7, 14)}-${raw.slice(14)}`;
    }
    return raw;
  }
  if (dateFields.includes(field.field_name)) {
    // Only established full dates are formatted. Never derive a century here.
    if (field.normalized_value) {
      const formatted = fullDate(field.normalized_value);
      if (formatted) return formatted;
    }
    // Honor the backend's established display date too, without reparsing raw
    // numeric text in the browser or choosing a date order a second time.
    if (
      !isMRZDate(field) &&
      field.validation?.calendar_date !== false &&
      !field.validation?.date_order_ambiguous &&
      field.display_value
    ) {
      const display = fullDate(field.display_value);
      if (display) return display;
    }
    if (field.value) {
      const iso = /^(\d{4})-(\d{2})-(\d{2})$/.exec(field.value);
      if (iso) return `${iso[3]}/${iso[2]}/${iso[1]}`;
    }
    return field.display_value ?? field.value ?? "";
  }
  return field.display_value ?? field.value ?? "";
}

export function missingValueMessage(field: FieldValue): string {
  if (field.status === "conflicting")
    return "Multiple readings available in Technical details";
  if (field.validation?.heading_unresolved) {
    return "Possible text found — field heading unclear";
  }
  if (dateFields.includes(field.field_name) && field.status === "uncertain") {
    if (field.validation?.calendar_date === false) {
      return "Date reading is invalid — check the original";
    }
    const hasCandidates =
      (field.evidence && field.evidence.length > 0) ||
      Boolean(field.raw) ||
      Boolean(field.observed_value);
    return hasCandidates ? "Unreadable" : "Full date unavailable";
  }
  if (
    field.source === "mrz" &&
    field.evidence.length > 0 &&
    field.status === "uncertain"
  ) {
    return "MRZ reading could not be confirmed";
  }
  if (field.status === "uncertain") {
    const hasCandidates =
      (field.evidence && field.evidence.length > 0) ||
      Boolean(field.raw) ||
      Boolean(field.observed_value);
    return hasCandidates ? "Unreadable" : "Not available";
  }
  return "Not available";
}

export function copyValue(field: FieldValue): string {
  const value = displayValue(field);
  if (!value) {
    return field.status === "conflicting"
      ? "Uncertain — review required"
      : "Unreadable — upload a clearer image";
  }
  const notes: string[] = [];
  if (field.status === "uncertain") notes.push("uncertain");
  if (field.status === "conflicting") notes.push("conflicting readings");
  const dateWarning = dateOrderWarning(field);
  if (dateWarning) notes.push(dateWarning);
  if (field.value_kind === "assembled") notes.push("assembled");
  if (isMRZDate(field)) {
    notes.push("MRZ source YYMMDD; full date unavailable, century unknown");
  } else if (field.value_kind === "mrz") {
    notes.push("MRZ reading");
  }
  return notes.length ? `${value} (${notes.join("; ")})` : value;
}
