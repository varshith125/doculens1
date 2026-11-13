# Model files

The model files are too large for Git, so this folder holds only this description.
The Docker image copies the whole folder in, so it must contain the files below
before `docker build`.

```text
models/
├── ocr/
│   ├── PP-OCRv6_det_small.onnx              text detection (small)
│   ├── PP-OCRv6_rec_small.onnx              text recognition (small, first pass)
│   ├── ch_ppocr_mobile_v2.0_cls_mobile.onnx text direction
│   ├── ppocrv6_dict.txt                     recognition alphabet
│   ├── medium-det/inference.onnx + .yml     text detection (medium, used by default)
│   └── medium-rec/inference.onnx + .yml     text recognition (medium, rereads)
├── semantic/
│   ├── model.onnx                           multilingual caption model
│   ├── tokenizer.json
│   └── manifest.json
└── arabic_PP-OCRv4_rec_mobile.onnx          Arabic recognition (optional)
```

| Files | Source | Licence |
|---|---|---|
| `ocr/*` small models, dictionary | [RapidOCR](https://github.com/RapidAI/RapidOCR) model hub, v3.10.0 | Apache-2.0 |
| `ocr/medium-*` | [PaddleOCR](https://github.com/PaddlePaddle/PaddleOCR) PP-OCRv6 medium, exported to ONNX | Apache-2.0 |
| `semantic/*` | [paraphrase-multilingual-MiniLM-L12-v2](https://huggingface.co/sentence-transformers/paraphrase-multilingual-MiniLM-L12-v2); install with `scripts/setup_semantic_model.py` | Apache-2.0 |
| `arabic_PP-OCRv4_rec_mobile.onnx` | RapidOCR model hub; install with `scripts/download_arabic_model.py` | Apache-2.0 |

About 630 MB in total.
