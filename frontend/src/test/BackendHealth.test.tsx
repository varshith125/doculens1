import { StrictMode } from "react";
import { act, renderHook } from "@testing-library/react";
import { afterEach, beforeEach, expect, it, vi } from "vitest";
import { useBackendHealth } from "@/hooks/useBackendHealth";
import { health } from "@/services/api";
import { healthResult } from "./fixtures";

vi.mock("@/services/api", async () => ({
  ...(await vi.importActual("@/services/api")),
  health: vi.fn(),
}));
beforeEach(() => {
  vi.useFakeTimers();
  vi.mocked(health).mockReset();
});
afterEach(() => {
  vi.useRealTimers();
});

it("connects immediately when the backend is running", async () => {
  vi.mocked(health).mockResolvedValue(healthResult);
  const { result } = renderHook(useBackendHealth);
  await act(async () => {});
  expect(result.current).toMatchObject({
    service: healthResult,
    checking: false,
    error: false,
  });
  await act(async () => {
    await vi.advanceTimersByTimeAsync(30_000);
  });
  expect(health).toHaveBeenCalledOnce();
});

it("automatically recovers from temporary proxy/startup failures", async () => {
  vi.mocked(health)
    .mockRejectedValueOnce(new Error("502"))
    .mockRejectedValueOnce(new Error("connection refused"))
    .mockResolvedValue(healthResult);
  const { result } = renderHook(useBackendHealth);
  await act(async () => {
    await vi.advanceTimersByTimeAsync(500);
  });
  expect(result.current).toMatchObject({ checking: true, error: false });
  await act(async () => {
    await vi.advanceTimersByTimeAsync(1000);
  });
  expect(result.current).toMatchObject({
    service: healthResult,
    checking: false,
    error: false,
  });
  expect(health).toHaveBeenCalledTimes(3);
});

it("stops after four failures and retains a working manual retry", async () => {
  vi.mocked(health).mockRejectedValue(new Error("offline"));
  const { result } = renderHook(useBackendHealth);
  await act(async () => {
    await vi.advanceTimersByTimeAsync(30_000);
  });
  expect(result.current).toMatchObject({
    service: null,
    checking: false,
    error: true,
  });
  expect(health).toHaveBeenCalledTimes(4);
  vi.mocked(health).mockResolvedValue(healthResult);
  await act(async () => {
    result.current.reconnect();
  });
  expect(result.current).toMatchObject({
    service: healthResult,
    checking: false,
    error: false,
  });
});

it("ignores StrictMode cleanup errors after a newer successful request", async () => {
  vi.mocked(health)
    .mockImplementationOnce(
      (signal) =>
        new Promise((_resolve, reject) =>
          signal?.addEventListener("abort", () =>
            reject(new DOMException("Aborted", "AbortError")),
          ),
        ),
    )
    .mockResolvedValue(healthResult);
  const { result } = renderHook(useBackendHealth, { wrapper: StrictMode });
  await act(async () => {});
  expect(result.current).toMatchObject({
    service: healthResult,
    error: false,
    checking: false,
  });
});

it("cancels pending requests and timers on unmount", async () => {
  let signal: AbortSignal | undefined;
  vi.mocked(health).mockImplementation((value) => {
    signal = value;
    return new Promise(() => {});
  });
  const { unmount } = renderHook(useBackendHealth);
  unmount();
  expect(signal?.aborted).toBe(true);
  expect(vi.getTimerCount()).toBe(0);
});

it("cancels a scheduled retry on unmount", async () => {
  vi.mocked(health).mockRejectedValue(new Error("offline"));
  const { unmount } = renderHook(useBackendHealth);
  await act(async () => {});
  expect(vi.getTimerCount()).toBe(1);
  unmount();
  expect(vi.getTimerCount()).toBe(0);
  await act(async () => {
    await vi.advanceTimersByTimeAsync(30_000);
  });
  expect(health).toHaveBeenCalledOnce();
});

it("bounds hung requests and reports model unavailability separately", async () => {
  vi.mocked(health).mockImplementation(
    (signal) =>
      new Promise((_resolve, reject) =>
        signal?.addEventListener("abort", () =>
          reject(new DOMException("Timeout", "AbortError")),
        ),
      ),
  );
  const { result } = renderHook(useBackendHealth);
  await act(async () => {
    await vi.advanceTimersByTimeAsync(20_000);
  });
  expect(result.current.error).toBe(true);
  expect(health).toHaveBeenCalledTimes(4);
  vi.mocked(health).mockResolvedValue({
    ...healthResult,
    status: "degraded",
    ocr_ready: false,
  });
  await act(async () => {
    result.current.reconnect();
  });
  await act(async () => {
    await vi.advanceTimersByTimeAsync(3500);
  });
  expect(result.current).toMatchObject({
    error: false,
    checking: false,
    service: { ocr_ready: false },
  });
});
