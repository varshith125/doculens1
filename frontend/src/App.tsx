import { useEffect, useState } from "react";
import {
  ArrowRight,
  Check,
  ChevronRight,
  CircleHelp,
  Focus,
  Globe2,
  Layers2,
  LayoutDashboard,
  LockKeyhole,
  ScanLine,
  ScanText,
  ShieldCheck,
  X,
} from "lucide-react";
import { AnimatePresence, motion } from "framer-motion";
import { Button } from "@/components/ui/button";
import { Swap } from "@/components/Swap";
import {
  EASE,
  pop,
  rise,
  stagger,
  useEntrance,
  useInView,
  useReducedMotion,
} from "@/lib/motion";
import { CropEditor } from "@/components/CropEditor";
import { DocumentViewer } from "@/components/DocumentViewer";
import { Progress } from "@/components/Progress";
import { Results } from "@/components/Results";
import { UploadArea } from "@/components/UploadArea";
import { useObjectUrl } from "@/hooks/useObjectUrl";
import { useScan } from "@/hooks/useScan";
import { useBackendHealth } from "@/hooks/useBackendHealth";
import type {
  Corners,
  Rotation,
  ScanOptions,
  Side,
  Uploads,
  FieldValue,
} from "@/types/scan";

const initialOptions = (): ScanOptions => ({
  front: { rotation: 0, corners: null },
  back: { rotation: 0, corners: null },
  language: "latin",
  date_order: "dmy",
});

