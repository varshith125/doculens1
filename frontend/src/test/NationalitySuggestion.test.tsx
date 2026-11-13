import { fireEvent, render, screen, within } from "@testing-library/react";
import { expect, it, vi } from "vitest";
import { Results } from "@/components/Results";
import {
  canSuggestIndianNationality,
  missingNationality,
} from "@/lib/nationalitySuggestion";
import { result } from "./fixtures";

const indianIssuer = {
  ...result,
  fields: {
    nationality: missingNationality(),
    country_code: {
      ...result.fields.surname,
      field_name: "country_code",
      value: "IND",
      code: "IND",
    },
  },
};

async function exportResult() {
  vi.spyOn(HTMLAnchorElement.prototype, "click").mockImplementation(
    () => undefined,
  );
  fireEvent.click(screen.getByRole("button", { name: "Export JSON" }));
  const blob = vi.mocked(URL.createObjectURL).mock.calls.at(-1)![0] as Blob;
  const text = await new Promise<string>((resolve) => {
    const reader = new FileReader();
    reader.onload = () => resolve(String(reader.result));
    reader.readAsText(blob);
  });
  return JSON.parse(text);
}

it("keeps the suggestion out of the nationality value until explicitly confirmed", async () => {
  render(<Results result={indianIssuer} />);
  const row = screen
    .getByText("Nationality")
    .closest(".field-row") as HTMLElement;
  expect(
    within(row).getByText("Suggested nationality: Indian — please confirm"),
  ).toBeVisible();
  expect(
    within(row).queryByRole("button", { name: "Copy Nationality" }),
  ).toBeNull();
  expect((await exportResult()).fields.nationality.value).toBeNull();
  expect(
    screen.getByLabelText("Reading notes for Nationality").closest("details"),
  ).not.toHaveAttribute("open");
  fireEvent.click(
    within(row).getByRole("button", { name: "Confirm Indian nationality" }),
  );
  expect(within(row).getByText("Indian")).toBeVisible();
  expect(within(row).getByText("Edited")).toBeVisible();
  expect(within(row).queryByText(/Suggested nationality/)).toBeNull();
  const confirmed = (await exportResult()).fields.nationality;
  expect(confirmed.value).toBe("Indian");
  expect(confirmed.source).toBe("user");
  expect(confirmed.validation.user_confirmed_suggestion).toBe(true);
  expect(confirmed.status).toBe("uncertain");
  expect(indianIssuer.fields.nationality.value).toBeNull();
});

it("supports a completely missing nationality field and permits another nationality", () => {
  render(
    <Results
      result={{
        ...indianIssuer,
        fields: { country_code: indianIssuer.fields.country_code },
      }}
    />,
  );
  fireEvent.click(screen.getByRole("button", { name: "Edit Nationality" }));
  fireEvent.change(screen.getByLabelText("Edit Nationality"), {
    target: { value: "Nepalese" },
  });
  fireEvent.click(screen.getByRole("button", { name: "Save" }));
  expect(screen.getByText("Nepalese")).toBeVisible();
  expect(screen.queryByText(/Suggested nationality/)).toBeNull();
});

it("never overrides a readable nationality", () => {
  expect(
    canSuggestIndianNationality({
      ...indianIssuer,
      fields: {
        ...indianIssuer.fields,
        nationality: {
          ...indianIssuer.fields.nationality,
          value: "Nepalese",
          value_kind: "printed",
        },
      },
    }),
  ).toBe(false);
});

it("does not suggest when issuer is absent, conflicting, or contradictory", () => {
  expect(canSuggestIndianNationality(result)).toBe(false);
  expect(
    canSuggestIndianNationality({
      ...indianIssuer,
      fields: {
        ...indianIssuer.fields,
        country_code: {
          ...indianIssuer.fields.country_code,
          status: "conflicting",
        },
      },
    }),
  ).toBe(false);
  expect(
    canSuggestIndianNationality({ ...indianIssuer, issuing_country: "USA" }),
  ).toBe(false);
});
