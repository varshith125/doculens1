import { useEffect, useRef } from "react";

type MotionKind = "page" | "upload" | "progress" | "results" | "highlight" | "scan";

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
            const selectors = {
              page: ".hero-copy, .hero-note, .workspace-heading",
              upload: ".file-info, .file-icon, .document-art",
              progress: "h3, .progress-description, .processing-steps .current",
              results: ".result-summary, [data-result-field]",
              highlight: ".evidence-overlay polygon",
              scan: ".scan-line",
            };
            const elements = Array.from(
              scope.querySelectorAll(selectors[kind]),
            ).slice(0, 12);
            if (elements.length) {
              gsap.from(elements, {
                y: kind === "page" ? 12 : 7,
                opacity: 0.72,
                duration: 0.38,
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
              gsap.fromTo(scope.querySelector(".scan-line"), { top: "10%" }, {
                top: "90%", duration: 2, repeat: -1, yoyo: true, ease: "sine.inOut",
              });
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