export default function App() {
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
  const [highlight, setHighlight] = useState<{
    scan: string;
    field: FieldValue;
  } | null>(null);
  const frontUrl = useObjectUrl(files.front);
  const backUrl = useObjectUrl(files.back);
  const original = side === "front" ? frontUrl : backUrl;
  const selectedPdf = files[side]?.type === "application/pdf";
  const pdfPage = selectedPdf
    ? (scanner.previews[side]?.original ?? null)
    : null;
  const pdfPageUrl = useObjectUrl(pdfPage);
  const cropImage = selectedPdf ? pdfPageUrl : original;

  const changeFile = (target: Side, file: File | null) => {
    scanner.reset();
    setHighlight(null);
    setFiles((previous) =>
      target === "front"
        ? { front: file, back: null }
        : { ...previous, back: file },
    );
    setOptions((previous) => ({
      ...previous,
      ...(target === "front"
        ? { back: { rotation: 0 as Rotation, corners: null } }
        : {}),
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
    setHighlight(null);
    setCropOpen(false);
    setCompareOpen(false);
  };
  useEffect(() => {
    const discardDocument = () => {
      setFiles({ front: null, back: null });
      setOptions(initialOptions());
      setHighlight(null);
      setCropOpen(false);
      setCompareOpen(false);
      setSide("front");
    };
    window.addEventListener("pagehide", discardDocument);
    return () => window.removeEventListener("pagehide", discardDocument);
  }, []);
  const canScan = files.front && service?.ocr_ready && !scanner.busy;
  const entrance = useEntrance();
  const inView = useInView();
  const reducedMotion = useReducedMotion();
  useEffect(() => {
    if (helpOpen) {
      document.getElementById("how-it-works")?.scrollIntoView?.({
        behavior: reducedMotion ? "instant" : "smooth",
        block: "start",
      });
    }
  }, [helpOpen, reducedMotion]);
  const currentStep = scanner.result ? 2 : files.front ? 1 : 0;
  const panelState = scanner.busy
    ? "scanning"
    : scanner.result
      ? `result-${scanner.result.scan_id}`
      : "empty";
  return (
    <div className="app-shell">
      <a className="skip-link" href="#workspace">
        Skip to document workspace
      </a>
      <header className="site-header">
        <a className="brand" href="#" aria-label="DocuLens home">
          <span className="brand-symbol">
            <Focus size={25} strokeWidth={1.8} />
          </span>
          <span className="brand-name">
            DocuLens<small>DOCUMENT WORKSPACE</small>
          </span>
        </a>
        <nav aria-label="Main navigation">
          <span className="nav-label">WORKSPACE</span>
          <a href="#workspace" className="active" aria-current="page">
            <LayoutDashboard size={18} /> Document scanner
          </a>
          <button
            aria-expanded={helpOpen}
            aria-controls="how-it-works"
            onClick={() => setHelpOpen((value) => !value)}
          >
            <CircleHelp size={18} /> How it works
          </button>
        </nav>
        <div className="sidebar-note">
          <LockKeyhole size={20} strokeWidth={1.5} />
          <strong>Local. Private. In your control.</strong>
          <p>
            Your documents are processed on this computer. No external AI
            services.
          </p>
          <span>
            LOCAL EDITION <span aria-hidden="true">/</span> 01
          </span>
        </div>
      </header>
      <div className="workspace-topbar">
        <div>
          <span>Workspace</span>
          <ChevronRight size={14} />
          <strong>Document scanner</strong>
        </div>
        <span className="privacy-chip">
          <LockKeyhole size={13} /> Local processing
        </span>
      </div>
      <main>
        <section className="hero">
          <motion.div
            className="hero-copy"
            variants={stagger(0.04)}
            {...entrance}
          >
            <motion.span className="eyebrow hero-eyebrow" variants={rise}>
              DOCUMENT INTELLIGENCE
            </motion.span>
            <motion.h1 variants={rise}>
              A clear view of every document.
            </motion.h1>
            <motion.p variants={rise}>
              Upload, extract and review passport or identity card details in
              one focused workspace.
            </motion.p>
            <motion.div className="hero-features" variants={rise}>
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
                Review with evidence
              </span>
            </motion.div>
          </motion.div>
        </section>
        <ol className="workflow-steps" aria-label="Document workflow">
          {[
            { title: "Upload document", detail: "Add a clear image" },
            { title: "Scan & extract", detail: "Read the document locally" },
            {
              title: "Review & export",
              detail: "Check details against the original",
            },
          ].map((step, index) => (
            <li
              key={step.title}
              className={
                index === currentStep
                  ? "is-current"
                  : index < currentStep
                    ? "is-complete"
                    : ""
              }
              aria-current={index === currentStep ? "step" : undefined}
            >
              <span className="workflow-number">
                {index < currentStep ? <Check size={16} /> : `0${index + 1}`}
              </span>
              <div>
                <strong>{step.title}</strong>
                <span>{step.detail}</span>
              </div>
              {index < 2 && (
                <ChevronRight
                  className="workflow-chevron"
                  size={16}
                  aria-hidden="true"
                />
              )}
            </li>
          ))}
        </ol>
        <AnimatePresence initial={false}>
          {helpOpen && (
            <motion.section
              id="how-it-works"
              className="help-panel"
              aria-label="How DocuLens works"
              initial={
                reducedMotion ? false : { opacity: 0, y: -12, scale: 0.98 }
              }
              animate={{ opacity: 1, y: 0, scale: 1 }}
              exit={
                reducedMotion ? undefined : { opacity: 0, y: -8, scale: 0.98 }
              }
              transition={{ duration: 0.3, ease: EASE }}
            >
              <div>
                <h2>A simple scan, with the evidence intact.</h2>
                <p>
                  Upload one document image, and optionally its reverse. Review
                  the detected crop, readable fields and their original text.
                  Adjust the corners or rotation and scan again when needed.
                </p>
                <p>
                  Each scan starts fresh. Uploaded images and extracted text are
                  processed in memory, without a disk cache or scan history. The
                  server releases them after the result and previews reach this
                  page. The current document stays in page memory until you
                  replace it, clear it or leave. Undelivered results expire{" "}
                  {service?.retention_seconds ?? 60} seconds after processing.
                  Downloaded exports and clipboard contents remain under your
                  control.
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
            </motion.section>
          )}
        </AnimatePresence>
        <motion.section
          id="workspace"
          tabIndex={-1}
          className="workspace"
          aria-label="Document scanning workspace"
          initial={reducedMotion ? false : { opacity: 0, y: 10 }}
          animate={{ opacity: 1, y: 0 }}
          transition={{ duration: 0.3, ease: EASE }}
        >
          <div className="workspace-heading">
            <div className="workspace-title">
              <span className="workspace-number">
                <ScanLine size={20} />
              </span>
              <div>
                <h2>Document workspace</h2>
                <p>
                  {scanner.result
                    ? "Review each value against your document before exporting."
                    : files.front
                      ? "Check the image, adjust if needed, then start your scan."
                      : "Start with the front of your document. Add the reverse if needed."}
                </p>
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
                      original={pdfPageUrl ?? original}
                      result={scanner.result}
                      correctedPreview={
                        scanner.previews[side]?.corrected ?? null
                      }
                      side={side}
                      options={options[side]}
                      busy={scanner.busy}
                      onRotate={rotate}
                      onCrop={() => setCropOpen(true)}
                      isPdf={selectedPdf && !pdfPageUrl}
                      highlight={
                        highlight?.scan === scanner.result?.scan_id
                          ? highlight?.field
                          : null
                      }
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
              <Swap id={panelState}>
                {scanner.busy ? (
                  <Progress stage={scanner.stage} />
                ) : scanner.result ? (
                  <Results
                    key={scanner.result.scan_id}
                    result={scanner.result}
                    onHighlight={(field) => {
                      setHighlight(
                        field ? { scan: scanner.result!.scan_id, field } : null,
                      );
                      const location = field?.evidence.find(
                        (item) => item.bounding_box,
                      );
                      if (location) setSide(location.side);
                    }}
                  />
                ) : (
                  <div className="results-empty">
                    <div className="empty-orbit">
                      <ScanText size={28} strokeWidth={1.5} />
                    </div>
                    <span className="eyebrow">READY WHEN YOU ARE</span>
                    <h3>Your document details, organised.</h3>
                    <p>
                      Extracted fields and their source evidence will appear
                      here after your scan.
                    </p>
                    <div className="field-preview" aria-hidden="true">
                      <div>
                        <span>Full name</span>
                        <i />
                      </div>
                      <div>
                        <span>Document number</span>
                        <i />
                      </div>
                      <div>
                        <span>Date of birth</span>
                        <i />
                      </div>
                    </div>
                    <span className="empty-note">
                      <LockKeyhole size={12} />
                      No document data is sent to external AI services.
                    </span>
                  </div>
                )}
              </Swap>
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
        </motion.section>
        <motion.section
          className="features-strip"
          aria-label="Scanning capabilities"
          variants={stagger(0.1)}
          {...inView}
        >
          <motion.div variants={pop}>
            <span className="feature-icon">
              <Focus size={23} strokeWidth={1.5} />
            </span>
            <div>
              <h3>Precise image preparation</h3>
              <p>Automatic alignment, with a human final look.</p>
            </div>
          </motion.div>
          <motion.div variants={pop}>
            <span className="feature-icon">
              <ScanText size={23} strokeWidth={1.5} />
            </span>
            <div>
              <h3>Evidence for every review</h3>
              <p>Visible text, MRZ checks and clear uncertainty.</p>
            </div>
          </motion.div>
          <motion.div variants={pop}>
            <span className="feature-icon">
              <LockKeyhole size={23} strokeWidth={1.5} />
            </span>
            <div>
              <h3>Private from the start</h3>
              <p>Local OCR. Temporary storage. Your control.</p>
            </div>
          </motion.div>
        </motion.section>
      </main>
      <footer className="site-footer">
        <span className="footer-brand">
          <Focus size={16} />
          DocuLens
        </span>
        <span>Document reading, with you in control.</span>
        <span>Local document processing</span>
      </footer>
      {cropOpen && cropImage && (
        <CropEditor
          image={cropImage}
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
