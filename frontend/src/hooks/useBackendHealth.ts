import { useEffect, useState } from "react";
import { delay, health } from "@/services/api";
import type { Health } from "@/types/scan";

const retryDelays = [0, 500, 1000, 2000];

export function useBackendHealth() {
  const [state, setState] = useState<{
    service: Health | null;
    checking: boolean;
    error: boolean;
  }>({
    service: null,
    checking: true,
    error: false,
  });
  const [generation, setGeneration] = useState(0);
  useEffect(() => {
    const lifetime = new AbortController();
    let request: AbortController | undefined;
    let requestTimeout: ReturnType<typeof setTimeout> | undefined;
    setState({ service: null, checking: true, error: false });
    void (async () => {
      let lastService: Health | null = null;
      for (const wait of retryDelays) {
        try {
          if (wait) await delay(wait, lifetime.signal);
          if (lifetime.signal.aborted) return;
          request = new AbortController();
          requestTimeout = setTimeout(() => request?.abort(), 4000);
          try {
            lastService = await health(request.signal);
            if (lifetime.signal.aborted) return;
            if (lastService.ocr_ready) {
              setState({ service: lastService, checking: false, error: false });
              return;
            }
          } finally {
            clearTimeout(requestTimeout);
          }
        } catch {
          if (lifetime.signal.aborted) return;
          lastService = null;
        }
      }
      if (!lifetime.signal.aborted) {
        setState({
          service: lastService,
          checking: false,
          error: lastService === null,
        });
      }
    })();
    return () => {
      lifetime.abort();
      request?.abort();
      clearTimeout(requestTimeout);
    };
  }, [generation]);
  return { ...state, reconnect: () => setGeneration((value) => value + 1) };
}
