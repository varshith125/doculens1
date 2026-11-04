import {
  fireEvent,
  render,
  screen,
  waitFor,
  within,
} from "@testing-library/react";
import { expect, it, vi } from "vitest";
import { Results } from "@/components/Results";
import { CropEditor } from "@/components/CropEditor";
import { result } from "./fixtures";

it.each([true, false, null])(
  "shows MRZ immediately and copies exact characters when validation is %s",
  async (valid) => {
    const lines = [
      "P<UTOEXAMPLE<<ALEX<<<<<<<<<<<<",
      "A1234 567<UTO900403?M<<<<<<<<",
    ];
    render(
      <Results
        result={{
          ...result,
          mrz: {
            ...result.mrz,
            detected: valid !== null,
            raw_lines: lines,
            checksum_valid: valid,
            warnings: ["Check the incomplete source."],
          },
        }}
      />,
    );
    const mrz = screen.getByLabelText("Recognized MRZ");
    expect(
      screen.getByRole("heading", { name: "Machine-readable Zone (MRZ)" }),
    ).toBeVisible();
    expect(mrz).toBeVisible();
    expect(mrz.textContent).toBe(lines.join("\n"));
    expect(mrz.closest("details")).toBeNull();
    expect(mrz).toHaveAttribute("tabindex", "0");
    expect(screen.getByText("Check the incomplete source.")).not.toBeVisible();
    fireEvent.click(screen.getByRole("button", { name: "Copy MRZ" }));
    await waitFor(() =>
      expect(navigator.clipboard.writeText).toHaveBeenCalledWith(
        lines.join("\n"),
      ),
    );
  },
);

it("keeps document code in the normal fields and all diagnostics below MRZ", () => {
  render(
    <Results
      result={{
        ...result,
        other_fields: [
          { ...result.fields.surname, field_name: "document_code", value: "P" },
        ],
        ocr_lines: [
          {
            text: "RAW SAMPLE",
            confidence: 0.8,
            side: "front",
            bounding_box: [],
          },
        ],
      }}
    />,
  );
  expect(screen.getByText("Document Code")).toBeVisible();
  expect(
    screen.getByRole("button", { name: "Copy Document Code" }),
  ).toBeVisible();
  expect(
    screen.queryByText("Additional printed fields"),
  ).not.toBeInTheDocument();
  expect(screen.queryByText(/Front.*Line 1/)).not.toBeInTheDocument();
  expect(screen.queryByText(/text regions/)).not.toBeInTheDocument();
  expect(
    screen.queryByText("Original OCR text (optional)"),
  ).not.toBeInTheDocument();
  const details = screen.getByText("Technical details").closest("details")!;
  expect(document.querySelectorAll("details")).toHaveLength(1);
  expect(details).not.toHaveAttribute("open");
  for (const source of screen.getAllByText("Surname: SPECIMEN"))
    expect(source).not.toBeVisible();
  expect(
    screen
      .getByRole("heading", { name: "Machine-readable Zone (MRZ)" })
      .compareDocumentPosition(details) & Node.DOCUMENT_POSITION_FOLLOWING,
  ).toBeTruthy();
  fireEvent.click(screen.getByText("Technical details"));
  expect(
    screen.getByRole("region", { name: "Extracted OCR text" }),
  ).toBeVisible();
});

it("states MRZ not available for an ID without MRZ", () => {
  render(<Results result={{ ...result, document_type: "emirates_id" }} />);
  expect(screen.getByText("MRZ not available")).toBeVisible();
  expect(
    screen.queryByRole("button", { name: "Copy MRZ" }),
  ).not.toBeInTheDocument();
});

