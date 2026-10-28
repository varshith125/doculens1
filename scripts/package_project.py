"""Create a source ZIP, excluding environments, caches, credentials and runtime data."""

import argparse
import os
from pathlib import Path
from zipfile import ZIP_DEFLATED, ZipFile

EXCLUDED = {
    ".venv",
    "node_modules",
    ".git",
    ".cache",
    ".npm-cache",
    ".uv-cache",
    "__pycache__",
    ".pytest_cache",
    ".ruff_cache",
    "dist",
    "test-results",
    "coverage",
    "models",
}


def package(destination: Path) -> int:
    root = Path(__file__).resolve().parents[1]
    count = 0
    with ZipFile(destination, "w", ZIP_DEFLATED) as archive:
        for directory, directories, filenames in os.walk(root):
            directories[:] = sorted(
                name
                for name in directories
                if name not in EXCLUDED and not name.endswith(".egg-info")
            )
            for filename in sorted(filenames):
                path = Path(directory) / filename
                if path.name == ".env" or path.suffix in {
                    ".pyc",
                    ".log",
                    ".tsbuildinfo",
                    ".zip",
                }:
                    continue
                archive.write(path, Path("doculens") / path.relative_to(root))
                count += 1
    return count


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("output", type=Path)
    args = parser.parse_args()
    print(f"Packaged {package(args.output.resolve())} source files into {args.output}")
