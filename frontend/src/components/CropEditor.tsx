import { useEffect, useRef, useState } from "react";
import { Crop, RotateCcw, X } from "lucide-react";
import { Button } from "@/components/ui/button";
import type { Corners, Point } from "@/types/scan";

const full: Corners = [
  [0, 0],
  [1, 0],
  [1, 1],
  [0, 1],
];
const names = ["Top left", "Top right", "Bottom right", "Bottom left"];

interface Props {
  image: string;
  initial: Corners | null;
  onApply: (corners: Corners) => void;
  onClose: () => void;
}

export function CropEditor({ image, initial, onApply, onClose }: Props) {
  const [corners, setCorners] = useState<Corners>(initial || full);
  const dialog = useRef<HTMLDialogElement>(null);
  const surface = useRef<HTMLDivElement>(null);
  const [active, setActive] = useState<number | null>(null);
  useEffect(() => {
    const element = dialog.current;
    element?.showModal();
    return () => element?.close();
  }, []);
  const move = (index: number, point: Point) =>
    setCorners(
      (previous) =>
        previous.map((p, i) =>
          i === index ? point.map((v) => Math.min(1, Math.max(0, v))) : p,
        ) as Corners,
    );
  return (
    <dialog
      ref={dialog}
      className="crop-dialog"
      aria-labelledby="crop-title"
      onCancel={onClose}
    >
      <div className="dialog-heading">
        <div>
          <span className="eyebrow">REFINE YOUR DOCUMENT</span>
          <h2 id="crop-title">Keep every detail in frame.</h2>
        </div>
        <Button
          variant="ghost"
          size="icon"
          onClick={onClose}
          aria-label="Close crop editor"
        >
          <X size={20} />
        </Button>
      </div>
      <p className="dialog-description">
        Move each corner to the document edge. Include the full machine-readable
        zone. Use arrow keys to fine-tune a selected corner.
      </p>
      <div
        ref={surface}
        className="crop-surface"
        onPointerMove={(event) => {
          if (active === null || !surface.current) return;
          const bounds = surface.current.getBoundingClientRect();
          move(active, [
            (event.clientX - bounds.left) / bounds.width,
            (event.clientY - bounds.top) / bounds.height,
          ]);
        }}
        onPointerUp={() => setActive(null)}
        onPointerCancel={() => setActive(null)}
      >
        <img
          src={image}
          alt="Original document for four-corner adjustment"
          draggable={false}
        />
        <svg
          className="crop-overlay"
          viewBox="0 0 1000 1000"
          preserveAspectRatio="none"
          aria-hidden="true"
        >
          <defs>
            <mask id="crop-mask">
              <rect width="1000" height="1000" fill="white" />
              <polygon
                points={corners
                  .map(([x, y]) => `${x * 1000},${y * 1000}`)
                  .join(" ")}
                fill="black"
              />
            </mask>
          </defs>
          <rect
            width="1000"
            height="1000"
            fill="rgba(13,38,35,.5)"
            mask="url(#crop-mask)"
          />
          <polygon
            points={corners
              .map(([x, y]) => `${x * 1000},${y * 1000}`)
              .join(" ")}
            fill="none"
            stroke="#d5f3ba"
            strokeWidth="4"
            vectorEffect="non-scaling-stroke"
          />
        </svg>
        {corners.map(([x, y], index) => (
          <button
            key={index}
            className="crop-handle"
            aria-label={`${names[index]} crop corner`}
            style={{ left: `${x * 100}%`, top: `${y * 100}%` }}
            onPointerDown={(event) => {
              event.preventDefault();
              event.currentTarget.focus();
              event.currentTarget.setPointerCapture(event.pointerId);
              setActive(index);
            }}
            onKeyDown={(event) => {
              const step = event.shiftKey ? 0.02 : 0.005;
              const change: Record<string, Point> = {
                ArrowLeft: [-step, 0],
                ArrowRight: [step, 0],
                ArrowUp: [0, -step],
                ArrowDown: [0, step],
              };
              if (change[event.key]) {
                event.preventDefault();
                move(index, [
                  x + change[event.key][0],
                  y + change[event.key][1],
                ]);
              }
            }}
          >
            <span>{index + 1}</span>
          </button>
        ))}
      </div>
      <div className="dialog-footer">
        <Button variant="ghost" onClick={() => setCorners(full)}>
          <RotateCcw size={15} /> Reset corners
        </Button>
        <Button onClick={() => onApply(corners)}>
          <Crop size={16} /> Apply crop
        </Button>
      </div>
    </dialog>
  );
}
