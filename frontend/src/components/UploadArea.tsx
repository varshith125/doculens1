import { useRef, useState } from "react";
import { ArrowUpRight, FileImage, Plus, Upload, X } from "lucide-react";
import { Button } from "@/components/ui/button";
import { cn } from "@/lib/utils";
import { useMotion } from "@/hooks/useMotion";
import type { Side } from "@/types/scan";

const ACCEPTED_TYPES = [
  "image/jpeg",
  "image/png",
  "image/webp",
  "application/pdf",
];

interface Props {
  side: Side;
  file: File | null;
  onFile: (side: Side, file: File | null) => void;
  disabled?: boolean;
  maxMb: number;
  compact?: boolean;
}

export function UploadArea({
  side,
  file,
  onFile,
  disabled,
  maxMb,
  compact,
}: Props) {
  const input = useRef<HTMLInputElement>(null);
  const motionRoot = useMotion("upload", file);
  const [dragging, setDragging] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const choose = (files: FileList | null) => {
    setDragging(false);
    if (!files?.length) return;
    if (files.length > 1) {
      setError("Choose one image for this side. Add the reverse separately.");
      return;
    }
    const next = files[0];
    // Some systems report no type for a PDF, so its extension also counts.
    const pdf = next.type === "application/pdf" || /\.pdf$/i.test(next.name);
    if (!ACCEPTED_TYPES.includes(next.type) && !pdf) {
      setError("Use a JPG, PNG or WebP image, or a single-page PDF.");
      return;
    }
    if (next.size > maxMb * 1024 * 1024) {
      setError(`This image is too large. The limit is ${maxMb} MB per side.`);
      return;
    }
    setError(null);
    onFile(side, next);
  };
  return (
    <div
      ref={motionRoot}
      className={cn("upload-wrap", compact && "compact-upload")}
    >
      <input
        ref={input}
        type="file"
        className="sr-only"
        accept={[...ACCEPTED_TYPES, ".pdf"].join(",")}
        aria-label={`Upload document ${side}`}
        aria-describedby={error ? `upload-error-${side}` : undefined}
        aria-invalid={error ? "true" : "false"}
        disabled={disabled}
        onChange={(event) => {
          choose(event.target.files);
          event.target.value = "";
        }}
      />
      <div
        className={cn(
          "upload-area",
          dragging && "is-dragging",
          file && "has-file",
        )}
        onDragOver={(event) => {
          event.preventDefault();
          if (!disabled) setDragging(true);
        }}
        onDragLeave={(event) => {
          if (!event.currentTarget.contains(event.relatedTarget as Node | null))
            setDragging(false);
        }}
        onDrop={(event) => {
          event.preventDefault();
          if (!disabled) choose(event.dataTransfer.files);
        }}
      >
        {file ? (
          <>
            <span className="file-icon">
              <FileImage size={20} />
            </span>
            <div className="file-info">
              <strong>{file.name}</strong>
              <span>
                {side === "front" ? "Primary image" : "Reverse side"} ·{" "}
                {(file.size / 1024 / 1024).toFixed(1)} MB
              </span>
            </div>
            <Button
              variant="ghost"
              size="sm"
              disabled={disabled}
              onClick={() => input.current?.click()}
            >
              Replace
            </Button>
            <Button
              variant="ghost"
              size="icon"
              aria-label={`Remove ${side} image`}
              disabled={disabled}
              onClick={() => onFile(side, null)}
            >
              <X size={16} />
            </Button>
          </>
        ) : compact ? (
          <>
            <span className="add-side-icon">
              <Plus size={20} />
            </span>
            <div className="file-info">
              <strong>Add the reverse side</strong>
              <span>Optional · for two-sided identity cards</span>
            </div>
            <Button
              variant="outline"
              size="sm"
              disabled={disabled}
              onClick={() => input.current?.click()}
            >
              Add image
            </Button>
          </>
        ) : (
          <>
            <div className="upload-symbol" aria-hidden="true">
              <Upload size={28} strokeWidth={1.5} />
            </div>
            <h3>Drop your document here</h3>
            <p>
              Drag and drop a passport or identity card image, or choose a file
              below.
            </p>
            <Button disabled={disabled} onClick={() => input.current?.click()}>
              Browse files <ArrowUpRight size={17} />
            </Button>
            <span className="format-hint">
              JPG, PNG, WebP or PDF <span>·</span> Up to {maxMb} MB
            </span>
          </>
        )}
      </div>
      {error && (
        <p id={`upload-error-${side}`} className="input-error" role="alert">
          {error}
        </p>
      )}
    </div>
  );
}
