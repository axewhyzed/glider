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

SCENARIOS = ("list", "pagination", "json", "nested")


def _configure_loop() -> None:
    """Use curl_cffi's preferred loop when the benchmark runs on Windows."""
    if os.name == "nt" and hasattr(asyncio, "WindowsSelectorEventLoopPolicy"):
        asyncio.set_event_loop_policy(asyncio.WindowsSelectorEventLoopPolicy())


def _config(base_url: str, scenario: str, workload_size: int, concurrency: int) -> ScraperConfig:
    common = {
        "name": f"local_{scenario}_benchmark",
        "concurrency": concurrency,
        "rate_limit": 100_000,
        "min_delay": 0,
        "max_delay": 0,
        "url_policy": {
            "block_private_networks": False,
            "resolve_dns": False,
            "allowed_domains": ["127.0.0.1"],
        },
    }
    if scenario == "list":
        return ScraperConfig.model_validate({
            **common,
            "mode": "list",
            "start_urls": [f"{base_url}/item/{index}" for index in range(workload_size)],
            "fields": [{
                "name": "items",
                "selector": "article.product",
                "is_list": True,
                "children": [
                    {"name": "title", "selector": "h1"},
                    {"name": "price", "selector": ".price"},
                ],
            }],
        })
    if scenario == "pagination":
        return ScraperConfig.model_validate({
            **common,
            "mode": "pagination",
            "base_url": f"{base_url}/page/1",
            "fields": [{"name": "pages", "selector": "article.product", "is_list": True}],
            "pagination": {"selector": "a.next", "max_pages": workload_size},
        })
    if scenario == "json":
        return ScraperConfig.model_validate({
            **common,
            "mode": "list",
            "start_urls": [f"{base_url}/api/item/{index}" for index in range(workload_size)],
            "fields": [{"name": "record", "selectors": [{"type": "json", "value": "title"}]}],
            "response_type": "json",
        })
    if scenario == "nested":
        return ScraperConfig.model_validate({
            **common,
            "mode": "list",
            "start_urls": [f"{base_url}/catalog"],
            "fields": [{
                "name": "products",
                "selector": "a.product-link",
                "attribute": "href",
                "is_list": True,
                "follow_url": True,
                "nested_fields": [{"name": "title", "selector": "h1"}],
            }],
        })
    raise ValueError(f"unknown benchmark scenario: {scenario}")


def _nested_record_count(batches: list[dict[str, Any]]) -> int:
    return sum(
        sum(
            1
            for value in record.values()
            if isinstance(value, list)
            for child in value
            if isinstance(child, dict)
        )
        for batch in batches
        for record in batch.get("items", [])
        if isinstance(record, dict)
    )


async def _run_once(
    server: FixtureServer, scenario: str, workload_size: int, concurrency: int
) -> dict[str, Any]:
    batches: list[dict[str, Any]] = []

    async def collect(batch: dict[str, Any]) -> None:
        batches.append(batch)

    before_requests = server.request_count
    engine = ScraperEngine(
        _config(server.base_url, scenario, workload_size, concurrency), output_callback=collect
    )
    with tempfile.TemporaryDirectory(prefix="glider-benchmark-") as temp_dir:
        engine.bloom_path = Path(temp_dir) / "dedupe.bloom"
        started = time.perf_counter()
        await engine.run()
    elapsed = time.perf_counter() - started
    records = sum(len(batch.get("items", [])) for batch in batches)
    requests = server.request_count - before_requests
    return {
        "elapsed_seconds": round(elapsed, 6),
        "workload_size": workload_size,
        # Retain the v3.3 output key for consumers that already parse it.
        "pages": workload_size,
        "records": records,
        "requests_per_second": round(requests / elapsed, 3) if elapsed else 0.0,
        "failed_pages": int(engine.failed_urls),
        "batches": len(batches),
        "requests": requests,
        "nested_records": _nested_record_count(batches) if scenario == "nested" else 0,
    }


def run_scenario(
    scenario: str,
    workload_size: int | None = None,
    concurrency: int = 10,
    repeats: int = 3,
    *,
    pages: int | None = None,
) -> dict[str, Any]:
    """Measure one deterministic local usage scenario."""
    if workload_size is not None and pages is not None:
        raise ValueError("pass workload_size or its legacy pages alias, not both")
    if workload_size is None:
        workload_size = pages if pages is not None else 100
    if workload_size < 1 or concurrency < 1 or repeats < 1:
        raise ValueError("workload_size, concurrency, and repeats must be positive")
    if scenario not in SCENARIOS:
        raise ValueError(f"scenario must be one of: {', '.join(SCENARIOS)}")
    _configure_loop()
    with FixtureServer(page_count=workload_size, catalog_count=workload_size).start() as server:
        runs = [
            asyncio.run(_run_once(server, scenario, workload_size, concurrency))
            for _ in range(repeats)
        ]
    elapsed_values = [float(run["elapsed_seconds"]) for run in runs]
    return {
        "benchmark": f"local_http_{scenario}_extraction",
        "scenario": scenario,
        "workload_size": workload_size,
        "pages": workload_size,
        "concurrency": concurrency,
        "repeats": repeats,
        "mean_seconds": round(statistics.mean(elapsed_values), 6),
        "min_seconds": round(min(elapsed_values), 6),
        "max_seconds": round(max(elapsed_values), 6),
        "runs": runs,
    }


def run_benchmark(
    workload_size: int | None = None,
    concurrency: int = 10,
    repeats: int = 3,
    *,
    pages: int | None = None,
) -> dict[str, Any]:
    """Backward-compatible list extraction benchmark."""
    return run_scenario(
        "list", workload_size, concurrency, repeats, pages=pages
    )


def run_usage_benchmark(
    workload_size: int | None = None,
    concurrency: int = 10,
    repeats: int = 3,
    *,
    pages: int | None = None,
) -> dict[str, Any]:
    """Measure each deterministic local usage scenario separately."""
    if workload_size is not None and pages is not None:
        raise ValueError("pass workload_size or its legacy pages alias, not both")
    if workload_size is None:
        workload_size = pages if pages is not None else 100
    return {
        "benchmark": "local_http_usage",
        "workload_size": workload_size,
        "pages": workload_size,
        "concurrency": concurrency,
        "repeats": repeats,
        "scenarios": {
            scenario: run_scenario(
                scenario, workload_size, concurrency, repeats
            )
            for scenario in SCENARIOS
        },
    }


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--workload-size", "--pages", dest="workload_size", type=int, default=100,
        help="Scenario workload size; --pages is retained as a compatibility alias.",
    )
    parser.add_argument("--concurrency", type=int, default=10)
    parser.add_argument("--repeats", type=int, default=3)
    parser.add_argument("--scenario", choices=("all", *SCENARIOS), default="all")
    args = parser.parse_args()
    result = (
        run_usage_benchmark(args.workload_size, args.concurrency, args.repeats)
        if args.scenario == "all"
        else run_scenario(args.scenario, args.workload_size, args.concurrency, args.repeats)
    )
    print(json.dumps(result, indent=2))


if __name__ == "__main__":
    main()