it("exports the original result including evidence and MRZ without altering date strings", async () => {
  vi.spyOn(HTMLAnchorElement.prototype, "click").mockImplementation(
    () => undefined,
  );
  const original = {
    ...result,
    mrz: { ...result.mrz, raw_lines: ["P<UTOEXAMPLE<<<"] },
  };
  render(<Results result={original} />);
  fireEvent.click(screen.getByRole("button", { name: "Export JSON" }));
  const blob = vi.mocked(URL.createObjectURL).mock.calls.at(-1)![0] as Blob;
  const text = await new Promise<string>((resolve) => {
    const reader = new FileReader();
    reader.onload = () => resolve(String(reader.result));
    reader.readAsText(blob);
  });
  expect(JSON.parse(text)).toEqual(original);
});

it("copies the observed value and exports structured JSON", async () => {
  const click = vi
    .spyOn(HTMLAnchorElement.prototype, "click")
    .mockImplementation(() => undefined);
  render(<Results result={result} />);
  fireEvent.click(screen.getByRole("button", { name: "Copy Surname" }));
  await waitFor(() =>
    expect(navigator.clipboard.writeText).toHaveBeenCalledWith("SPECIMEN"),
  );
  fireEvent.click(screen.getByRole("button", { name: /Export JSON/i }));
  expect(click).toHaveBeenCalledOnce();
  expect(URL.createObjectURL).toHaveBeenCalledWith(expect.any(Blob));
});

it("preserves source evidence and uncertainty in the results", () => {
  render(
    <Results
      result={{
        ...result,
        fields: {
          surname: {
            ...result.fields.surname,
            value: null,
            status: "conflicting",
            reason: "The two sides disagree.",
          },
        },
      }}
    />,
  );
  expect(screen.getByText("The two sides disagree.")).toBeInTheDocument();
  expect(
    screen.queryByRole("button", { name: "Copy Surname" }),
  ).not.toBeInTheDocument();
  expect(screen.getByText("Surname: SPECIMEN")).toBeInTheDocument();
});

it("shows a preferred name first and keeps evidence collapsed", async () => {
  render(
    <Results
      result={{
        ...result,
        fields: {
          full_name: {
            ...result.fields.surname,
            field_name: "full_name",
            value: "ALEX MORGAN EXAMPLE",
            confidence: 1,
            status: "conflicting",
            reason: "Other readings differ.",
          },
        },
      }}
    />,
  );
  expect(screen.getByText("ALEX MORGAN EXAMPLE")).toBeVisible();
  expect(screen.queryByText("Uncertain")).not.toBeInTheDocument();
  expect(screen.queryByText("Uncertain — review required")).not.toBeInTheDocument();
  expect(screen.queryByText("100% OCR")).not.toBeInTheDocument();
  expect(screen.getByText("100% OCR confidence")).not.toBeVisible();
  const reason = screen.getByText("Other readings differ.");
  expect(reason.closest("details")).not.toHaveAttribute("open");
  fireEvent.click(screen.getByRole("button", { name: "Copy Full Name" }));
  await waitFor(() =>
    expect(navigator.clipboard.writeText).toHaveBeenCalledWith(
      "ALEX MORGAN EXAMPLE",
    ),
  );
});

it("displays and copies ISO dates in day/month/year order", async () => {
  render(
    <Results
      result={{
        ...result,
        fields: {
          date_of_birth: {
            ...result.fields.surname,
            field_name: "date_of_birth",
            value: "1982-07-22",
          },
        },
      }}
    />,
  );
  expect(screen.getByText("22/07/1982")).toBeVisible();
  fireEvent.click(screen.getByRole("button", { name: "Copy Date Of Birth" }));
  await waitFor(() =>
    expect(navigator.clipboard.writeText).toHaveBeenCalledWith("22/07/1982"),
  );
});

it("shows full name before components and labels passport numbers", async () => {
  render(
    <Results
      result={{
        ...result,
        document_type: "passport",
        fields: {
          surname: result.fields.surname,
          full_name: {
            ...result.fields.surname,
            field_name: "full_name",
            value: "ALEX SPECIMEN",
          },
          document_number: {
            ...result.fields.surname,
            field_name: "document_number",
            value: "A12345678",
          },
        },
      }}
    />,
  );
  expect(document.querySelector(".field-label")).toHaveTextContent("Full Name");
  fireEvent.click(screen.getByRole("button", { name: "Copy Passport Number" }));
  await waitFor(() =>
    expect(navigator.clipboard.writeText).toHaveBeenCalledWith("A12345678"),
  );
});

