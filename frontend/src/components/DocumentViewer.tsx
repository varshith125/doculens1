import { useEffect, useRef, useState, type CSSProperties } from "react";
import { Crop, Image, RotateCw, ZoomIn, ZoomOut } from "lucide-react";
import { Button } from "@/components/ui/button";
import { useObjectUrl } from "@/hooks/useObjectUrl";
import { useMotion } from "@/hooks/useMotion";
import type { FieldValue, ScanResult, Side, SideOptions } from "@/types/scan";

interface Props {
  correctedPreview: Blob | null;
  isPdf?: boolean;
  highlight?: FieldValue | null;
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
  isPdf,
  highlight,
  correctedPreview,
}: Props) {
  const motion = useMotion("highlight", highlight);
  const scanMotion = useMotion("scan", busy);
  const [variant, setVariant] = useState<"corrected" | "original">("corrected");
  const [zoom, setZoom] = useState(1);
  const canvas = useRef<HTMLDivElement>(null);
  const corrected = useObjectUrl(result ? correctedPreview : null);
  const scanId = result?.scan_id;
  useEffect(() => {
    setZoom(1);
  }, [scanId, side]);
  const showingCorrected = result && variant === "corrected" && corrected;
  const image = showingCorrected ? corrected : original;
  const metadata = result?.images.find((image) => image.side === side);
  const boxes =
    highlight?.evidence
      .filter(
        (item) =>
          item.side === side &&
          item.bounding_box &&
          (highlight.value_kind === "mrz"
            ? item.source === "mrz"
            : item.source === "visual"),
      )
      .map((item) => item.bounding_box!) ?? [];
  useEffect(() => {
    if (highlight) setVariant("corrected");
  }, [highlight]);
  return (
    <div className="viewer" ref={motion}>
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
          {isPdf && !showingCorrected ? (
            // The browser's own PDF viewer shows the page before scanning; the
            // scan then returns it as an image for highlighting and cropping.
            <object
              className="pdf-preview"
              data={`${original}#toolbar=0&navpanes=0&view=Fit`}
              type="application/pdf"
              aria-label="PDF document preview"
            >
              <p className="pdf-preview-note">
                This browser cannot display PDFs here. Scan the document to see
                its page.
              </p>
            </object>
          ) : (
            <div className="image-with-evidence">
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
              {showingCorrected && metadata && boxes.length > 0 && (
                <svg
                  className="evidence-overlay"
                  viewBox={`0 0 ${metadata.width} ${metadata.height}`}
                  preserveAspectRatio="xMidYMid meet"
                  aria-label="Selected field source location"
                >
                  {boxes.map((box, index) => (
                    <polygon
                      key={index}
                      points={box.map((point) => point.join(",")).join(" ")}
                    />
                  ))}
                </svg>
              )}
            </div>
          )}
        </div>
        {busy && (
          <div className="scan-overlay" ref={scanMotion}>
            <span className="scan-line" style={{ animation: "none" }} />
          </div>
        )}
      </div>
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
          <Button
            variant="ghost"
            size="sm"
            disabled={busy || isPdf}
            onClick={onCrop}
          >
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
