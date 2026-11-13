import type {
  Health,
  Preview,
  ScanJob,
  ScanOptions,
  Uploads,
} from "@/types/scan";

const base = "/api/v1";

async function checked(response: Response): Promise<Response> {
  if (response.ok) return response;
  const payload: unknown = await response.json().catch(() => null);
  const detail =
    payload && typeof payload === "object" && "detail" in payload
      ? payload.detail
      : null;
  throw new Error(
    typeof detail === "string"
      ? detail
      : `The request could not be completed (${response.status}). Please try again.`,
  );
}

export async function health(signal?: AbortSignal): Promise<Health> {
  return (
    await checked(
      await fetch(`${base}/health`, {
        signal,
        credentials: "same-origin",
        cache: "no-store",
      }),
    )
  ).json() as Promise<Health>;
}

export async function startScan(
  files: Uploads,
  options: ScanOptions,
  signal: AbortSignal,
): Promise<ScanJob> {
  await checked(
    await fetch(`${base}/session`, {
      method: "POST",
      signal,
      credentials: "same-origin",
    }),
  );
  if (!files.front) throw new Error("Add the document front before scanning.");
  const body = new FormData();
  body.append("front", files.front);
  if (files.back) body.append("back", files.back);
  body.append("options", JSON.stringify(options));
  return (
    await checked(
      await fetch(`${base}/scans`, {
        method: "POST",
        body,
        signal,
        credentials: "same-origin",
      }),
    )
  ).json() as Promise<ScanJob>;
}

export async function getScan(
  id: string,
  signal: AbortSignal,
): Promise<ScanJob> {
  return (
    await checked(
      await fetch(`${base}/scans/${encodeURIComponent(id)}`, {
        signal,
        credentials: "same-origin",
        cache: "no-store",
      }),
    )
  ).json() as Promise<ScanJob>;
}

export async function deleteScan(id: string): Promise<void> {
  await checked(
    await fetch(`${base}/scans/${encodeURIComponent(id)}`, {
      method: "DELETE",
      credentials: "same-origin",
      keepalive: true,
    }),
  );
}

export function previewBlob(preview: Preview): Blob {
  const bytes = Uint8Array.from(atob(preview.jpeg_base64), (char) =>
    char.charCodeAt(0),
  );
  return new Blob([bytes], { type: "image/jpeg" });
}

export function isAbort(error: unknown): boolean {
  return error instanceof Error && error.name === "AbortError";
}

export function delay(ms: number, signal: AbortSignal): Promise<void> {
  return new Promise((resolve, reject) => {
    if (signal.aborted) {
      reject(new DOMException("Aborted", "AbortError"));
      return;
    }
    const abort = () => {
      clearTimeout(timer);
      reject(new DOMException("Aborted", "AbortError"));
    };
    const timer = setTimeout(() => {
      signal.removeEventListener("abort", abort);
      resolve();
    }, ms);
    signal.addEventListener("abort", abort, { once: true });
  });
}
