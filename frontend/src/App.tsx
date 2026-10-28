import { useState } from "react";
import {
  ArrowRight,
  Check,
  ChevronRight,
  CircleHelp,
  Focus,
  Globe2,
  Layers2,
  LockKeyhole,
  ScanLine,
  ScanText,
  ShieldCheck,
  Sparkles,
  X,
} from "lucide-react";
import { Button } from "@/components/ui/button";
import { CropEditor } from "@/components/CropEditor";
import { DocumentViewer } from "@/components/DocumentViewer";
import { Progress } from "@/components/Progress";
import { Results } from "@/components/Results";
import { UploadArea } from "@/components/UploadArea";
import { useObjectUrl } from "@/hooks/useObjectUrl";
import { useScan } from "@/hooks/useScan";
import { useMotion } from "@/hooks/useMotion";
import { useBackendHealth } from "@/hooks/useBackendHealth";
import type {
  Corners,
  Rotation,
  ScanOptions,
  Side,
  Uploads,
} from "@/types/scan";

const initialOptions = (): ScanOptions => ({
  front: { rotation: 0, corners: null },
  back: { rotation: 0, corners: null },
  language: "latin",
  date_order: "dmy",
});

export default function App() {
  const motionRoot = useMotion("page");
  const [files, setFiles] = useState<Uploads>({ front: null, back: null });
  const [options, setOptions] = useState<ScanOptions>(initialOptions);
  const [side, setSide] = useState<Side>("front");
  const [compareOpen, setCompareOpen] = useState(false);
  const [cropOpen, setCropOpen] = useState(false);
  const {
    service,
    error: serviceError,
    checking,
    reconnect,
  } = useBackendHealth();
  const [helpOpen, setHelpOpen] = useState(false);
  const scanner = useScan();
  const frontUrl = useObjectUrl(files.front);
  const backUrl = useObjectUrl(files.back);
  const original = side === "front" ? frontUrl : backUrl;

  const changeFile = (target: Side, file: File | null) => {
    scanner.reset();
    setFiles((previous) => ({ ...previous, [target]: file }));
    setOptions((previous) => ({
      ...previous,
      [target]: { rotation: 0, corners: null },
    }));
    setSide(file ? target : "front");
  };
  const rotate = () => {
    const rotation =
      scanner.result?.images.find((image) => image.side === side)?.rotation ??
      options[side].rotation;
    scanner.reset();
    setOptions((previous) => ({
      ...previous,
      [side]: {
        ...previous[side],
        rotation: ((rotation + 90) % 360) as Rotation,
      },
    }));
  };
  const applyCrop = (corners: Corners) => {
    scanner.reset();
    setOptions((previous) => ({
      ...previous,
      [side]: { ...previous[side], corners },
    }));
    setCropOpen(false);
  };
  const clear = () => {
    scanner.reset();
    setFiles({ front: null, back: null });
    setOptions(initialOptions());
    setSide("front");
  };
  const canScan = files.front && service?.ocr_ready && !scanner.busy;
  return (
    <div className="app-shell" ref={motionRoot}>
      <a className="skip-link" href="#workspace">
        Skip to document workspace
      </a>
      <header className="site-header">
        <a className="brand" href="#" aria-label="DocuLens home">
          <span className="brand-symbol">
            <Focus size={25} strokeWidth={1.8} />
          </span>
          Docu<span>Lens</span>
          <span className="brand-beta">LOCAL EDITION</span>
        </a>
        <nav aria-label="Main navigation">
          <a href="#workspace" className="active">
            Workspace
          </a>
          <button
            aria-expanded={helpOpen}
            aria-controls="how-it-works"
            onClick={() => setHelpOpen((value) => !value)}
          >
            How it works
          </button>
        </nav>
        <div className="privacy-chip">
          <span />
          Private by design
          <LockKeyhole size={13} />
        </div>
      </header>
      <main>
        <section className="hero">
          <div className="hero-copy">
            <span className="eyebrow hero-eyebrow">
              <span /> A CLEARER WAY TO READ DOCUMENTS
            </span>
            <h1>
              Every detail.
              <br />
              <em>In focus.</em>
            </h1>
            <p>
              Turn passports and identity cards into clear, structured
              information. One image. A closer look.
            </p>
            <div className="hero-features">
              <span>
                <ShieldCheck size={15} />
                Local processing
              </span>
              <span>
                <Globe2 size={15} />
                International formats
              </span>
              <span>
                <Check size={15} />
                Evidence, not guesses
              </span>
            </div>
          </div>
          <div className="hero-note">
            <div className="note-symbol">
              <ScanText size={30} strokeWidth={1.4} />
            </div>
            <span className="eyebrow">LESS TYPING. MORE CLARITY.</span>
            <p>
              Your document,
              <br />
              with the details
              <br />
              <strong>already in place.</strong>
            </p>
            <span className="note-footer">
              Built for careful reading <ArrowRight size={15} />
            </span>
          </div>
        </section>
        {helpOpen && (
          <section
            id="how-it-works"
            className="help-panel"
            aria-label="How DocuLens works"
          >
            <div>
              <h2>A simple scan, with the evidence intact.</h2>
              <p>
                Upload one document image, and optionally its reverse. Review
                the detected crop, readable fields and their original text.
                Adjust the corners or rotation and scan again when needed.
              </p>
              <p>
                Images are processed by this local backend and kept in memory
                for up to {Math.round((service?.retention_seconds ?? 900) / 60)}{" "}
                minutes. Clear a scan to delete it sooner. Downloaded exports
                and clipboard contents remain under your control.
              </p>
              <p>
                OCR can misread characters. A passing MRZ checksum checks
                transcription, not identity or document authenticity. Document
                layouts and languages vary; review every important value.
              </p>
            </div>
            <Button
              variant="ghost"
              size="icon"
              aria-label="Close help"
              onClick={() => setHelpOpen(false)}
            >
              <X size={18} />
            </Button>
          </section>
        )}
        <section
          id="workspace"
          tabIndex={-1}
          className="workspace"
          aria-label="Document scanning workspace"
        >
          <div className="workspace-heading">
            <div className="workspace-title">
              <span className="workspace-number">01</span>
              <div>
                <h2>Your scanning workspace</h2>
                <p>A little less paperwork starts here.</p>
              </div>
            </div>
            <div
              className={`engine-state ${service?.ocr_ready ? "online" : ""}`}
              role="status"
            >
              <span />
              {checking
                ? "Connecting to local engine"
                : serviceError
                  ? "Backend unavailable"
                  : !service
                    ? "Connecting to local engine"
                    : service.ocr_ready
                      ? "Local engine ready"
                      : "OCR model unavailable"}
            </div>
          </div>
          {!checking && (serviceError || (service && !service.ocr_ready)) && (
            <div className="service-warning" role="alert">
              <CircleHelp size={18} />
              <p>
                {serviceError
                  ? "The local backend is not responding. Start the FastAPI server, then reconnect."
                  : "The OCR model could not start. Check the backend installation and restart it."}
              </p>
              <Button variant="outline" size="sm" onClick={reconnect}>
                Reconnect
              </Button>
            </div>
          )}
          <div
            className={`workspace-grid ${scanner.result ? "has-results" : ""} ${compareOpen ? "compare-open" : ""}`}
          >
            {scanner.result && (
              <button
                className="compare-toggle"
                aria-expanded={compareOpen}
                aria-controls="comparison-preview"
                onClick={() => setCompareOpen((value) => !value)}
              >
                {compareOpen
                  ? "Hide document comparison"
                  : "Compare with document"}
              </button>
            )}
            <div className="document-panel" id="comparison-preview">
              <div className="panel-heading">
                <h3>
                  <Layers2 size={17} />
                  Document
                </h3>
                {files.front && (
                  <Button
                    variant="ghost"
                    size="sm"
                    disabled={scanner.busy}
                    onClick={clear}
                  >
                    Clear scan
                  </Button>
                )}
                <span className="panel-label">01 / INPUT</span>
              </div>
              {!files.front ? (
                <div className="upload-empty">
                  <UploadArea
                    side="front"
                    file={null}
                    onFile={changeFile}
                    maxMb={service?.max_upload_mb ?? 12}
                    disabled={scanner.busy}
                  />
                  <div className="upload-tip">
                    <Focus size={18} />
                    <p>
                      A good scan starts with a good photo.
                      <br />
                      <span>
                        Keep all four corners visible and avoid glare.
                      </span>
                    </p>
                  </div>
                </div>
              ) : (
                <div className="document-loaded">
                  {files.back && (
                    <div className="side-tabs" aria-label="Document side">
                      <button
                        aria-pressed={side === "front"}
                        onClick={() => setSide("front")}
                      >
                        Front
                      </button>
                      <button
                        aria-pressed={side === "back"}
                        onClick={() => setSide("back")}
                      >
                        Reverse
                      </button>
                    </div>
                  )}
                  {original && (
                    <DocumentViewer
                      original={original}
                      result={scanner.result}
                      side={side}
                      options={options[side]}
                      busy={scanner.busy}
                      onRotate={rotate}
                      onCrop={() => setCropOpen(true)}
                    />
                  )}
                  <details
                    className="scan-settings"
                    key={scanner.result ? "review" : "input"}
                    open={scanner.result ? undefined : true}
                  >
                    <summary>Upload and scan settings</summary>
                    <UploadArea
                      side="front"
                      file={files.front}
                      onFile={changeFile}
                      maxMb={service?.max_upload_mb ?? 12}
                      disabled={scanner.busy}
                    />
                    <UploadArea
                      side="back"
                      file={files.back}
                      onFile={changeFile}
                      compact
                      maxMb={service?.max_upload_mb ?? 12}
                      disabled={scanner.busy}
                    />
                    <div className="scan-controls">
                      <label htmlFor="date-order">
                        Printed date order
                        <select
                          id="date-order"
                          value={options.date_order}
                          disabled={scanner.busy}
                          onChange={(event) => {
                            scanner.reset();
                            setOptions((previous) => ({
                              ...previous,
                              date_order: event.target.value as
                                "dmy" | "mdy" | "auto",
                            }));
                          }}
                        >
                          <option value="dmy">Day / month / year</option>
                          <option value="mdy">Month / day / year</option>
                          <option value="auto">
                            Keep ambiguous dates as printed
                          </option>
                        </select>
                      </label>
                      <label htmlFor="ocr-language">
                        Reading language
                        <select
                          id="ocr-language"
                          value={options.language}
                          disabled={scanner.busy}
                          onChange={(event) => {
                            scanner.reset();
                            setOptions((previous) => ({
                              ...previous,
                              language: event.target.value as
                                "latin" | "arabic",
                            }));
                          }}
                        >
                          <option value="latin">Latin-script text</option>
                          {service?.languages.includes("arabic") && (
                            <option value="arabic">
                              Arabic · experimental
                            </option>
                          )}
                        </select>
                      </label>
                      {scanner.busy ? (
                        <Button variant="outline" onClick={scanner.cancel}>
                          Cancel scan
                        </Button>
                      ) : (
                        <Button
                          disabled={!canScan}
                          onClick={() => void scanner.scan(files, options)}
                        >
                          <ScanLine size={17} />
                          {scanner.result ? "Scan again" : "Scan document"}
                          <ArrowRight size={16} />
                        </Button>
                      )}
                    </div>
                  </details>
                </div>
              )}
            </div>
            <div className="information-panel">
              <div className="panel-heading">
                <h3>
                  <ScanText size={17} />
                  Extracted information
                </h3>
                <span className="panel-label">02 / OUTPUT</span>
              </div>
              {scanner.error && (
                <div className="scan-error" role="alert">
                  <CircleHelp size={19} />
                  <div>
                    <strong>Let’s take another look.</strong>
                    <p>{scanner.error}</p>
                  </div>
                </div>
              )}
              {scanner.busy ? (
                <Progress stage={scanner.stage} />
              ) : scanner.result ? (
                <Results result={scanner.result} />
              ) : (
                <div className="results-empty">
                  <div className="empty-orbit">
                    <ScanText size={36} strokeWidth={1.25} />
                    <span>
                      <Sparkles size={13} />
                    </span>
                  </div>
                  <span className="eyebrow">THE DETAILS WILL APPEAR HERE</span>
                  <h3>
                    A document goes in.
                    <br />
                    Clarity comes out.
                  </h3>
                  <p>
                    We find the text, connect the fields,
                    <br className="desktop-break" /> and show you where every
                    value came from.
                  </p>
                  <div className="empty-steps">
                    <div>
                      <span>1</span>
                      <p>Upload your document</p>
                      <ChevronRight size={14} />
                    </div>
                    <div>
                      <span>2</span>
                      <p>Scan and check the crop</p>
                      <ChevronRight size={14} />
                    </div>
                    <div>
                      <span>3</span>
                      <p>Review, copy or export</p>
                      <Check size={14} />
                    </div>
                  </div>
                  <span className="empty-note">
                    <LockKeyhole size={12} />
                    No document data is sent to external AI services.
                  </span>
                </div>
              )}
            </div>
          </div>
          <div className="workspace-footer">
            <span>
              <ShieldCheck size={14} />
              Your files stay on your local server.
            </span>
            <button onClick={() => setHelpOpen((value) => !value)}>
              Privacy & reading notes <ArrowRight size={13} />
            </button>
          </div>
        </section>
        <section className="features-strip" aria-label="Scanning capabilities">
          <div>
            <span className="feature-icon">
              <Focus size={23} strokeWidth={1.5} />
            </span>
            <div>
              <h3>A better perspective</h3>
              <p>Automatic alignment, with a human final look.</p>
            </div>
          </div>
          <div>
            <span className="feature-icon">
              <ScanText size={23} strokeWidth={1.5} />
            </span>
            <div>
              <h3>Details with a source</h3>
              <p>Visible text, MRZ checks and clear uncertainty.</p>
            </div>
          </div>
          <div>
            <span className="feature-icon">
              <LockKeyhole size={23} strokeWidth={1.5} />
            </span>
            <div>
              <h3>Private from the start</h3>
              <p>Local OCR. Temporary storage. Your control.</p>
            </div>
          </div>
        </section>
      </main>
      <footer className="site-footer">
        <span className="footer-brand">
          <Focus size={16} />
          DocuLens
        </span>
        <span>A little focus changes everything.</span>
        <span>Thoughtfully local.</span>
      </footer>
      {cropOpen && original && (
        <CropEditor
          image={original}
          initial={
            options[side].corners ??
            (scanner.result?.images.find((image) => image.side === side)
              ?.corners as Corners | undefined) ??
            null
          }
          onApply={applyCrop}
          onClose={() => setCropOpen(false)}
        />
      )}
    </div>
  );
}