it("formats and copies an Emirates ID with printed grouping", async () => {
  render(
    <Results
      result={{
        ...result,
        fields: {
          emirates_id_number: {
            ...result.fields.surname,
            field_name: "emirates_id_number",
            value: "784200012345671",
          },
        },
      }}
    />,
  );
  expect(screen.getByText("784-2000-1234567-1")).toBeVisible();
  fireEvent.click(
    screen.getByRole("button", { name: "Copy Emirates Id Number" }),
  );
  await waitFor(() =>
    expect(navigator.clipboard.writeText).toHaveBeenCalledWith(
      "784-2000-1234567-1",
    ),
  );
});

it("does not invent fields for unmatched text and keeps the raw transcript optional", async () => {
  const texts = [
    "EXAMPL",
    "ALEX M0RGAN",
    "M",
    "21011961",
    "TESTCITY",
    "AN0THER",
    "25T3/2025",
  ];
  const lines = texts.map((text, index) => ({
    text,
    confidence: index === 0 ? 0.52 : 0.78,
    side: "front" as const,
    bounding_box: [
      [0, 0],
      [100, 0],
      [100, 20],
      [0, 20],
    ],
    observations:
      index === 0
        ? [
            { text, confidence: 0.52, method: "Initial reading" },
            { text: "EXA", confidence: 0.28, method: "Enlarged crop" },
          ]
        : [],
  }));
  render(<Results result={{ ...result, fields: {}, ocr_lines: lines }} />);
  for (const heading of [
    "Full Name",
    "Given Names",
    "Surname",
    "Date Of Birth",
    "Passport Number",
    "Date Of Issue",
    "Date Of Expiry",
  ]) {
    expect(screen.queryByText(heading)).not.toBeInTheDocument();
  }
  expect(
    screen.getByText("Technical details").closest("details"),
  ).not.toHaveAttribute("open");
  fireEvent.click(screen.getByText("Technical details"));
  const transcript = screen.getByRole("region", { name: "Extracted OCR text" });
  for (const text of texts) {
    const mainReading = within(transcript)
      .getAllByText(text)
      .find((element) => element.tagName === "CODE");
    expect(mainReading).toBeVisible();
    expect(mainReading?.closest("details")).toHaveAttribute("open");
  }
  expect(screen.getByText("DOCUMENT DETAILS")).toBeVisible();
  expect(
    screen.getByText("Text found, but fields could not be matched"),
  ).toBeVisible();
  expect(
    screen.queryByText("No reliable fields found"),
  ).not.toBeInTheDocument();
  expect(
    screen.queryByRole("button", { name: "Copy fields" }),
  ).not.toBeInTheDocument();
  expect(
    within(transcript).getByText("EXA").closest("details"),
  ).toHaveAttribute("open");
  fireEvent.click(
    within(transcript).getByRole("button", { name: "Copy OCR text" }),
  );
  await waitFor(() =>
    expect(navigator.clipboard.writeText).toHaveBeenCalledWith(
      texts.join("\n"),
    ),
  );
});

it("keeps unmatched OCR text available below extracted fields", () => {
  render(
    <Results
      result={{
        ...result,
        ocr_lines: [
          {
            text: "UNCLASSIFIED PRINTED TEXT",
            confidence: 0.6,
            side: "back",
            bounding_box: [],
          },
        ],
      }}
    />,
  );
  expect(screen.getByText("SPECIMEN")).toBeVisible();
  fireEvent.click(screen.getByText("Technical details"));
  expect(
    within(
      screen.getByRole("region", { name: "Extracted OCR text" }),
    ).getAllByText("UNCLASSIFIED PRINTED TEXT")[0],
  ).toBeVisible();
  expect(screen.getByRole("button", { name: "Copy fields" })).toBeEnabled();
});

