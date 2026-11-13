import { fireEvent, render, screen, within } from "@testing-library/react";
import { expect, it } from "vitest";
import { Results } from "@/components/Results";
import type { FieldValue } from "@/types/scan";
import { result } from "./fixtures";

function field(key: string, value: string | null): FieldValue {
  return {
    field_name: key,
    value,
    display_value: value,
    value_kind: value ? "printed" : "unresolved",
    status: value ? "detected" : "uncertain",
    source: "visual",
    confidence: 0.98,
    bounding_box: null,
    evidence: [],
    reason: null,
  };
}

it("displays each issuer detail under its own heading", () => {
  const fields = {
    issuing_country: field("issuing_country", "India"),
    country_code: field("country_code", "IND"),
    issuing_authority: field("issuing_authority", "Passport Office, Hyderabad"),
    nationality: field("nationality", "Indian (IND)"),
  };
  render(
    <Results
      result={{
        ...result,
        fields,
        other_fields: [
          field("authority_code", "HYD-01"),
          field("place_of_issue", "Hyderabad"),
        ],
      }}
    />,
  );
  for (const [heading, value] of [
    ["Issuing Country", "India"],
    ["Issuing Country Code", "IND"],
    ["Issuing Authority", "Passport Office, Hyderabad"],
    ["Authority Code", "HYD-01"],
    ["Nationality", "Indian (IND)"],
    ["Place of Issue", "Hyderabad"],
  ]) {
    const row = screen.getByText(heading).closest(".field-row") as HTMLElement;
    expect(within(row).getByText(value)).toBeVisible();
  }
});

it("leaves out authority details that were not found", () => {
  render(
    <Results
      result={{
        ...result,
        fields: { issuing_authority: field("issuing_authority", null) },
        other_fields: [field("authority_code", null)],
      }}
    />,
  );
  expect(screen.queryByText("Issuing Authority")).not.toBeInTheDocument();
  expect(screen.queryByText("Authority Code")).not.toBeInTheDocument();
  expect(screen.queryByText("Not available")).not.toBeInTheDocument();
});

it("lists the fields in the agreed sequence", () => {
  const names = [
    "authority_code",
    "document_number",
    "document_code",
    "issuing_country",
    "country_code",
    "date_of_expiry",
    "date_of_issue",
    "date_of_birth",
    "nationality",
    "sex",
    "given_names",
    "surname",
    "full_name",
  ];
  const fields = Object.fromEntries(
    names.map((name) => [name, field(name, `v-${name}`)]),
  );
  const { container } = render(
    <Results result={{ ...result, fields, other_fields: [] }} />,
  );
  const shown = [...container.querySelectorAll(".field-row .field-label")].map(
    (node) => node.textContent,
  );
  expect(shown).toEqual([
    "Full Name",
    "Surname",
    "Given Names",
    "Sex",
    "Nationality",
    "Date of Birth",
    "Date of Issue",
    "Date of Expiry",
    "Issuing Country Code",
    "Issuing Country",
    "Document Type Code",
    "Passport Number",
    "Authority Code",
  ]);
});

it("shows country conflicts without hiding the retained printed reading", () => {
  render(
    <Results
      result={{
        ...result,
        fields: {
          issuing_country: {
            ...field("issuing_country", "India"),
            status: "conflicting",
          },
        },
        other_fields: [],
      }}
    />,
  );
  expect(screen.getByText("India")).toBeVisible();
  expect(screen.getByText(/Conflicting readings — compare/)).not.toBeVisible();
  fireEvent.click(screen.getByLabelText("Reading notes for Issuing Country"));
  expect(screen.getByText(/Conflicting readings — compare/)).toBeVisible();
});
