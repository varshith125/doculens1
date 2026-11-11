"""Install the pinned local multilingual encoder (no document data is sent).

Run from the repository root with .venv/Scripts/python scripts/setup_semantic_model.py.
"""

import argparse
import hashlib
import json
import os
import urllib.request
from pathlib import Path

MODEL = "sentence-transformers/paraphrase-multilingual-MiniLM-L12-v2"
REVISION = "ae06c001a2546bef168b9bf8f570ccb1a16aaa27"
FILES = {"onnx/model.onnx": "model.onnx", "tokenizer.json": "tokenizer.json"}
MODEL_SHA256 = "10f7a088420252b26caf819236ca2c9d2987afd0fc06fec7553b542a5655a05a"


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--directory", type=Path, default=Path(__file__).resolve().parents[1] / "models" / "semantic")
    args = parser.parse_args()
    args.directory.mkdir(parents=True, exist_ok=True)
    for remote, local in FILES.items():
        target = args.directory / local
        temporary = target.with_suffix(target.suffix + ".download")
        url = f"https://huggingface.co/{MODEL}/resolve/{REVISION}/{remote}"
        print(f"Downloading {remote}", flush=True)
        try:
            with urllib.request.urlopen(url, timeout=60) as response, temporary.open("wb") as stream:
                while chunk := response.read(1024 * 1024):
                    stream.write(chunk)
            if local == "model.onnx":
                with temporary.open("rb") as stream:
                    actual = hashlib.file_digest(stream, "sha256").hexdigest()
                if actual != MODEL_SHA256:
                    raise ValueError("Downloaded model checksum does not match the pinned release.")
            os.replace(temporary, target)
        finally:
            temporary.unlink(missing_ok=True)
    (args.directory / "manifest.json").write_text(
        json.dumps({"model": MODEL, "revision": REVISION, "pooling": "attention-mask mean"}, indent=2),
        encoding="utf-8",
    )
    print(f"Installed local semantic model in {args.directory}")


if __name__ == "__main__":
    main()
