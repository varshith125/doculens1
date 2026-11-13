"""Shared helpers for the DocuLens testing notebooks."""

import json
import os
import re
import socket
import subprocess
import sys
import time
from contextlib import contextmanager
from pathlib import Path

from IPython.display import Markdown, display

HERE = Path(__file__).resolve().parent
ROOT = HERE.parent


def upper_drive(path: Path) -> str:
    """Windows paths with a lowercase drive letter make Vitest load itself twice."""
    text = str(path)
    return text[0].upper() + text[1:] if len(text) > 1 and text[1] == ":" else text


_VENV_PY = ROOT / ".venv" / ("Scripts/python.exe" if os.name == "nt" else "bin/python")
PY = str(_VENV_PY if _VENV_PY.exists() else Path(sys.executable))
BACKEND = upper_drive(ROOT / "backend")
FRONTEND = upper_drive(ROOT / "frontend")
PROJECT = upper_drive(ROOT)
SYNTHETIC = ROOT / "synthetic-passports"


def run(command, cwd, env=None, shell=False):
    """Run a command; return (exit code, combined output, seconds)."""
    started = time.perf_counter()
    done = subprocess.run(command, cwd=cwd, env={**os.environ, **(env or {})}, shell=shell,
                          capture_output=True, text=True, encoding="utf-8", errors="replace")
    return done.returncode, done.stdout + done.stderr, time.perf_counter() - started


def table(headers, rows):
    lines = ["| " + " | ".join(headers) + " |", "|" + "---|" * len(headers)]
    lines += ["| " + " | ".join(str(cell) for cell in row) + " |" for row in rows]
    display(Markdown("\n".join(lines)))


def bar(fraction, width=30):
    filled = round(fraction * width)
    return "`" + "█" * filled + "░" * (width - filled) + f" {fraction:.1%}`"


def pytest_counts(output):
    """Counts from pytest's final summary line, such as '665 passed, 17 skipped'."""
    line = next((row for row in reversed(output.splitlines())
                 if re.search(r"\d+ (passed|failed)", row)), "")
    return {kind: int(n) for n, kind in re.findall(r"(\d+) (passed|failed|skipped|error)", line)}


def vitest_counts(output):
    passed = re.search(r"Tests\s+(?:\d+ failed \| )?(\d+) passed", output)
    failed = re.search(r"Tests\s+(\d+) failed", output)
    return {"passed": int(passed.group(1)) if passed else 0,
            "failed": int(failed.group(1)) if failed else 0}


@contextmanager
def running_server():
    """Start DocuLens on a free local port and yield its base URL."""
    import httpx

    with socket.socket() as probe:
        probe.bind(("127.0.0.1", 0))
        port = probe.getsockname()[1]
    server = subprocess.Popen(
        [PY, "-m", "uvicorn", "app.main:app", "--host", "127.0.0.1", "--port", str(port), "--no-access-log"],
        cwd=BACKEND, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
    base = f"http://127.0.0.1:{port}"
    try:
        for _ in range(120):
            try:
                if httpx.get(base + "/api/v1/health", timeout=2).json().get("ocr_ready"):
                    break
            except httpx.HTTPError:
                time.sleep(1)
        yield base
    finally:
        server.terminate()
        server.wait(timeout=30)


def synthetic_evaluation(variants, limit):
    """Score the generated passports; return per-scan rows from the evaluator's report."""
    if not (SYNTHETIC / "answers.json").exists():
        run([PY, "scripts/synthetic_passports.py", "generate", "--count", "24"], PROJECT)
    run([PY, "scripts/synthetic_passports.py", "evaluate", "--variants", variants, "--limit", str(limit)],
        PROJECT)
    return json.loads((SYNTHETIC / "report.json").read_text(encoding="utf-8"))


def accuracy(rows, key):
    """(correct, total) per group, where ``key(row, field)`` names the group."""
    groups: dict[str, list[int]] = {}
    for row in rows:
        for field, ok in row["checks"].items():
            group = groups.setdefault(key(row, field), [0, 0])
            group[0] += ok
            group[1] += 1
    return groups
