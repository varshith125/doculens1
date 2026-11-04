from types import SimpleNamespace

import pytest
import yaml

from app.services.medium_models import check_medium_signature, medium_parameters
from app.services.ocr import OCRService, OCRUnavailableError


def test_explicit_missing_medium_does_not_use_small(tmp_path):
    missing = tmp_path / "inference (1).onnx"
    service = OCRService(medium_det_path=str(missing), medium_rec_path="")
    with pytest.raises(OCRUnavailableError, match="Configured Medium ONNX file missing"):
        service.warmup()
    assert not service.ready


def test_same_width_permuted_external_dictionary_is_rejected(tmp_path):
    model = tmp_path / "inference.onnx"
    model.touch()
    metadata = {
        "Global": {"model_name": "PP-OCRv6_medium_rec"},
        "PreProcess": {
            "transform_ops": [
                {"DecodeImage": {"img_mode": "BGR"}},
                {"RecResizeImg": {"image_shape": [3, 48, 320]}},
            ]
        },
        "PostProcess": {"name": "CTCLabelDecode", "character_dict": ["B", "A"]},
    }
    model.with_suffix(".yml").write_text(yaml.safe_dump(metadata), encoding="utf-8")
    dictionary = tmp_path / "dictionary.txt"
    dictionary.write_text("A\nB\n", encoding="utf-8")
    with pytest.raises(ValueError, match="dictionary do not match"):
        medium_parameters(model, "Rec", dictionary)


def test_detector_graph_cannot_be_used_as_recognizer():
    session = SimpleNamespace(
        get_inputs=lambda: [SimpleNamespace(type="tensor(float)", shape=["N", 3, "H", "W"])],
        get_outputs=lambda: [SimpleNamespace(type="tensor(float)", shape=["N", 1, "H", "W"])],
    )
    check_medium_signature("Det", session)
    with pytest.raises(ValueError, match="tensor signature"):
        check_medium_signature("Rec", session, 18710)
