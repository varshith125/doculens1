import { Check, LoaderCircle, ScanLine } from "lucide-react";
import type { Stage } from "@/types/scan";
import { useMotion } from "@/hooks/useMotion";

const steps: { stages: Stage[]; title: string; detail: string }[] = [
  {
    stages: ["queued", "detecting_document", "correcting_alignment"],
    title: "Finding the right perspective",
    detail: "Locating document edges and checking image quality.",
  },
  {
    stages: ["reading_text"],
    title: "Reading your document",
    detail: "Reading the visible names, numbers and dates.",
  },
  {
    stages: ["validating_fields"],
    title: "Checking the details",
    detail: "Matching each detail to its label and checking the readings.",
  },
  {
    stages: ["preparing_results", "completed"],
    title: "Bringing it together",
    detail: "Preparing your corrected image and extracted information.",
  },
];

export function Progress({ stage }: { stage: Stage | null }) {
  const motionRoot = useMotion("progress", stage);
  const index = Math.max(
    0,
    steps.findIndex((step) => step.stages.includes(stage || "queued")),
  );
  return (
    <div
      ref={motionRoot}
      className="progress-panel"
      role="status"
      aria-live="polite"
      aria-atomic="true"
    >
      <div className="progress-mark">
        <ScanLine size={32} strokeWidth={1.5} />
        <span aria-hidden="true" />
      </div>
      <span className="eyebrow">PROCESSING ON YOUR COMPUTER</span>
      <h3>
        {stage === "queued" ? "Your scan is in the queue" : steps[index].title}
      </h3>
      <p className="progress-description">
        {stage === "queued"
          ? "Waiting for the local OCR worker to be ready."
          : steps[index].detail}
      </p>
      <ol className="processing-steps">
        {steps.map((step, i) => (
          <li
            key={step.title}
            className={i === index ? "current" : i < index ? "complete" : ""}
            aria-current={i === index ? "step" : undefined}
          >
            {i < index ? (
              <Check size={15} />
            ) : i === index ? (
              <LoaderCircle className="spin" size={15} />
            ) : (
              <span className="step-dot" />
            )}
            <span>
              {
                [
                  "Detect & align",
                  "Read visible text",
                  "Validate fields",
                  "Prepare results",
                ][i]
              }
            </span>
          </li>
        ))}
      </ol>
      <p className="processing-note">
        Actual processing stages · no estimated percentages
      </p>
    </div>
  );
}
