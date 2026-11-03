"""Reproducible, local OCR benchmark runner.

The runner accepts a manifest with image paths and human-verified ground truth.
It never uploads images or calls a remote service. Additional OCR engines can
implement the small OCREngine protocol without changing the benchmark logic.
"""
from __future__ import annotations

import argparse
import json
import time
from dataclasses import asdict, dataclass
from pathlib import Path
from typing import Any, Protocol


class OCREngine(Protocol):
    name: str

    def recognize(self, image_bytes: bytes, *, language: str, config: str) -> dict[str, Any]:
        """Return at least {'text': str, 'words': list[dict]}."""


@dataclass(frozen=True)
class BenchmarkCase:
    case_id: str
    image_bytes: bytes
    ground_truth: str
    ground_truth_words: tuple[dict[str, Any], ...] = ()


def normalize_text(value: str) -> str:
    import unicodedata

    normalized = unicodedata.normalize("NFKC", value).casefold()
    return " ".join(normalized.split())


def edit_distance(reference: str, hypothesis: str) -> int:
    """Levenshtein distance using O(min(n, m)) memory."""
    if len(reference) < len(hypothesis):
        reference, hypothesis = hypothesis, reference
    previous = list(range(len(hypothesis) + 1))
    for row_index, ref_char in enumerate(reference, start=1):
        current = [row_index]
        for column_index, hyp_char in enumerate(hypothesis, start=1):
            current.append(min(
                current[-1] + 1,
                previous[column_index] + 1,
                previous[column_index - 1] + (ref_char != hyp_char),
            ))
        previous = current
    return previous[-1]


def character_error_rate(reference: str, hypothesis: str) -> float:
    reference_norm = normalize_text(reference)
    hypothesis_norm = normalize_text(hypothesis)
    if not reference_norm:
        return 0.0 if not hypothesis_norm else 1.0
    return edit_distance(reference_norm, hypothesis_norm) / len(reference_norm)


def word_error_rate(reference: str, hypothesis: str) -> float:
    reference_words = normalize_text(reference).split()
    hypothesis_words = normalize_text(hypothesis).split()
    if not reference_words:
        return 0.0 if not hypothesis_words else 1.0
    return edit_distance(" ".join(reference_words), " ".join(hypothesis_words)) / len(
        reference_words
    )


def _box_iou(first: list[float], second: list[float]) -> float:
    left = max(first[0], second[0])
    top = max(first[1], second[1])
    right = min(first[2], second[2])
    bottom = min(first[3], second[3])
    intersection = max(0.0, right - left) * max(0.0, bottom - top)
    first_area = max(0.0, first[2] - first[0]) * max(0.0, first[3] - first[1])
    second_area = max(0.0, second[2] - second[0]) * max(0.0, second[3] - second[1])
    union = first_area + second_area - intersection
    return intersection / union if union > 0 else 0.0


def evaluate_boxes(
    expected: tuple[dict[str, Any], ...], predicted: list[dict[str, Any]]
) -> dict[str, float] | None:
    """Greedily match equal tokens by IoU; boxes must share one coordinate space."""
    if not expected:
        return None
    candidates: list[tuple[float, int, int]] = []
    for expected_index, expected_word in enumerate(expected):
        expected_box = expected_word.get("bbox")
        if not expected_box:
            continue
        for predicted_index, predicted_word in enumerate(predicted):
            predicted_box = predicted_word.get("bbox_px") or predicted_word.get("bbox")
            if not predicted_box:
                continue
            if normalize_text(str(expected_word.get("text", ""))) != normalize_text(
                str(predicted_word.get("text", ""))
            ):
                continue
            candidates.append((
                _box_iou(list(expected_box), list(predicted_box)),
                expected_index,
                predicted_index,
            ))
    candidates.sort(reverse=True)
    matched_expected: set[int] = set()
    matched_predicted: set[int] = set()
    matched_ious: list[float] = []
    for iou, expected_index, predicted_index in candidates:
        if iou < 0.5 or expected_index in matched_expected or predicted_index in matched_predicted:
            continue
        matched_expected.add(expected_index)
        matched_predicted.add(predicted_index)
        matched_ious.append(iou)
    precision = len(matched_predicted) / len(predicted) if predicted else 0.0
    recall = len(matched_expected) / len(expected) if expected else 0.0
    return {
        "precision": precision,
        "recall": recall,
        "mean_iou": sum(matched_ious) / len(matched_ious) if matched_ious else 0.0,
    }