it("shows the empty state only when neither fields nor OCR text were read", () => {
  render(<Results result={{ ...result, fields: {}, ocr_lines: [] }} />);
  expect(screen.getByText("No readable text found")).toBeVisible();
  expect(
    screen.queryByRole("button", { name: "Copy OCR text" }),
  ).not.toBeInTheDocument();
});

it("keeps given names separate from surname in rendering and copying", async () => {
  render(
    <Results
      result={{
        ...result,
        fields: {
          given_names: {
            ...result.fields.surname,
            field_name: "given_names",
            value: "VENKATA VARSHITH",
          },
          surname: { ...result.fields.surname, value: "GUMMADI" },
          full_name: {
            ...result.fields.surname,
            field_name: "full_name",
            value: "VENKATA VARSHITH GUMMADI",
          },
        },
      }}
    />,
  );
  expect(screen.getByText("VENKATA VARSHITH")).toBeVisible();
  fireEvent.click(screen.getByRole("button", { name: "Copy Given Names" }));
  await waitFor(() =>
    expect(navigator.clipboard.writeText).toHaveBeenCalledWith(
      "VENKATA VARSHITH",
    ),
  );
});

it("preserves printed first, middle and last name headings in display and copy", async () => {
  render(
    <Results
      result={{
        ...result,
        fields: {
          given_names: {
            ...result.fields.surname,
            field_name: "given_names",
            display_label: "First Name",
            value: "ALEX",
          },
          middle_names: {
            ...result.fields.surname,
            field_name: "middle_names",
            display_label: "Middle Name",
            value: "MORGAN",
          },
          surname: {
            ...result.fields.surname,
            display_label: "Last Name",
            value: "EXAMPLE",
          },
        },
      }}
    />,
  );
  for (const heading of ["First Name", "Middle Name", "Last Name"])
    expect(screen.getByText(heading)).toBeVisible();
  expect(screen.queryByText("Given Names")).not.toBeInTheDocument();
  fireEvent.click(screen.getByRole("button", { name: "Copy fields" }));
  await waitFor(() =>
    expect(navigator.clipboard.writeText).toHaveBeenCalledWith(
      "First Name: ALEX\nMiddle Name: MORGAN\nLast Name: EXAMPLE",
    ),
  );
});

it("shows unreadable dates under their headings without presenting raw garbage as a date", () => {
  render(
    <Results
      result={{
        ...result,
        fields: {
          date_of_birth: {
            ...result.fields.surname,
            field_name: "date_of_birth",
            value: null,
            status: "uncertain",
            evidence: [
              { ...result.fields.surname.evidence[0], raw_text: "1961110112" },
            ],
          },
        },
      }}
    />,
  );
  const row = screen
    .getByText("Date Of Birth")
    .closest(".field-row") as HTMLElement;
  expect(within(row).getAllByText("Unreadable")[0]).toBeVisible();
  expect(screen.getByText("1961110112").closest("details")).not.toHaveAttribute(
    "open",
  );
  expect(
    screen.queryByRole("button", { name: "Copy Date Of Birth" }),
  ).not.toBeInTheDocument();
});

it("allows keyboard four-corner adjustment and applies normalized coordinates", () => {
  const apply = vi.fn();
  render(
    <CropEditor
      image="blob:test"
      initial={null}
      onApply={apply}
      onClose={() => undefined}
    />,
  );
  fireEvent.keyDown(screen.getByLabelText("Top left crop corner"), {
    key: "ArrowRight",
  });
  fireEvent.click(screen.getByRole("button", { name: "Apply crop" }));
  expect(apply).toHaveBeenCalledWith([
    [0.005, 0],
    [1, 0],
    [1, 1],
    [0, 1],
  ]);
});
