import {
  act,
  fireEvent,
  render,
  screen,
  waitFor,
} from "@testing-library/react";
import { beforeEach, describe, expect, it, vi } from "vitest";
import userEvent from "@testing-library/user-event";
import App from "@/App";
import * as api from "@/services/api";
import { healthResult, result } from "./fixtures";

vi.mock("@/services/api", async () => {
  const original =
    await vi.importActual<typeof import("@/services/api")>("@/services/api");
  return {
    ...original,
    health: vi.fn(),
    startScan: vi.fn(),
    getScan: vi.fn(),
    deleteScan: vi.fn(),
  };
});

beforeEach(() => {
  vi.clearAllMocks();
  vi.mocked(api.health).mockResolvedValue(healthResult);
  vi.mocked(api.startScan).mockResolvedValue({
    scan_id: result.scan_id,
    status: "queued",
    stage: "queued",
    result: null,
    error: null,
  });
  vi.mocked(api.getScan).mockResolvedValue({
    scan_id: result.scan_id,
    status: "completed",
    stage: "completed",
    result,
    error: null,
    previews: [],
  });
  vi.mocked(api.deleteScan).mockResolvedValue(undefined);
});

async function upload() {
  await screen.findByText("Local engine ready");
  const file = new File(["synthetic test image"], "specimen.png", {
    type: "image/png",
  });
  fireEvent.change(screen.getByLabelText("Upload document front"), {
    target: { files: [file] },
  });
  return file;
}