class TesseractEngine:
    name = "tesseract"

    def recognize(self, image_bytes: bytes, *, language: str, config: str) -> dict[str, Any]:
        import io

        import pytesseract
        from PIL import Image

        with Image.open(io.BytesIO(image_bytes)) as image:
            data = pytesseract.image_to_data(
                image,
                lang=language,
                config=config,
                output_type=pytesseract.Output.DICT,
            )
        words: list[dict[str, Any]] = []
        for index, raw in enumerate(data.get("text", [])):
            token = str(raw).strip()
            try:
                confidence = float(data["conf"][index])
            except (KeyError, TypeError, ValueError):
                confidence = -1.0
            if not token or confidence < 0:
                continue
            left = int(data["left"][index])
            top = int(data["top"][index])
            words.append({
                "text": token,
                "confidence": confidence,
                "bbox_px": [
                    left,
                    top,
                    left + int(data["width"][index]),
                    top + int(data["height"][index]),
                ],
            })
        lines: dict[tuple[int, int, int], list[str]] = {}
        for index, token in enumerate(data.get("text", [])):
            word = str(token).strip()
            if not word:
                continue
            key = (
                int(data["block_num"][index]),
                int(data["par_num"][index]),
                int(data["line_num"][index]),
            )
            lines.setdefault(key, []).append(word)
        return {
            "text": "\n".join(" ".join(parts) for parts in lines.values()),
            "words": words,
            "version": str(pytesseract.get_tesseract_version()),
        }


def run_benchmark(
    cases: list[BenchmarkCase],
    engines: list[OCREngine],
    *,
    language: str = "rus+eng",
    config: str = "--psm 3",
) -> dict[str, Any]:
    rows: list[dict[str, Any]] = []
    for engine in engines:
        for case in cases:
            rss_before: int | None = None
            rss_after: int | None = None
            try:
                try:
                    import psutil

                    process = psutil.Process()
                    rss_before = process.memory_info().rss
                except ImportError:
                    pass
                started = time.perf_counter()
                result = engine.recognize(case.image_bytes, language=language, config=config)
                elapsed_ms = (time.perf_counter() - started) * 1000
                try:
                    if rss_before is not None:
                        rss_after = process.memory_info().rss
                except (NameError, OSError):
                    rss_after = None
                recognized = str(result.get("text", ""))
                row = {
                    "engine": engine.name,
                    "case_id": case.case_id,
                    "status": "ok",
                    "cer": character_error_rate(case.ground_truth, recognized),
                    "wer": word_error_rate(case.ground_truth, recognized),
                    "latency_ms": round(elapsed_ms, 3),
                    "rss_before_bytes": rss_before,
                    "rss_after_bytes": rss_after,
                    "rss_delta_bytes": (
                        rss_after - rss_before
                        if rss_before is not None and rss_after is not None
                        else None
                    ),
                    "recognized_characters": len(recognized),
                    "recognized_words": len(result.get("words", [])),
                    "box_metrics": evaluate_boxes(
                        case.ground_truth_words, list(result.get("words", []))
                    ),
                    "engine_version": result.get("version"),
                }
            except Exception as exc:
                row = {
                    "engine": engine.name,
                    "case_id": case.case_id,
                    "status": "error",
                    "error_type": type(exc).__name__,
                    "error": str(exc)[:1000],
                }
            rows.append(row)
    return {
        "schema_version": 1,
        "language": language,
        "config": config,
        "case_count": len(cases),
        "engine_count": len(engines),
        "results": rows,
        "notes": [
            "CER/WER are calculated against normalized human-verified ground truth.",
            "Bounding-box metrics require ground_truth_words and OCR words in the same image-pixel coordinate space.",
            "RSS values are process snapshots, not peak memory measurements; they require optional psutil.",
            "This report does not establish accuracy on document classes absent from the supplied corpus.",
        ],
    }


def load_cases(manifest_path: Path) -> list[BenchmarkCase]:
    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    root = manifest_path.parent
    cases: list[BenchmarkCase] = []
    for item in manifest.get("cases", []):
        image_path = (root / item["image"]).resolve()
        if not image_path.is_relative_to(root.resolve()):
            raise ValueError(f"Image path escapes manifest directory: {item['image']}")
        cases.append(BenchmarkCase(
            case_id=str(item["id"]),
            image_bytes=image_path.read_bytes(),
            ground_truth=str(item["ground_truth"]),
            ground_truth_words=tuple(item.get("ground_truth_words", [])),
        ))
    if not cases:
        raise ValueError("Benchmark manifest contains no cases")
    return cases


def main() -> None:
    parser = argparse.ArgumentParser(description="Run a local OCR benchmark from a ground-truth manifest.")
    parser.add_argument("--manifest", required=True, type=Path)
    parser.add_argument("--output", required=True, type=Path)
    parser.add_argument("--language", default="rus+eng")
    parser.add_argument("--config", default="--psm 3")
    args = parser.parse_args()
    try:
        import pytesseract  # noqa: F401
        from PIL import Image  # noqa: F401
    except ImportError as exc:
        raise SystemExit("Install the optional OCR dependencies: pip install -e '.[ocr]'") from exc
    report = run_benchmark(
        load_cases(args.manifest),
        [TesseractEngine()],
        language=args.language,
        config=args.config,
    )
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(report, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(f"Benchmark complete: {len(report['results'])} result(s) -> {args.output}")


if __name__ == "__main__":
    main()
