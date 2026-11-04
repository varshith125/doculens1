import { expect, it } from "vitest";
import { editField, reviewedResult } from "@/lib/review";
import { result } from "./fixtures";

it("keeps the extracted value and evidence when the user edits a field", () => {
  const field = editField(result.fields.surname, "Example");
  expect(field.value).toBe("EXAMPLE");
  expect(field.extracted_value).toBe("SPECIMEN");
  expect(field.source).toBe("user");
  expect(field.confidence).toBeNull();
  expect(field.evidence).toEqual(result.fields.surname.evidence);
  expect(reviewedResult(result, { surname: field }).fields.surname.value).toBe("EXAMPLE");
});

it("rejects impossible dates and ambiguous date edits", () => {
  const field = { ...result.fields.surname, field_name: "date_of_birth" };
  expect(() => editField(field, "2024-02-31")).toThrow();
  expect(() => editField(field, "01/02/2024")).toThrow();
  expect(editField(field, "2024-02-29").value).toBe("2024-02-29");
});