describe("Document workflow", () => {
  it("offers a keyboard skip link and associates upload errors with their control", async () => {
    const user = userEvent.setup();
    render(<App />);
    await screen.findByText("Local engine ready");
    await user.tab();
    const skip = screen.getByRole("link", {
      name: "Skip to document workspace",
    });
    expect(skip).toHaveFocus();
    expect(skip).toHaveAttribute("href", "#workspace");
    expect(document.getElementById("workspace")).toHaveAttribute(
      "tabindex",
      "-1",
    );
    const input = screen.getByLabelText("Upload document front");
    fireEvent.change(input, {
      target: {
        files: [new File(["x"], "bad.gif", { type: "image/gif" })],
      },
    });
    expect(input).toHaveAttribute("aria-invalid", "true");
    expect(input).toHaveAccessibleDescription(
      "Use a JPG, PNG or WebP image, or a single-page PDF.",
    );
  });
  it("previews an upload and displays actual API fields after scanning", async () => {
    render(<App />);
    const file = await upload();
    expect(screen.getByAltText("Original document preview")).toHaveAttribute(
      "src",
      "blob:test-document",
    );
    fireEvent.click(screen.getByRole("button", { name: "Scan document" }));
    expect(await screen.findByText("SPECIMEN")).toBeInTheDocument();
    expect(api.startScan).toHaveBeenCalledWith(
      expect.objectContaining({ front: file }),
      expect.objectContaining({ date_order: "dmy" }),
      expect.any(AbortSignal),
    );
    expect(screen.getByRole("button", { name: /Export JSON/i })).toBeEnabled();
  });
  it("provides a keyboard comparison toggle and preserves zoom, fit and scan settings", async () => {
    const user = userEvent.setup();
    render(<App />);
    await upload();
    fireEvent.click(screen.getByRole("button", { name: "Scan document" }));
    await screen.findByText("SPECIMEN");
    const toggle = screen.getByRole("button", {
      name: "Compare with document",
    });
    toggle.focus();
    await user.keyboard("{Enter}");
    expect(toggle).toHaveAttribute("aria-expanded", "true");
    expect(document.querySelector(".workspace-grid")).toHaveClass(
      "has-results",
      "compare-open",
    );
    const preview = screen.getByRole("region", { name: /Document preview/ });
    expect(preview).toHaveAttribute("tabindex", "0");
    fireEvent.click(screen.getByRole("button", { name: "Zoom in" }));
    expect(screen.getByText("125%")).toBeVisible();
    fireEvent.click(screen.getByRole("button", { name: "Fit" }));
    expect(screen.getByText("100%")).toBeVisible();
    expect(screen.getByRole("button", { name: "Rotate" })).toBeEnabled();
    expect(screen.getByRole("button", { name: "Adjust crop" })).toBeEnabled();
    fireEvent.click(screen.getByText("Upload and scan settings"));
    expect(screen.getByRole("button", { name: "Scan again" })).toBeVisible();
    await user.click(toggle);
    expect(toggle).toHaveAttribute("aria-expanded", "false");
    expect(screen.getByText("MRZ not available")).toBeVisible();
  });
  it("shows an actionable backend error", async () => {
    vi.mocked(api.health).mockRejectedValue(new Error("offline"));
    render(<App />);
    expect(
      await screen.findByRole("alert", {}, { timeout: 5000 }),
    ).toHaveTextContent("backend is not responding");
    expect(
      screen.getByRole("button", { name: "Reconnect" }),
    ).toBeInTheDocument();
  });
  it("rejects an unsupported upload before calling the API", async () => {
    render(<App />);
    await screen.findByText("Local engine ready");
    fireEvent.change(screen.getByLabelText("Upload document front"), {
      target: {
        files: [new File(["x"], "notes.txt", { type: "text/plain" })],
      },
    });
    expect(screen.getByRole("alert")).toHaveTextContent("single-page PDF");
    expect(api.startScan).not.toHaveBeenCalled();
  });
  it("accepts a PDF and sends it for scanning", async () => {
    render(<App />);
    await screen.findByText("Local engine ready");
    const pdf = new File(["%PDF-1.7"], "passport.pdf", {
      type: "application/pdf",
    });
    fireEvent.change(screen.getByLabelText("Upload document front"), {
      target: { files: [pdf] },
    });
    expect(screen.queryByRole("alert")).not.toBeInTheDocument();
    expect(screen.getByText(/PDF selected/)).toBeInTheDocument();
    fireEvent.click(screen.getByRole("button", { name: "Scan document" }));
    expect(await screen.findByText("SPECIMEN")).toBeInTheDocument();
    expect(api.startScan).toHaveBeenCalledWith(
      expect.objectContaining({ front: pdf }),
      expect.anything(),
      expect.any(AbortSignal),
    );
  });
  it("reports scan failure and allows another attempt", async () => {
    vi.mocked(api.getScan).mockResolvedValue({
      scan_id: "test",
      status: "failed",
      stage: "failed",
      result: null,
      error: "The image is damaged.",
    });
    render(<App />);
    await upload();
    fireEvent.click(screen.getByRole("button", { name: "Scan document" }));
    expect(await screen.findByRole("alert")).toHaveTextContent(
      "The image is damaged.",
    );
    expect(screen.getByRole("button", { name: "Scan document" })).toBeEnabled();
  });
  it("shows truthful stages and ignores a late result after cancellation", async () => {
    let complete:
      ((value: Awaited<ReturnType<typeof api.getScan>>) => void) | undefined;
    vi.mocked(api.getScan).mockImplementation(
      () =>
        new Promise((resolve) => {
          complete = resolve;
        }),
    );
    render(<App />);
    await upload();
    fireEvent.click(screen.getByRole("button", { name: "Scan document" }));
    await waitFor(() => expect(api.getScan).toHaveBeenCalled());
    expect(screen.getByText("Your scan is in the queue")).toBeInTheDocument();
    fireEvent.click(screen.getByRole("button", { name: "Cancel scan" }));
    await act(async () =>
      complete?.({
        scan_id: result.scan_id,
        status: "completed",
        stage: "completed",
        result,
        error: null,
      }),
    );
    expect(screen.queryByText("SPECIMEN")).not.toBeInTheDocument();
    expect(api.deleteScan).toHaveBeenCalledWith(result.scan_id);
  });
  it("shows the corrected page sent with the final reply", async () => {
    vi.mocked(api.getScan).mockResolvedValue({
      scan_id: result.scan_id,
      status: "completed",
      stage: "completed",
      result: {
        ...result,
        images: [
          {
            side: "front",
            width: 100,
            height: 70,
            corners: [
              [0, 0],
              [1, 0],
              [1, 1],
              [0, 1],
            ],
            crop_applied: false,
            rotation: 0,
            quality: {},
            warnings: [],
          },
        ],
      },
      error: null,
      previews: [
        { side: "front", variant: "corrected", jpeg_base64: btoa("jpeg") },
      ],
    });
    render(<App />);
    await upload();
    fireEvent.click(screen.getByRole("button", { name: "Scan document" }));
    expect(await screen.findByAltText("Corrected document")).toBeVisible();
    expect(screen.queryByRole("alert")).not.toBeInTheDocument();
  });
  it("needs no server cleanup once a scan is delivered", async () => {
    render(<App />);
    await upload();
    fireEvent.click(screen.getByRole("button", { name: "Scan document" }));
    await screen.findByText("SPECIMEN");
    fireEvent.click(screen.getByRole("button", { name: "Clear scan" }));
    expect(screen.queryByText("SPECIMEN")).not.toBeInTheDocument();
    expect(
      screen.getByRole("button", { name: /Browse files/i }),
    ).toBeInTheDocument();
    // The server deleted the scan itself when it delivered the result.
    expect(api.deleteScan).not.toHaveBeenCalled();
  });

  it("stops a timed-out scan and offers an actionable message", async () => {
    vi.mocked(api.getScan).mockImplementation(
      (_id, signal) =>
        new Promise((_resolve, reject) => {
          signal?.addEventListener(
            "abort",
            () => reject(new DOMException("Aborted", "AbortError")),
            { once: true },
          );
        }),
    );
    render(<App />);
    await upload();
    vi.useFakeTimers();
    try {
      fireEvent.click(screen.getByRole("button", { name: "Scan document" }));
      await act(async () => {
        await vi.advanceTimersByTimeAsync(300_000);
      });
      expect(screen.getByRole("alert")).toHaveTextContent(
        "The scan took too long",
      );
      expect(api.deleteScan).toHaveBeenCalledWith(result.scan_id);
      expect(
        screen.getByRole("button", { name: "Scan document" }),
      ).toBeEnabled();
    } finally {
      vi.useRealTimers();
    }
  });
});
