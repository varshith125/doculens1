param([int]$Port = 8000)
$ErrorActionPreference = 'Stop'
$projectRoot = $PSScriptRoot
$pythonExecutable = Join-Path $projectRoot '.venv\Scripts\python.exe'
if (-not (Test-Path -LiteralPath $pythonExecutable)) {
    throw 'Install the backend first. See README.md for the Python virtual environment commands.'
}
if (-not (Test-Path -LiteralPath (Join-Path $projectRoot 'frontend\dist\index.html'))) {
    throw 'Build the frontend first: cd frontend; npm install; npm run build'
}
Push-Location (Join-Path $projectRoot 'backend')
try {
    Write-Host "DocuLens will be available at http://127.0.0.1:$Port after the OCR model loads."
    & $pythonExecutable -m uvicorn app.main:app --host 127.0.0.1 --port $Port --no-access-log
} finally {
    Pop-Location
}
