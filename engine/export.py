import json
import csv
from pathlib import Path
from typing import Set
from loguru import logger
from engine.utils import flatten_dict

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

def convert_to_csv(input_file: Path, output_file: Path):
    """
    Two-pass CSV conversion to handle dynamic headers without memory spikes.
    Pass 1: Scan for keys.
    Pass 2: Write rows.
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
                except json.JSONDecodeError:
                    continue
    except Exception as e:
        logger.error(f"CSV Pass 1 failed: {e}")
        return

    if not headers:
        logger.warning("No headers found for CSV.")
        return

    fieldnames = sorted(list(headers))

    # Pass 2: Write Data
    try:
        with open(input_file, 'r', encoding='utf-8') as fin, \
             open(output_file, 'w', newline='', encoding='utf-8') as fout:
            
            writer = csv.DictWriter(fout, fieldnames=fieldnames)
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
                                writer.writerow(flat)
                except json.JSONDecodeError:
                    continue
        logger.success(f"✅ CSV saved to {output_file}")
    except Exception as e:
        logger.error(f"CSV Export failed: {e}")