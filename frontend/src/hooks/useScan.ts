import { useCallback, useEffect, useRef, useState } from "react";
import * as api from "@/services/api";
import type {
  ScanJob,
  ScanOptions,
  ScanResult,
  Side,
  Stage,
  Uploads,
} from "@/types/scan";

type Previews = Partial<Record<Side, { original: Blob; corrected: Blob }>>;

function isPdf(file: File): boolean {
  return file.type === "application/pdf" || /\.pdf$/i.test(file.name);
}

/** Pair each side's corrected page with its original from the final reply. */
function readPreviews(job: ScanJob, files: Uploads): Previews {
  const previews: Previews = {};
  for (const { side } of job.result?.images ?? []) {
    const sent = (variant: "original" | "corrected") => {
      const preview = job.previews?.find(
        (item) => item.side === side && item.variant === variant,
      );
      return preview ? api.previewBlob(preview) : null;
    };
    const uploaded = files[side];
    // An uploaded photo is already in the browser; a PDF page comes back rendered.
    const original = uploaded && !isPdf(uploaded) ? uploaded : sent("original");
    const corrected = sent("corrected");
    if (original && corrected) previews[side] = { original, corrected };
  }
  return previews;
}

interface ScanState {
  busy: boolean;
  stage: Stage | null;
  result: ScanResult | null;
  error: string | null;
  previews: Previews;
}
const empty: ScanState = {
  busy: false,
  stage: null,
  result: null,
  error: null,
  previews: {},
};

export function useScan() {
  const [state, setState] = useState<ScanState>(empty);
  const controller = useRef<AbortController | null>(null);
  const currentId = useRef<string | null>(null);
  const generation = useRef(0);

  const dispose = useCallback(() => {
    generation.current += 1;
    controller.current?.abort();
    controller.current = null;
    if (currentId.current) {
      void api.deleteScan(currentId.current).catch(() => undefined);
      currentId.current = null;
    }
  }, []);

  const reset = useCallback(() => {
    dispose();
    setState(empty);
  }, [dispose]);
  const cancel = useCallback(() => {
    dispose();
    setState({
      ...empty,
      error: "Scan cancelled. Your images are ready when you are.",
    });
  }, [dispose]);

  useEffect(() => {
    window.addEventListener("pagehide", reset);
    return () => {
      window.removeEventListener("pagehide", reset);
      dispose();
    };
  }, [dispose, reset]);

  const scan = useCallback(
    async (files: Uploads, options: ScanOptions) => {
      dispose();
      const run = generation.current;
      const active = new AbortController();
      controller.current = active;
      setState({ ...empty, busy: true, stage: "queued" });
      const timeout = setTimeout(
        () => active.abort(new DOMException("Scan timeout", "TimeoutError")),
        300_000,
      );
      try {
        const started = await api.startScan(files, options, active.signal);
        if (run !== generation.current) {
          void api.deleteScan(started.scan_id).catch(() => undefined);
          return;
        }
        currentId.current = started.scan_id;
        while (!active.signal.aborted && run === generation.current) {
          const job = await api.getScan(started.scan_id, active.signal);
          if (run !== generation.current) return;
          if (job.status === "completed" || job.status === "failed") {
            // The server deleted the scan when it sent this final reply.
            currentId.current = null;
          }
          if (job.status === "failed")
            throw new Error(
              job.error ||
                "The document could not be read. Try a sharper, evenly lit image.",
            );
          if (job.status === "completed" && job.result) {
            clearTimeout(timeout);
            const previews = readPreviews(job, files);
            const missing = job.result.images.some(
              ({ side }) => !previews[side],
            );
            setState({
              busy: false,
              stage: "completed",
              result: job.result,
              error: missing
                ? "Extracted results are available, but a document preview could not be loaded."
                : null,
              previews,
            });
            return;
          }
          setState((previous) =>
            previous.stage === job.stage
              ? previous
              : { ...previous, stage: job.stage },
          );
          await api.delay(250, active.signal);
        }
      } catch (error) {
        if (run !== generation.current) return;
        const timedOut =
          active.signal.reason instanceof DOMException &&
          active.signal.reason.name === "TimeoutError";
        if (api.isAbort(error) && !timedOut) return;
        if (currentId.current) {
          void api.deleteScan(currentId.current).catch(() => undefined);
          currentId.current = null;
        }
        setState({
          ...empty,
          error: timedOut
            ? "The scan took too long. Try a smaller, clearer image or check the backend."
            : error instanceof Error
              ? error.message
              : "Unable to reach DocuLens. Check your connection and try again.",
        });
      } finally {
        clearTimeout(timeout);
      }
    },
    [dispose],
  );

  return { ...state, scan, cancel, reset };
}
