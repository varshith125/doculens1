import { useSyncExternalStore } from "react";
import type { Variants } from "framer-motion";

const REDUCE = "(prefers-reduced-motion: reduce)";

/** The visitor's reduced-motion preference, read with the standard media query. */
export function useReducedMotion(): boolean {
  return useSyncExternalStore(
    (notify) => {
      const query = window.matchMedia(REDUCE);
      query.addEventListener("change", notify);
      return () => query.removeEventListener("change", notify);
    },
    () => window.matchMedia(REDUCE).matches,
    () => true,
  );
}

/** Shared Framer Motion presets. Motion never gates content: with reduced
 *  motion (and in tests) every element renders in its final state. */
export const EASE = [0.22, 1, 0.36, 1] as const;

export const rise: Variants = {
  hidden: { opacity: 0, y: 8 },
  show: { opacity: 1, y: 0, transition: { duration: 0.24, ease: EASE } },
};

export const pop: Variants = {
  hidden: { opacity: 0, y: 6 },
  show: { opacity: 1, y: 0, transition: { duration: 0.24, ease: EASE } },
};

export function stagger(gap = 0.07, delay = 0): Variants {
  return {
    hidden: {},
    show: { transition: { staggerChildren: gap, delayChildren: delay } },
  };
}

/** Props for an element that animates in when mounted. */
export function useEntrance() {
  const reduced = useReducedMotion();
  return reduced
    ? ({ initial: false, animate: "show" } as const)
    : ({ initial: "hidden", animate: "show" } as const);
}

/** Props for an element that animates in when scrolled into view. */
export function useInView() {
  const reduced = useReducedMotion();
  return reduced
    ? ({ initial: false, animate: "show" } as const)
    : ({
        initial: "hidden",
        whileInView: "show",
        viewport: { once: true, margin: "-60px" },
      } as const);
}
