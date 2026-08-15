"""End-to-end usage checks against deterministic local HTTP fixtures."""

from benchmarks.fixture_server import FixtureServer
from engine.schemas import ScraperConfig
from engine.scraper import ScraperEngine


def _local_policy() -> dict[str, object]:
    return {
        "block_private_networks": False,
        "resolve_dns": False,
        "allowed_domains": ["127.0.0.1"],
    }


async def test_local_http_pagination_and_extraction():
    with FixtureServer(page_count=3) as server:
        config = ScraperConfig.model_validate({
            "name": "local-pagination",
            "base_url": f"{server.base_url}/page/1",
            "mode": "pagination",
            "min_delay": 0,
            "max_delay": 0,
            "fields": [{"name": "pages", "selector": "article.product", "is_list": True}],
            "pagination": {"selector": "a.next", "max_pages": 3},
            "url_policy": _local_policy(),
        })
        batches: list[dict] = []

        async def collect(batch: dict) -> None:
            batches.append(batch)

        engine = ScraperEngine(config, output_callback=collect)
        await engine.run()

        assert int(engine.failed_urls) == 0
        assert sum(len(batch["items"]) for batch in batches) == 3
        assert server.request_count == 3


async def test_local_json_api_and_nested_links():
    with FixtureServer() as server:
        config = ScraperConfig.model_validate({
            "name": "local-json-nested",
            "mode": "list",
            "start_urls": [f"{server.base_url}/api/item/7"],
            "concurrency": 1,
            "min_delay": 0,
            "max_delay": 0,
            "fields": [{
                "name": "record",
                "selectors": [{"type": "json", "value": "title"}],
            }],
            "response_type": "json",
            "url_policy": _local_policy(),
        })
        json_batches: list[dict] = []

        async def collect_json(batch: dict) -> None:
            json_batches.append(batch)

        engine = ScraperEngine(config, output_callback=collect_json)
        await engine.run()
        assert int(engine.failed_urls) == 0
        assert any(batch["items"][0]["record"] == "Fixture API item 7" for batch in json_batches)

        nested_config = ScraperConfig.model_validate({
            "name": "local-nested",
            "mode": "list",
            "start_urls": [f"{server.base_url}/catalog"],
            "min_delay": 0,
            "max_delay": 0,
            "fields": [{
                "name": "products",
                "selector": "a.product-link",
                "attribute": "href",
                "is_list": True,
                "follow_url": True,
                "nested_fields": [{"name": "title", "selector": "h1"}],
            }],
            "url_policy": _local_policy(),
        })
        nested_batches: list[dict] = []

        async def collect_nested(batch: dict) -> None:
            nested_batches.append(batch)

        nested_engine = ScraperEngine(nested_config, output_callback=collect_nested)
        await nested_engine.run()
        assert int(nested_engine.failed_urls) == 0
        products = nested_batches[0]["items"][0]["products"]
        assert [product["title"] for product in products] == [
            "Fixture item 1", "Fixture item 2"
        ]


def test_local_benchmark_smoke():
    from benchmarks.local import run_benchmark

    result = run_benchmark(pages=5, concurrency=2, repeats=1)
    assert result["runs"][0]["records"] == 5
    assert result["runs"][0]["failed_pages"] == 0


def test_local_benchmark_usage_matrix():
    from benchmarks.local import run_usage_benchmark

    result = run_usage_benchmark(pages=3, concurrency=2, repeats=1)
    assert set(result["scenarios"]) == {"list", "pagination", "json", "nested"}
    assert result["scenarios"]["list"]["runs"][0]["records"] == 3
    assert result["scenarios"]["pagination"]["runs"][0]["records"] == 3
    assert result["scenarios"]["json"]["runs"][0]["records"] == 3
    assert result["scenarios"]["nested"]["runs"][0]["nested_records"] == 3
    assert all(
        scenario["runs"][0]["failed_pages"] == 0
        for scenario in result["scenarios"].values()
    )
