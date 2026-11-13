import { describe, expect, it } from "vitest";
import {
  copyValue,
  dateOrderWarning,
  displayValue,
  fieldHeading,
} from "@/lib/format";
import type { FieldValue } from "@/types/scan";

function field(field_name: string, display_label: string): FieldValue {
  return {
    field_name,
    display_label,
    value: "EXAMPLE",
    status: "detected",
    source: "visual",
    confidence: 0.99,
    bounding_box: null,
    reason: null,
    evidence: [],
    value_kind: "printed",
  };
}

describe("field presentation", () => {
  it.each([
    ["full_name", "Name", "Name"],
    ["full_name", "Full name", "Full Name"],
    ["first_name", "First name", "First Name"],
    ["given_names", "Given names", "Given Names"],
    ["middle_names", "Middle name", "Middle Name"],
    ["surname", "Family name", "Family Name"],
    ["country_code", "Country code", "Issuing Country Code"],
    ["issuing_country", "Issuing country", "Issuing Country"],
    ["issuing_authority", "Authority", "Issuing Authority"],
    ["authority_code", "Issuing authority code", "Authority Code"],
    ["place_of_issue", "Place of issue", "Place of Issue"],
    ["nationality", "Nationalité / Nationality", "Nationality"],
    [
      "place_of_origin",
      "Heimatort · Lieu d'origine · Luogo di attinenza",
      "Place of Origin",
    ],
    ["place_of_birth", "出生地 / Place of Birth", "Place of Birth"],
    ["full_name", "氏名", "Full Name"],
  ])("keeps %s under its own heading", (key, printed, expected) => {
    expect(fieldHeading(field(key, printed))).toBe(expected);
  });

  it("uses the same established date for display and copy", () => {
    const date = {
      ...field("date_of_issue", "Date of issue"),
      value: "2024-11-12",
      observed_value: "12th November 2024",
      normalized_value: "2024-11-12",
    };
    expect(displayValue(date)).toBe("12-November-2024");
    expect(copyValue(date)).toBe("12-November-2024");
    expect(date.observed_value).toBe("12th November 2024");
  });

  it("keeps an MRZ date raw if the backend has not supplied a full date", () => {
    const date: FieldValue = {
      ...field("date_of_birth", "Date of birth"),
      value: "880812",
      value_kind: "mrz",
      source: "mrz",
      status: "uncertain",
    };
    expect(displayValue(date)).toBe("880812");
    expect(copyValue(date)).toContain("century unknown");
  });

  it("formats a birth date expanded by the backend century rule", () => {
    const date: FieldValue = {
      ...field("date_of_birth", "Date of birth"),
      value: "1962-08-01",
      normalized_value: "1962-08-01",
      observed_value: "620801",
      value_kind: "mrz",
      source: "mrz",
      status: "uncertain",
      validation: { birth_century_rule_applied: true },
    };
    expect(displayValue(date)).toBe("01-August-1962");
    expect(copyValue(date)).not.toContain("century unknown");
    expect(date.observed_value).toBe("620801");
  });

  it("formats an MRZ fallback with an established printed year without a false century warning", () => {
    const date: FieldValue = {
      ...field("date_of_birth", "Date of birth"),
      value: "1987-06-17",
      normalized_value: "1987-06-17",
      observed_value: "870617",
      value_kind: "mrz",
      source: "multiple",
      status: "uncertain",
    };
    expect(displayValue(date)).toBe("17-June-1987");
    expect(copyValue(date)).toContain("17-June-1987");
    expect(copyValue(date)).not.toContain("century unknown");
    expect(copyValue(date)).toContain("uncertain");
  });

  it("formats an expiry date expanded by the backend century rule", () => {
    const date: FieldValue = {
      ...field("date_of_expiry", "Date of expiry"),
      value: "1993-09-03",
      normalized_value: "1993-09-03",
      observed_value: "930903",
      value_kind: "mrz",
      source: "mrz",
      status: "uncertain",
      validation: { expiry_century_rule_applied: true },
    };
    expect(displayValue(date)).toBe("03-September-1993");
    expect(copyValue(date)).not.toContain("century unknown");
    expect(date.observed_value).toBe("930903");
  });

  it("formats a printed issue date expanded by the backend century rule", () => {
    const date: FieldValue = {
      ...field("date_of_issue", "Date of issue"),
      value: "1993-09-03",
      normalized_value: "1993-09-03",
      observed_value: "03 SEP/SEPT 93",
      status: "uncertain",
      validation: { issue_century_rule_applied: true },
    };
    expect(displayValue(date)).toBe("03-September-1993");
    expect(copyValue(date)).toContain("03-September-1993");
    expect(date.observed_value).toBe("03 SEP/SEPT 93");
  });

  it("keeps a date-order warning in copied values without rewriting the date", () => {
    const date: FieldValue = {
      ...field("date_of_issue", "Date of issue"),
      value: "2024-11-12",
      normalized_value: "2024-11-12",
      status: "uncertain",
      validation: {
        issue_on_or_before_expiry: false,
        chronological_order: false,
      },
    };
    expect(displayValue(date)).toBe("12-November-2024");
    expect(copyValue(date)).toContain("12-November-2024");
    expect(copyValue(date)).toContain(
      "Date of issue is later than date of expiry.",
    );
    expect(dateOrderWarning(date)).toContain("dates have not been reassigned");
  });

  it("does not show a failed-order warning when the comparison is unavailable", () => {
    const date = {
      ...field("date_of_birth", "Date of birth"),
      validation: {
        chronological_order: null,
        birth_on_or_before_expiry: null,
      },
    };
    expect(dateOrderWarning(date)).toBeNull();
  });
});
