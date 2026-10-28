import { useCallback, useEffect, useRef, useState } from "react";
import * as api from "@/services/api";
import type { ScanOptions, ScanResult, Stage, Uploads } from "@/types/scan";

interface ScanState {
  busy: boolean;
  stage: Stage | null;
  result: ScanResult | null;
  error: string | null;
}
const empty: ScanState = {
  busy: false,
  stage: null,
  result: null,
  error: null,
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

  useEffect(() => () => dispose(), [dispose]);

  const scan = useCallback(
    async (files: Uploads, options: ScanOptions) => {
      dispose();
      const run = generation.current;
      const active = new AbortController();
      controller.current = active;
      setState({ ...empty, busy: true, stage: "queued" });
      const timeout = setTimeout(
        () => active.abort(new DOMException("Scan timeout", "TimeoutError")),
        180_000,
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
          if (job.status === "failed")
            throw new Error(
              job.error ||
                "The document could not be read. Try a sharper, evenly lit image.",
            );
          if (job.status === "completed" && job.result) {
            setState({
              busy: false,
              stage: "completed",
              result: job.result,
              error: null,
            });
            return;
          }
          setState({ busy: true, stage: job.stage, result: null, error: null });
          await api.delay(650, active.signal);
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
