"""Map local Paddle PP-OCRv6 Medium exports to RapidOCR 3.10 CPU stages."""

from pathlib import Path

import yaml
from rapidocr import ModelType


def medium_parameters(path: Path, stage: str, dictionary: Path) -> dict:
    if not path.is_file() or path.suffix.lower() != ".onnx":
        raise ValueError(f"Missing Medium {stage} ONNX file: {path}")
    sidecar = path.with_suffix(".yml")
    if not sidecar.is_file():
        raise ValueError(f"Missing Medium {stage} settings: {sidecar}")
    metadata = yaml.safe_load(sidecar.read_text(encoding="utf-8"))
    if metadata["Global"]["model_name"] != f"PP-OCRv6_medium_{stage.lower()}":
        raise ValueError(f"{sidecar} describes a different model or stage")
    ops = {
        key: value for op in metadata["PreProcess"]["transform_ops"] for key, value in op.items()
    }
    if ops["DecodeImage"]["img_mode"] != "BGR":
        raise ValueError(f"Unsupported Medium {stage} image channel order")
    post = metadata["PostProcess"]
    params = {f"{stage}.model_path": str(path), f"{stage}.model_type": ModelType.MEDIUM}
    if stage == "Rec":
        if not dictionary.is_file():
            raise ValueError(f"Medium recognition requires the local dictionary: {dictionary}")
        with dictionary.open(encoding="utf-8") as entries:
            alphabet = [line.rstrip("\n") for line in entries]
        if post["name"] != "CTCLabelDecode" or alphabet != post["character_dict"]:
            raise ValueError("Medium recognition YAML and the local CTC dictionary do not match")
        shape = ops["RecResizeImg"]["image_shape"]
        if shape != [3, 48, 320]:
            raise ValueError(f"Unsupported Medium recognition resize: {shape}")
        params.update({"Rec.rec_img_shape": shape, "Rec.rec_keys_path": str(dictionary)})
    else:
        norm = ops["NormalizeImage"]
        if norm["scale"] != "1./255." or norm["order"] != "hwc" or post["name"] != "DBPostProcess":
            raise ValueError("Unsupported Medium detector preprocessing or postprocessing")
        for key in ("mean", "std"):
            params[f"Det.{key}"] = norm[key]
        for key in ("thresh", "box_thresh", "max_candidates", "unclip_ratio"):
            params[f"Det.{key}"] = post[key]
        params["Det.use_dilation"] = post.get("use_dilation", False)
    return params


def check_medium_signature(stage: str, session, classes: int | None = None) -> None:
    inputs, outputs = session.get_inputs(), session.get_outputs()
    if len(inputs) == len(outputs) == 1 and inputs[0].type == outputs[0].type == "tensor(float)":
        image, result = inputs[0].shape, outputs[0].shape
        if (
            len(image) == 4
            and image[1] == 3
            and (
                (stage == "Det" and len(result) == 4 and result[1] == 1)
                or (
                    stage == "Rec" and image[2] == 48 and len(result) == 3 and result[-1] == classes
                )
            )
        ):
            return
    raise ValueError(f"Medium {stage} ONNX tensor signature does not match the configured decoder")
