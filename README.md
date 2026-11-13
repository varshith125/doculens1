# DocuLens

**A local document-reading and review application for passport and identity document images.**

DocuLens combines a React and TypeScript interface with a FastAPI backend. It prepares document images, reads printed text with local OCR models, identifies supported fields and machine-readable zones (MRZ), and presents the results with evidence for human review.

DocuLens is an assistance tool. It does not verify a person's identity, authenticate a document, or guarantee that an extracted value is correct. Review every result against the original image.

## Features

- Scan the front and optional back of a document.
- Rotate, crop, and straighten images before processing.
- Extract supported printed fields and parse TD1, TD2, and TD3 MRZ formats.
- Associate known multilingual captions with nearby values and retain OCR evidence for review.
- Handle different label and value sizes: relative text size can help associate a smaller caption with a larger printed answer. There is no fixed minimum label-font cutoff; very small or unclear text may still be missed by OCR.
- Show uncertainty and conflicting readings instead of silently treating them as verified facts.
- Copy reviewed values or export the result as JSON.
- Run OCR and image processing locally with OpenCV and ONNX Runtime. No document image or text is sent to a hosted service.
- An optional local Tesseract backup engine is discovered at startup; `GET /api/v1/health` reports whether it is usable on this machine.

## Run with Docker

The Docker image contains everything: the website, the API, the OCR and caption models, and
Tesseract. Only [Docker](https://www.docker.com/products/docker-desktop/) is needed.

```bash
docker compose up -d          # build (first time) and start
# open http://localhost:8000
docker compose down           # stop
```

The image is about 3 GB and the app needs about 2–3 GB of memory. The first start takes a minute
while the models load. Uploads are processed in memory only; the container's file system is
read-only.

To make the app reachable at a public address, set `DOCULENS_ALLOWED_HOSTS`,
`DOCULENS_ALLOWED_ORIGINS` and `DOCULENS_COOKIE_SECURE` in `docker-compose.yml`, and serve it
over HTTPS (for example behind a reverse proxy).

> The model files are not stored in Git because of their size. To build the image yourself, place
> them in `models/` as described in [models/README.md](models/README.md), or use a published image.

## Requirements for running without Docker

- Windows with PowerShell
- Python 3.12 (Python 3.11–3.13 is allowed by the backend package)
- Node.js 22 and npm
- Internet access for dependency installation and initial OCR model setup
- Approximately 4 GB of available memory recommended for local development

The first start may take longer while OCR models are initialized. Once dependencies and models are available locally, scans are processed on the computer.

## Quick start on Windows

Clone the repository, then run the commands from the `Doculens` project folder:

```powershell
git clone https://github.com/varshith125/Doculens.git
cd Doculens

py -3.12 -m venv .venv
.\.venv\Scripts\python.exe -m pip install -e ".\backend[dev]"
Copy-Item .env.example backend\.env

Push-Location frontend
npm.cmd ci
npm.cmd run build
Pop-Location

.\start.ps1
```

When startup finishes, open <http://127.0.0.1:8000>. The launcher binds to the local computer and serves the built website and API from the same address. Press **Ctrl+C** in PowerShell to stop the server.

`start.ps1` checks that the backend environment and frontend build exist; it does not install packages. If you prefer to start the backend directly, run this from the project root:

```powershell
Push-Location backend
..\.venv\Scripts\python.exe -m uvicorn app.main:app --host 127.0.0.1 --port 8000 --no-access-log
Pop-Location
```

## Development

Start the backend as described above. In a second PowerShell window, run the Vite development server:

```powershell
cd frontend
npm.cmd run dev
```

Open <http://127.0.0.1:5173>. Vite forwards API requests to the backend on port 8000. Keep the same hostname (`127.0.0.1`) for both addresses during a session.

## Tests and checks

Full results, in plain language, are in [testing-reports](testing-reports/README.md):
752 unit tests, 23 functional checks, 99.7 % accuracy on generated passports in eight photo
conditions, and 80 % on hand-checked real-world samples. Each report is a Jupyter
notebook that re-runs its tests.

Run backend checks from `backend/`:

```powershell
..\.venv\Scripts\python.exe -m pytest -q
..\.venv\Scripts\python.exe -m ruff check app tests
```

Run frontend checks from `frontend/`:

```powershell
npm.cmd test
npm.cmd run lint
npm.cmd run typecheck
npm.cmd run build
```

Some OCR integration checks are opt-in and require local OCR models. See [verification notes](docs/verification.md) and [multilingual extraction notes](docs/multilingual-visual-extraction.md) for scope and limitations.

## Data handling and limitations

- The scan pipeline uses local OCR models and does not send document images to a hosted OCR or AI service.
- Active scan data is held temporarily in backend process memory and expires according to `DOCULENS_RETENTION_SECONDS` (60 seconds by default). Clearing a scan removes its server-side result.
- Copying or exporting results moves information into the user's clipboard or chosen download location, which is outside the backend's retention controls.
- OCR can misread text, and recognition coverage has not been established for every country, document type, script, or image condition. Check the original image and supporting evidence.
- MRZ checks and confidence values can help with review but do not prove that a document or field is valid.
- The local launcher is intended for use on the same computer. This project does not provide organizational authentication or a production multi-user deployment configuration.

## Project documentation

- [Application architecture](docs/application-architecture.md)
- [API contract](docs/contract.md)
- [Field mapping](docs/passport-field-mapping.md)
- [Multilingual captions and visual value association](docs/multilingual-visual-extraction.md)
- [Verification notes](docs/verification.md)
- [Implementation review](docs/reports/implementation-review.md)

## Technology

| Area | Technologies |
| --- | --- |
| Web interface | React, TypeScript, Vite |
| API | FastAPI, Pydantic, Uvicorn |
| Image processing | Pillow, OpenCV, NumPy |
| OCR inference | RapidOCR, ONNX Runtime |
| Backend packaging | Python, `pyproject.toml` |
