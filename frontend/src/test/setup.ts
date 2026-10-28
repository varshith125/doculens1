import "@testing-library/jest-dom/vitest";
import { cleanup } from "@testing-library/react";
import { afterEach, vi } from "vitest";

afterEach(cleanup);
Object.defineProperty(window, "matchMedia", {
  writable: true,
  value: vi.fn((media: string) => ({
    media,
    matches: media.includes("prefers-reduced-motion: reduce"),
    onchange: null,
    addEventListener: vi.fn(),
    removeEventListener: vi.fn(),
    addListener: vi.fn(),
    removeListener: vi.fn(),
    dispatchEvent: vi.fn(),
  })),
});
Object.defineProperty(URL, "createObjectURL", {
  writable: true,
  value: vi.fn(() => "blob:test-document"),
});
Object.defineProperty(URL, "revokeObjectURL", {
  writable: true,
  value: vi.fn(),
});
Object.defineProperty(navigator, "clipboard", {
  configurable: true,
  value: { writeText: vi.fn().mockResolvedValue(undefined) },
});
HTMLDialogElement.prototype.showModal = function () {
  this.open = true;
};
HTMLDialogElement.prototype.close = function () {
  this.open = false;
};
