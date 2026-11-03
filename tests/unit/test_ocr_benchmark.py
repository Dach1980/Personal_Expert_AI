"""Tests for OCR benchmark metrics and engine-agnostic execution."""
from __future__ import annotations

from app.processing.ocr_benchmark import (
    BenchmarkCase,
    character_error_rate,
    edit_distance,
    evaluate_boxes,
    run_benchmark,
    word_error_rate,
)


def test_edit_distance_and_character_error_rate():
    assert edit_distance("kitten", "sitting") == 3
    assert character_error_rate("СП 30.13330", "СП 30.13330") == 0.0
    assert character_error_rate("ABC", "ADC") == 1 / 3


def test_word_error_rate_uses_word_tokens_not_character_distance():
    assert word_error_rate("one two three", "one four three") == 1 / 3
    assert word_error_rate("one two", "one two three") == 0.5


def test_box_metrics_match_token_and_iou():
    expected = (
        {"text": "Pump", "bbox": [10, 10, 30, 20]},
        {"text": "Valve", "bbox": [40, 10, 70, 20]},
    )
    predicted = [
        {"text": "Pump", "bbox_px": [11, 10, 31, 20]},
        {"text": "Other", "bbox_px": [40, 10, 70, 20]},
    ]
    metrics = evaluate_boxes(expected, predicted)
    assert metrics is not None
    assert metrics["precision"] == 0.5
    assert metrics["recall"] == 0.5
    assert metrics["mean_iou"] > 0.8


def test_benchmark_runner_is_engine_agnostic_and_records_errors():
    class FakeEngine:
        name = "fixture-engine"

        def recognize(self, image_bytes: bytes, *, language: str, config: str):
            assert image_bytes == b"image"
            assert language == "rus+eng"
            assert config == "--psm 3"
            return {"text": "текст один", "words": [], "version": "fixture-1"}

    case = BenchmarkCase("case-1", b"image", "текст один")
    report = run_benchmark([case], [FakeEngine()])
    assert report["case_count"] == 1
    assert report["results"][0]["status"] == "ok"
    assert report["results"][0]["cer"] == 0.0
    assert report["results"][0]["wer"] == 0.0


def test_benchmark_runner_keeps_engine_failures_in_report():
    class BrokenEngine:
        name = "broken"

        def recognize(self, image_bytes: bytes, *, language: str, config: str):
            raise RuntimeError("engine unavailable")

    report = run_benchmark(
        [BenchmarkCase("case-1", b"image", "expected")],
        [BrokenEngine()],
    )
    assert report["results"][0]["status"] == "error"
    assert report["results"][0]["error_type"] == "RuntimeError"


def test_tesseract_adapter_runs_on_a_synthetic_fixture_when_installed():
    import io

    import pytest

    pytesseract = pytest.importorskip("pytesseract")
    from PIL import Image, ImageDraw, ImageFont

    try:
        pytesseract.get_tesseract_version()
        font = ImageFont.truetype("DejaVuSans.ttf", 48)
    except (pytesseract.TesseractNotFoundError, OSError):
        pytest.skip("Tesseract executable or DejaVuSans font is unavailable")

    image = Image.new("RGB", (1000, 140), "white")
    ImageDraw.Draw(image).text((30, 35), "PROJECT 123", fill="black", font=font)
    buffer = io.BytesIO()
    image.save(buffer, format="PNG")

    from app.processing.ocr_benchmark import TesseractEngine

    result = TesseractEngine().recognize(
        buffer.getvalue(), language="eng", config="--psm 7"
    )
    assert result["text"].strip()
    assert len(result["words"]) >= 2
    assert result["version"]
