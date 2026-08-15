"""Run a repeatable end-to-end HTTP benchmark against the local fixture server."""

from __future__ import annotations

import argparse
import asyncio
import json
import os
import statistics
import tempfile
import time
from pathlib import Path
from typing import Any

from engine.schemas import ScraperConfig
from engine.scraper import ScraperEngine

from benchmarks.fixture_server import FixtureServer


def _configure_loop() -> None:
    """Use curl_cffi's preferred loop when the benchmark runs on Windows."""
    if os.name == "nt" and hasattr(asyncio, "WindowsSelectorEventLoopPolicy"):
        asyncio.set_event_loop_policy(asyncio.WindowsSelectorEventLoopPolicy())


def _config(base_url: str, pages: int, concurrency: int) -> ScraperConfig:
    return ScraperConfig.model_validate({
        "name": "v32_local_benchmark",
        "mode": "list",
        "start_urls": [f"{base_url}/item/{index}" for index in range(pages)],
        "concurrency": concurrency,
        "rate_limit": 100_000,
        "min_delay": 0,
        "max_delay": 0,
        "fields": [
            {
                "name": "items",
                "selector": "article.product",
                "is_list": True,
                "children": [
                    {"name": "title", "selector": "h1"},
                    {"name": "price", "selector": ".price"},
                ],
            }
        ],
        "url_policy": {
            "block_private_networks": False,
            "resolve_dns": False,
            "allowed_domains": ["127.0.0.1"],
        },
    })


async def _run_once(base_url: str, pages: int, concurrency: int) -> dict[str, Any]:
    batches: list[dict[str, Any]] = []

    async def collect(batch: dict[str, Any]) -> None:
        batches.append(batch)

    engine = ScraperEngine(_config(base_url, pages, concurrency), output_callback=collect)
    with tempfile.TemporaryDirectory(prefix="glider-benchmark-") as temp_dir:
        engine.bloom_path = Path(temp_dir) / "dedupe.bloom"
        started = time.perf_counter()
        await engine.run()
    elapsed = time.perf_counter() - started
    records = sum(len(batch.get("items", [])) for batch in batches)
    return {
        "elapsed_seconds": round(elapsed, 6),
        "pages": pages,
        "records": records,
        "requests_per_second": round(pages / elapsed, 3) if elapsed else 0.0,
        "failed_pages": int(engine.failed_urls),
        "batches": len(batches),
    }


def run_benchmark(pages: int = 100, concurrency: int = 10, repeats: int = 3) -> dict[str, Any]:
    """Return benchmark measurements without requiring external network access."""
    if pages < 1 or concurrency < 1 or repeats < 1:
        raise ValueError("pages, concurrency, and repeats must be positive")
    _configure_loop()
    with FixtureServer().start() as server:
        runs = [asyncio.run(_run_once(server.base_url, pages, concurrency)) for _ in range(repeats)]
    elapsed_values = [float(run["elapsed_seconds"]) for run in runs]
    return {
        "benchmark": "local_http_list_extraction",
        "pages": pages,
        "concurrency": concurrency,
        "repeats": repeats,
        "mean_seconds": round(statistics.mean(elapsed_values), 6),
        "min_seconds": round(min(elapsed_values), 6),
        "max_seconds": round(max(elapsed_values), 6),
        "runs": runs,
    }


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--pages", type=int, default=100)
    parser.add_argument("--concurrency", type=int, default=10)
    parser.add_argument("--repeats", type=int, default=3)
    args = parser.parse_args()
    print(json.dumps(run_benchmark(args.pages, args.concurrency, args.repeats), indent=2))


if __name__ == "__main__":
    main()
