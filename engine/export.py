import json
import csv
from pathlib import Path
from typing import Any, Dict, List, Optional, Set
from loguru import logger
from engine.utils import flatten_dict


def _stringify_lists(d: Dict[str, Any]) -> Dict[str, Any]:
    """Convert any list values in a flat dict to pipe-separated strings for CSV."""
    result = {}
    for k, v in d.items():
        if isinstance(v, list):
            result[k] = " | ".join(str(item) for item in v)
        else:
            result[k] = v
    return result


def convert_to_json(input_file: Path, output_file: Path):
    """
    Streams JSONL to a valid JSON array.
    Memory Usage: O(1) (Line by line)
    """
    logger.info(f"📂 Converting {input_file} to JSON...")
    try:
        with open(input_file, 'r', encoding='utf-8') as fin, \
             open(output_file, 'w', encoding='utf-8') as fout:
            
            fout.write('[\n')
            first = True
            for line in fin:
                if not line.strip(): continue
                try:
                    data = json.loads(line)
                    # Flatten top-level keys if they are just grouping containers
                    for _, value in data.items():
                        items = value if isinstance(value, list) else [value]
                        for item in items:
                            if not first: fout.write(',\n')
                            json.dump(item, fout, ensure_ascii=False, indent=2)
                            first = False
                except json.JSONDecodeError:
                    continue
            
            fout.write('\n]')
            logger.success(f"✅ JSON saved to {output_file}")
    except Exception as e:
        logger.error(f"JSON Export failed: {e}")

def convert_to_csv(input_file: Path, output_file: Path, field_order: Optional[List[str]] = None):
    """
    Two-pass CSV conversion to handle dynamic headers without memory spikes.
    Pass 1: Scan for keys.
    Pass 2: Write rows.

    Args:
        field_order: Optional list of field names to use as the preferred column order.
                     Any discovered fields not in this list are appended alphabetically.
    """
    logger.info(f"📂 Converting {input_file} to CSV...")
    headers: Set[str] = set()
    
    # Pass 1: Collect Headers
    try:
        with open(input_file, 'r', encoding='utf-8') as f:
            for line in f:
                if not line.strip(): continue
                try:
                    data = json.loads(line)
                    for _, value in data.items():
                        items = value if isinstance(value, list) else [value]
                        for item in items:
                            if isinstance(item, dict):
                                flat = flatten_dict(item)
                                headers.update(flat.keys())
                            else:
                                logger.debug(f"CSV: skipping non-dict item of type {type(item).__name__}")
                except json.JSONDecodeError:
                    continue
    except Exception as e:
        logger.error(f"CSV Pass 1 failed: {e}")
        return

    if not headers:
        logger.warning("No headers found for CSV.")
        return

    # Respect preferred field order; append any extra fields alphabetically
    if field_order:
        ordered = [f for f in field_order if f in headers]
        remaining = sorted(headers - set(ordered))
        fieldnames = ordered + remaining
    else:
        fieldnames = sorted(list(headers))

    # Pass 2: Write Data
    try:
        with open(input_file, 'r', encoding='utf-8') as fin, \
             open(output_file, 'w', newline='', encoding='utf-8') as fout:
            
            writer = csv.DictWriter(fout, fieldnames=fieldnames, extrasaction='ignore')
            writer.writeheader()
            
            for line in fin:
                if not line.strip(): continue
                try:
                    data = json.loads(line)
                    for _, value in data.items():
                        items = value if isinstance(value, list) else [value]
                        for item in items:
                            if isinstance(item, dict):
                                flat = flatten_dict(item)
                                row = _stringify_lists(flat)
                                writer.writerow(row)
                except json.JSONDecodeError:
                    continue
        logger.success(f"✅ CSV saved to {output_file}")
    except Exception as e:
        logger.error(f"CSV Export failed: {e}")