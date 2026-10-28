import { afterEach, expect, it, vi } from "vitest";
import { health } from "@/services/api";
import { healthResult } from "./fixtures";

afterEach(() => vi.unstubAllGlobals());
it("checks the same-origin API through the existing proxy without cached health data", async () => {
  const fetch = vi
    .fn()
    .mockResolvedValue(
      new Response(JSON.stringify(healthResult), { status: 200 }),
    );
  vi.stubGlobal("fetch", fetch);
  const signal = new AbortController().signal;
  expect(await health(signal)).toEqual(healthResult);
  expect(fetch).toHaveBeenCalledWith("/api/v1/health", {
    signal,
    credentials: "same-origin",
    cache: "no-store",
  });
});

it("does not treat a proxy error as a successful health response", async () => {
  vi.stubGlobal(
    "fetch",
    vi
      .fn()
      .mockResolvedValue(new Response("upstream unavailable", { status: 502 })),
  );
  await expect(health()).rejects.toThrow("502");
});
