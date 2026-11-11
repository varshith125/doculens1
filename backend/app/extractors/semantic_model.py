"""Local multilingual text meaning; never uses document label aliases.

The model is installed explicitly, not downloaded while processing a document.
Only model parameters and schema vectors are cached; OCR text is scan-local.
"""

from functools import lru_cache
from pathlib import Path
from threading import Lock
from typing import Protocol

import numpy as np


class SemanticUnavailable(RuntimeError):
    pass


class TextEncoder(Protocol):
    def encode(self, texts: list[str]) -> np.ndarray: ...

    def english_probability(self, text: str) -> float: ...


class LocalTextEncoder:
    def __init__(self, directory: str):
        root = Path(directory)
        if not all((root / name).is_file() for name in ("model.onnx", "tokenizer.json")):
            raise SemanticUnavailable("Local semantic model files are unavailable.")
        try:
            import onnxruntime as ort
            from lingua import Language, LanguageDetectorBuilder
            from tokenizers import Tokenizer

            self.tokenizer = Tokenizer.from_file(str(root / "tokenizer.json"))
            self.tokenizer.enable_truncation(max_length=128)
            self.tokenizer.enable_padding(pad_id=1, pad_token="<pad>")
            options = ort.SessionOptions()
            options.intra_op_num_threads = 2
            options.inter_op_num_threads = 1
            self.session = ort.InferenceSession(
                str(root / "model.onnx"), sess_options=options,
                providers=["CPUExecutionProvider"],
            )
            self.detector = LanguageDetectorBuilder.from_all_languages().with_low_accuracy_mode().build()
            self.english = Language.ENGLISH
            self.lock = Lock()
        except Exception as exc:
            # ORT exposes native load failures via several exception classes.
            raise SemanticUnavailable("Local semantic model could not be loaded.") from exc

    def english_probability(self, text: str) -> float:
        return self.detector.compute_language_confidence(text, self.english)

    def encode(self, texts: list[str]) -> np.ndarray:
        if not texts:
            return np.empty((0, 384), dtype=np.float32)
        chunks = []
        # Tokenizer padding state is mutable; serialize shared inference.
        with self.lock:
            for start in range(0, len(texts), 32):
                encoded = self.tokenizer.encode_batch(texts[start:start + 32])
                arrays = {
                    "input_ids": np.asarray([e.ids for e in encoded], dtype=np.int64),
                    "attention_mask": np.asarray([e.attention_mask for e in encoded], dtype=np.int64),
                    "token_type_ids": np.asarray([e.type_ids for e in encoded], dtype=np.int64),
                }
                inputs = {item.name: arrays[item.name] for item in self.session.get_inputs()}
                try:
                    tokens = self.session.run(None, inputs)[0]
                except Exception as exc:
                    raise SemanticUnavailable("Local semantic inference failed.") from exc
                mask = arrays["attention_mask"][..., None]
                vectors = (tokens * mask).sum(axis=1) / np.maximum(mask.sum(axis=1), 1)
                vectors /= np.maximum(np.linalg.norm(vectors, axis=1, keepdims=True), 1e-9)
                chunks.append(vectors.astype(np.float32))
        return np.concatenate(chunks)


@lru_cache(maxsize=1)
def get_encoder(directory: str) -> LocalTextEncoder:
    return LocalTextEncoder(directory)
