import { fireEvent, render, screen, within } from "@testing-library/react";
import { expect, it } from "vitest";
import { Results } from "@/components/Results";
import type { FieldValue } from "@/types/scan";
import { result } from "./fixtures";

it.each([
  ["surname", "Surname", "EXAMPLE"],
  ["country_code", "Issuing Country Code", "IND"],
  ["authority_code", "Authority Code", null],
])("keeps %s explanations optional and collapsed", (key, heading, value) => {
  const reason = "MRZ fallback: the printed field is missing or unreadable. Verify the source.";
  const field: FieldValue = {
    ...result.fields.surname, field_name: key, value, status: "uncertain",
    value_kind: value ? "mrz" : "unresolved", reason,
  };
  render(<Results result={{ ...result, fields: key === "authority_code" ? {} : { [key]: field },
    other_fields: key === "authority_code" ? [field] : [] }} />);
  const row = screen.getByText(heading).closest(".field-row") as HTMLElement;
  const notes = within(row).getByLabelText(`Reading notes for ${heading}`);
  expect(notes).toBeVisible();
  expect(notes.closest("details")).not.toHaveAttribute("open");
  expect(within(row).getByText(reason)).not.toBeVisible();
  expect(row.querySelector(":scope > p.field-reason")).toBeNull();
  if (value) {
    expect(within(row).getByText(value)).toBeVisible();
    expect(within(row).getByText("MRZ reading")).not.toBeVisible();
  }
  fireEvent.click(notes);
  expect(within(row).getByText(reason)).toBeVisible();
  if (value) expect(within(row).getByText("MRZ reading")).toBeVisible();
  fireEvent.click(notes);
  expect(within(row).getByText(reason)).not.toBeVisible();
});

it("does not add an empty dropdown to a field with no notes", () => {
  render(<Results result={result} />);
  const row = screen.getByText("Surname").closest(".field-row") as HTMLElement;
  expect(row.querySelector("details")).toBeNull();
  expect(within(row).getByText("SPECIMEN")).toBeVisible();
});

it.each([
  ["place_of_birth", "Place of Birth", "layout", { heading_unresolved: true },
    "Possible text found — field heading unclear"],
  ["date_of_issue", "Date of Issue", "visual", { calendar_date: false },
    "Date reading is invalid — check the original"],
  ["country_code", "Issuing Country Code", "mrz", {},
    "MRZ reading could not be confirmed"],
] as const)("explains why %s has no selected value without displaying a candidate as fact",
  (key, heading, source, validation, message) => {
    const field: FieldValue = {
      ...result.fields.surname, field_name: key, value: null, value_kind: "unresolved",
      source, status: "uncertain", validation, observed_value: "UNCONFIRMED READING",
      reason: "The original reading is retained for review.",
    };
    render(<Results result={{ ...result, fields: { [key]: field } }} />);
    const row = screen.getByText(heading).closest(".field-row") as HTMLElement;
    expect(within(row).getByText(message)).toBeVisible();
    expect(within(row).queryByText("UNCONFIRMED READING")).not.toBeInTheDocument();
    expect(within(row).queryByRole("button", { name: /^Copy/ })).not.toBeInTheDocument();
  });
