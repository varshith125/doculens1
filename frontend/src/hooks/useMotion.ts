import { useEffect, useRef } from "react";

type MotionKind = "upload" | "progress" | "results" | "highlight" | "scan";

/** Scoped GSAP animations never gate rendering or document processing. */
export function useMotion(kind: MotionKind, changeKey: unknown = null) {
  const root = useRef<HTMLDivElement>(null);
  useEffect(() => {
    if ((kind === "highlight" || kind === "scan") && !changeKey) return;
    let disposed = false;
    let revert: (() => void) | undefined;
    void import("gsap")
      .then(({ gsap }) => {
        if (disposed || !root.current) return;
        const scope = root.current;
        const media = gsap.matchMedia();
        revert = () => media.revert();
        media.add(
          "(prefers-reduced-motion: no-preference)",
          () => {
            // Framer Motion owns panel entrances. GSAP only animates local
            // feedback and active processing; there are no idle background loops.
            const selectors = {
              upload: ".file-info, .file-icon, .upload-symbol",
              progress: "h3, .progress-description, .processing-steps .current",
              results: ".visible-mrz, .technical-details, .result-actions",
              highlight: ".evidence-overlay polygon",
              scan: ".scan-line",
            };
            const elements = selectors[kind]
              ? Array.from(scope.querySelectorAll(selectors[kind])).slice(0, 12)
              : [];
            if (elements.length) {
              gsap.from(elements, {
                y: 5,
                opacity: 0.72,
                duration: 0.24,
                stagger: 0.035,
                ease: "power2.out",
                clearProps: "transform,opacity",
              });
            }
            if (kind === "progress") {
              gsap.to(scope.querySelector(".progress-mark > span"), {
                rotation: 360,
                duration: 14,
                repeat: -1,
                ease: "none",
              });
            }
            if (kind === "scan") {
              gsap.fromTo(
                scope.querySelector(".scan-line"),
                { top: "10%" },
                {
                  top: "90%",
                  duration: 2,
                  repeat: -1,
                  yoyo: true,
                  ease: "sine.inOut",
                },
              );
            }
          },
          scope,
        );
      })
      .catch(() => {
        // Motion is optional: blocked or offline chunks must not hide the interface.
      });
    return () => {
      disposed = true;
      revert?.();
    };
  }, [kind, changeKey]);
  return root;
}
