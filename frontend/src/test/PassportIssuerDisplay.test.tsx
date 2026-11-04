import { fireEvent, render, screen, within } from "@testing-library/react";
import { expect, it } from "vitest";
import { Results } from "@/components/Results";
import type { FieldValue } from "@/types/scan";
import { result } from "./fixtures";

function field(key: string, value: string | null): FieldValue {
  return {
    field_name: key, value, display_value: value, value_kind: value ? "printed" : "unresolved",
    status: value ? "detected" : "uncertain", source: "visual", confidence: 0.98,
    bounding_box: null, evidence: [], reason: null,
  };
}

it("displays each issuer detail under its own heading", () => {
  const fields = {
    issuing_country: field("issuing_country", "India"),
    country_code: field("country_code", "IND"),
    issuing_authority: field("issuing_authority", "Passport Office, Hyderabad"),
    nationality: field("nationality", "Indian (IND)"),
  };
  render(<Results result={{ ...result, fields, other_fields: [
    field("authority_code", "HYD-01"), field("place_of_issue", "Hyderabad"),
  ] }} />);
  for (const [heading, value] of [
    ["Issuing Country", "India"], ["Issuing Country Code", "IND"],
    ["Issuing Authority", "Passport Office, Hyderabad"], ["Authority Code", "HYD-01"],
    ["Nationality", "Indian (IND)"], ["Place of Issue", "Hyderabad"],
  ]) {
    const row = screen.getByText(heading).closest(".field-row") as HTMLElement;
    expect(within(row).getByText(value)).toBeVisible();
  }
});

it("shows absent authority details as unavailable", () => {
  render(<Results result={{ ...result,
    fields: { issuing_authority: field("issuing_authority", null) },
    other_fields: [field("authority_code", null)],
  }} />);
  expect(screen.getAllByText("Not available")).toHaveLength(2);
  expect(screen.queryByText(/upload a clearer image/i)).not.toBeInTheDocument();
});

it("shows country conflicts without hiding the retained printed reading", () => {
  render(<Results result={{ ...result,
    fields: { issuing_country: { ...field("issuing_country", "India"), status: "conflicting" } },
    other_fields: [],
  }} />);
  expect(screen.getByText("India")).toBeVisible();
  expect(screen.getByText(/Conflicting readings — compare/)).not.toBeVisible();
  fireEvent.click(screen.getByLabelText("Reading notes for Issuing Country"));
  expect(screen.getByText(/Conflicting readings — compare/)).toBeVisible();
});
