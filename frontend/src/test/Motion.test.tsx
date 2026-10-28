import { act, render, waitFor } from "@testing-library/react";
import { beforeEach, expect, it, vi } from "vitest";
import { useMotion } from "@/hooks/useMotion";

const motion = vi.hoisted(() => ({
  reduced: false,
  from: vi.fn(),
  to: vi.fn(),
  revert: vi.fn(),
  add: vi.fn(),
}));
vi.mock("gsap", () => ({
  gsap: {
    from: motion.from,
    to: motion.to,
    matchMedia: () => ({ add: motion.add, revert: motion.revert }),
  },
}));

beforeEach(() => {
  vi.clearAllMocks();
  motion.reduced = false;
  motion.add.mockImplementation((query: string, animate: () => void) => {
    if (query === "(prefers-reduced-motion: no-preference)" && !motion.reduced)
      animate();
  });
});

function Preview({ stage = "reading" }: { stage?: string }) {
  const ref = useMotion("progress", stage);
  return (
    <div ref={ref}>
      <h3>Reading document</h3>
      <div className="progress-mark">
        <span />
      </div>
    </div>
  );
}

it("scopes progress motion and reverts it on stage change and unmount", async () => {
  const { container, rerender, unmount } = render(<Preview />);
  await waitFor(() => expect(motion.add).toHaveBeenCalledOnce());
  expect(motion.add).toHaveBeenCalledWith(
    "(prefers-reduced-motion: no-preference)",
    expect.any(Function),
    container.firstChild,
  );
  expect(motion.to).toHaveBeenCalledWith(
    container.querySelector(".progress-mark > span"),
    expect.objectContaining({ repeat: -1 }),
  );
  rerender(<Preview stage="completed" />);
  await waitFor(() => expect(motion.add).toHaveBeenCalledTimes(2));
  expect(motion.revert).toHaveBeenCalledOnce();
  unmount();
  expect(motion.revert).toHaveBeenCalledTimes(2);
});

it("keeps content visible with reduced motion and starts no animations", async () => {
  motion.reduced = true;
  const { getByText } = render(<Preview />);
  await waitFor(() => expect(motion.add).toHaveBeenCalledOnce());
  expect(getByText("Reading document")).toBeVisible();
  expect(motion.from).not.toHaveBeenCalled();
  expect(motion.to).not.toHaveBeenCalled();
});

it("does not start a late animation after unmount", async () => {
  const { unmount } = render(<Preview />);
  unmount();
  await act(async () => {
    await import("gsap");
  });
  expect(motion.add).not.toHaveBeenCalled();
});
