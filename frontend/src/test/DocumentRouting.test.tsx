import { render, screen, within } from "@testing-library/react";
import { expect, it } from "vitest";
import { Results } from "@/components/Results";
import { TechnicalDetails } from "@/components/TechnicalDetails";
import { fieldHeading } from "@/lib/format";
import { result } from "./fixtures";

it("shows printed ID results without requiring MRZ", () => {
  render(<Results result={{ ...result, document_type: "emirates_id" }} />);
  expect(screen.getByRole("heading", { name: "Emirates ID" })).toBeVisible();
  expect(screen.getByText("MRZ not available")).toBeVisible();
  expect(screen.getByRole("button", { name: "Copy Surname" })).toBeVisible();
  expect(
    screen.queryByRole("button", { name: "Copy MRZ" }),
  ).not.toBeInTheDocument();
  expect(
    screen.queryByText("Review needed", { exact: true }),
  ).not.toBeInTheDocument();
});

it("does not report an absent MRZ as a failed check in diagnostics", () => {
  render(
    <TechnicalDetails
      result={result}
      fields={[]}
      onCopyOCR={() => undefined}
    />,
  );
  expect(screen.getByText(/MRZ validation was not performed/)).toBeVisible();
  expect(screen.queryByText(/Review needed/)).not.toBeInTheDocument();
  expect(screen.queryByText(/Checks passed/)).not.toBeInTheDocument();
});

it("still reports actual failed MRZ validation and preserves the raw lines", () => {
  const raw = ["I<UTOEXAMPLE<<<<<<<<<<<<<<<<<"];
  render(
    <Results
      result={{
        ...result,
        document_type: "identity_card",
        mrz: {
          ...result.mrz,
          detected: true,
          raw_lines: raw,
          checksum_valid: false,
        },
      }}
    />,
  );
  expect(screen.getByLabelText("Recognized MRZ").textContent).toBe(
    raw.join("\n"),
  );
  const details = screen.getByText("Technical details").closest("details")!;
  expect(within(details).getByText(/Review needed/)).toBeInTheDocument();
});

it("keeps a separately printed passport number distinct on an identity card", () => {
  const field = {
    ...result.fields.surname,
    field_name: "document_number",
    display_label: "Passport No",
  };
  expect(fieldHeading(field, "emirates_id")).toBe("Passport Number");
  expect(
    fieldHeading(
      { ...field, field_name: "mrz_document_number" },
      "emirates_id",
    ),
  ).toBe("MRZ Document Number");
});

it("shows the specific date-order problem beside the affected date without opening details", () => {
  render(
    <Results
      result={{
        ...result,
        fields: {
          date_of_issue: {
            ...result.fields.surname,
            field_name: "date_of_issue",
            display_label: "Date of issue",
            value: "2024-11-12",
            normalized_value: "2024-11-12",
            display_value: "2024-11-12",
            value_kind: "printed",
            status: "uncertain",
            evidence: [],
            validation: {
              issue_on_or_before_expiry: false,
              chronological_order: false,
            },
          },
        },
      }}
    />,
  );
  const field = screen
    .getByRole("button", { name: "Copy Date of Issue" })
    .closest<HTMLElement>(".field-row")!;
  expect(within(field).getByText("12-November-2024")).toBeVisible();
  expect(
    within(field).getByText(/Date of issue is later than date of expiry/),
  ).toBeVisible();
});
