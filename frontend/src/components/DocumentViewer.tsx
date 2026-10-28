import { useEffect, useRef, useState, type CSSProperties } from "react";
import {
  Crop,
  Image,
  LoaderCircle,
  RotateCw,
  ZoomIn,
  ZoomOut,
} from "lucide-react";
import { Button } from "@/components/ui/button";
import { imageBlob, isAbort } from "@/services/api";
import { useObjectUrl } from "@/hooks/useObjectUrl";
import type { ScanResult, Side, SideOptions } from "@/types/scan";

interface Props {
  original: string;
  result: ScanResult | null;
  side: Side;
  options: SideOptions;
  busy: boolean;
  onRotate: () => void;
  onCrop: () => void;
}

export function DocumentViewer({
  original,
  result,
  side,
  options,
  busy,
  onRotate,
  onCrop,
}: Props) {
  const [variant, setVariant] = useState<"corrected" | "original">("corrected");
  const [blob, setBlob] = useState<Blob | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [loading, setLoading] = useState(false);
  const [zoom, setZoom] = useState(1);
  const canvas = useRef<HTMLDivElement>(null);
  const corrected = useObjectUrl(blob);
  const scanId = result?.scan_id;
  useEffect(() => {
    setBlob(null);
    setError(null);
    setZoom(1);
    if (!scanId) {
      setLoading(false);
      return;
    }
    const controller = new AbortController();
    setLoading(true);
    void imageBlob(scanId, side, "corrected", controller.signal)
      .then((value) => {
        if (!controller.signal.aborted) setBlob(value);
      })
      .catch((error) => {
        if (!isAbort(error))
          setError(
            error instanceof Error ? error.message : "Preview unavailable.",
          );
      })
      .finally(() => {
        if (!controller.signal.aborted) setLoading(false);
      });
    return () => controller.abort();
  }, [scanId, side]);
  const showingCorrected = result && variant === "corrected" && corrected;
  const image = showingCorrected ? corrected : original;
  const metadata = result?.images.find((image) => image.side === side);
  return (
    <div className="viewer">
      <div className="viewer-top">
        <div className="segmented" aria-label="Image comparison">
          <button
            aria-pressed={variant === "corrected"}
            onClick={() => setVariant("corrected")}
          >
            Corrected
          </button>
          <button
            aria-pressed={variant === "original"}
            onClick={() => setVariant("original")}
          >
            Original
          </button>
        </div>
        <span className="image-side">
          {side === "front" ? "Front side" : "Reverse side"}
        </span>
      </div>
      <div
        className="image-canvas"
        ref={canvas}
        tabIndex={0}
        role="region"
        aria-label="Document preview. Zoom then scroll or use arrow keys to inspect."
        style={{ "--preview-zoom": zoom } as CSSProperties}
      >
        <div
          className="zoom-surface"
          style={{ width: `${zoom * 100}%`, minWidth: "100%" }}
        >
          <img
            src={image}
            alt={
              showingCorrected
                ? "Corrected document"
                : "Original document preview"
            }
            style={{
              maxHeight:
                "calc((var(--canvas-height) - 32px) * var(--preview-zoom))",
              width: "100%",
              transform: !showingCorrected
                ? `rotate(${options.rotation}deg)`
                : undefined,
            }}
          />
        </div>
        {loading && (
          <span className="preview-loading">
            <LoaderCircle size={16} className="spin" /> Loading corrected image
          </span>
        )}
        {busy && (
          <div className="scan-overlay">
            <span className="scan-line" />
          </div>
        )}
      </div>
      {error && (
        <p className="input-error" role="alert">
          {error} Original preview shown.
        </p>
      )}
      <div className="viewer-toolbar">
        <div className="toolbar-group">
          <Button
            variant="ghost"
            size="icon"
            onClick={() => setZoom(Math.max(1, zoom - 0.25))}
            disabled={zoom <= 1}
            aria-label="Zoom out"
          >
            <ZoomOut size={17} />
          </Button>
          <Button
            variant="ghost"
            size="sm"
            onClick={() => {
              setZoom(1);
              if (canvas.current) {
                canvas.current.scrollTop = 0;
                canvas.current.scrollLeft = 0;
              }
            }}
          >
            Fit
          </Button>
          <span className="zoom-label">{Math.round(zoom * 100)}%</span>
          <Button
            variant="ghost"
            size="icon"
            onClick={() => setZoom(Math.min(3, zoom + 0.25))}
            disabled={zoom >= 3}
            aria-label="Zoom in"
          >
            <ZoomIn size={17} />
          </Button>
        </div>
        <div className="toolbar-group">
          <Button variant="ghost" size="sm" disabled={busy} onClick={onRotate}>
            <RotateCw size={16} />
            <span>Rotate</span>
          </Button>
          <Button variant="ghost" size="sm" disabled={busy} onClick={onCrop}>
            <Crop size={16} />
            <span>Adjust crop</span>
          </Button>
        </div>
      </div>
      <div className="image-caption">
        <Image size={13} />
        <span>
          {metadata
            ? `${metadata.width} × ${metadata.height} · ${metadata.crop_applied ? "Perspective corrected" : "Full image preserved"}`
            : options.corners
              ? "Manual corners set · ready to scan"
              : "Original preserved · automatic crop on scan"}
        </span>
      </div>
    </div>
  );
}
