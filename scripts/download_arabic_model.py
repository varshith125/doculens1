"""Download the optional official Arabic recognizer; verify it before installation."""

import argparse
import hashlib
import tempfile
import urllib.request
from pathlib import Path

URL = "https://www.modelscope.cn/models/RapidAI/RapidOCR/resolve/v3.10.0/onnx/PP-OCRv4/rec/arabic_PP-OCRv4_rec_mobile.onnx"
SHA256 = "4a9011bef71687bb84288dc86ad2471bd5d37b717ddf672dd156f9e7a5601bac"
DEFAULT_OUTPUT = (
    Path(__file__).resolve().parents[1] / "models" / "arabic_PP-OCRv4_rec_mobile.onnx"
)


def download(destination: Path) -> None:
    destination.parent.mkdir(parents=True, exist_ok=True)
    if (
        destination.exists()
        and hashlib.sha256(destination.read_bytes()).hexdigest() == SHA256
    ):
        print(f"Verified Arabic model already installed: {destination}")
        return
    temporary = None
    try:
        with tempfile.NamedTemporaryFile(
            dir=destination.parent, suffix=".part", delete=False
        ) as output:
            temporary = Path(output.name)
            digest = hashlib.sha256()
            request = urllib.request.Request(
                URL, headers={"User-Agent": "DocuLens-model-setup/1.0"}
            )
            with urllib.request.urlopen(request, timeout=120) as response:
                size = 0
                while chunk := response.read(1024 * 1024):
                    size += len(chunk)
                    if size > 100 * 1024 * 1024:
                        raise ValueError("Unexpected model size; download rejected.")
                    digest.update(chunk)
                    output.write(chunk)
        if digest.hexdigest() != SHA256:
            raise ValueError(
                "Arabic model checksum did not match the official release."
            )
        temporary.replace(destination)
        print(f"Verified and installed Arabic model: {destination}")
    finally:
        if temporary is not None:
            temporary.unlink(missing_ok=True)


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output", type=Path, default=DEFAULT_OUTPUT)
    arguments = parser.parse_args()
    download(arguments.output.resolve())
