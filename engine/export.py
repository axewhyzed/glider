"""Streaming, fail-fast JSON and CSV exporters."""

from __future__ import annotations

import csv
import json
from pathlib import Path
from typing import Any, Dict, Iterable, List, Optional, Set

from loguru import logger

from engine.utils import flatten_dict


class ExportError(RuntimeError):
    """Raised when an export cannot complete without data loss."""


def _iter_items(line: str, line_number: int) -> Iterable[Any]:
    try:
        data = json.loads(line)
    except json.JSONDecodeError as exc:
        raise ExportError(f"Malformed JSONL at line {line_number}: {exc.msg}") from exc
    if not isinstance(data, dict):
        raise ExportError(f"JSONL line {line_number} must contain an object")
    for value in data.values():
        yield from (value if isinstance(value, list) else [value])


def _stringify_lists(data: Dict[str, Any]) -> Dict[str, Any]:
    return {key: " | ".join(str(item) for item in value) if isinstance(value, list) else value
            for key, value in data.items()}


def convert_to_json(input_file: Path, output_file: Path) -> None:
    logger.info(f"Converting {input_file} to JSON")
    try:
        with input_file.open("r", encoding="utf-8") as source, output_file.open("w", encoding="utf-8") as target:
            target.write("[\n")
            first = True
            for line_number, line in enumerate(source, 1):
                if not line.strip():
                    continue
                for item in _iter_items(line, line_number):
                    if not first:
                        target.write(",\n")
                    json.dump(item, target, ensure_ascii=False, indent=2)
                    first = False
            target.write("\n]")
    except ExportError:
        output_file.unlink(missing_ok=True)
        raise
    except Exception as exc:
        output_file.unlink(missing_ok=True)
        raise ExportError(f"JSON export failed: {exc}") from exc
    logger.success(f"JSON saved to {output_file}")


def convert_to_csv(input_file: Path, output_file: Path, field_order: Optional[List[str]] = None) -> None:
    logger.info(f"Converting {input_file} to CSV")
    headers: Set[str] = set()
    try:
        with input_file.open("r", encoding="utf-8") as source:
            for line_number, line in enumerate(source, 1):
                if not line.strip():
                    continue
                for item in _iter_items(line, line_number):
                    if isinstance(item, dict):
                        headers.update(flatten_dict(item).keys())
        if not headers:
            raise ExportError("No tabular records found for CSV export")
        ordered = [field for field in (field_order or []) if field in headers]
        fieldnames = ordered + sorted(headers - set(ordered))
        with input_file.open("r", encoding="utf-8") as source, output_file.open("w", newline="", encoding="utf-8") as target:
            writer = csv.DictWriter(target, fieldnames=fieldnames, extrasaction="ignore")
            writer.writeheader()
            for line_number, line in enumerate(source, 1):
                if not line.strip():
                    continue
                for item in _iter_items(line, line_number):
                    if isinstance(item, dict):
                        writer.writerow(_stringify_lists(flatten_dict(item)))
    except ExportError:
        output_file.unlink(missing_ok=True)
        raise
    except Exception as exc:
        output_file.unlink(missing_ok=True)
        raise ExportError(f"CSV export failed: {exc}") from exc
    logger.success(f"CSV saved to {output_file}")
