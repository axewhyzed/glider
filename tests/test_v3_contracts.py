import json

import pytest

from engine.export import ExportError, convert_to_json
from engine.network import UrlPolicy
from engine.report import build_resume_command
from engine.schemas import RetryConfig, ScraperConfig
from engine.sitemap import discover_sitemap, parse_sitemap
from engine.scraper import ScraperEngine
from engine.validation import validate_config_data


def _config(**overrides):
    data = {
        "name": "v3",
        "base_url": "https://example.com",
        "fields": [],
    }
    data.update(overrides)
    return ScraperConfig(**data)


def test_fields_dedup_requires_explicit_fields():
    result = validate_config_data({
        "name": "bad",
        "base_url": "https://example.com",
        "fields": [],
        "dedup": {"mode": "fields", "fields": []},
    })
    assert not result.valid
    assert any(issue.path == "dedup.fields" for issue in result.issues)


def test_record_count_does_not_sum_parallel_lists():
    engine = ScraperEngine(_config())
    assert engine._count_items({"titles": [1, 2], "prices": [3, 4]}) == 2
    configured = ScraperEngine(_config(record_field="titles", fields=[{"name": "titles", "is_list": True}]))
    assert configured._count_items({"titles": [1, 2], "prices": [3, 4, 5]}) == 2


def test_redirect_header_scope_uses_original_credential_origin():
    policy = UrlPolicy(_config().url_policy)
    headers = policy.headers_for(
        "https://other.example/item",
        parent_url="https://example.com/start",
        configured={"Authorization": "secret", "X-Trace": "ok"},
        bearer_token="token",
        credential_origin="https://example.com",
    )
    assert "Authorization" not in headers
    assert "X-Trace" in headers


def test_resume_command_is_complete_and_executable_shape():
    command = build_resume_command(["main.py"], "run-1", "config.json", "data")
    assert "scrape" in command
    assert "config.json" in command
    assert "--resume" in command
    assert "--output-dir" in command


def test_export_malformed_jsonl_fails_and_cleans_output(tmp_path):
    source = tmp_path / "stream.jsonl"
    target = tmp_path / "output.json"
    source.write_text('{"items":[{"ok":true}]}\nnot-json\n', encoding="utf-8")
    with pytest.raises(ExportError):
        convert_to_json(source, target)
    assert not target.exists()


def test_sitemap_parser_handles_indexes_and_urlsets():
    urls, children = parse_sitemap(
        '<sitemapindex xmlns="http://www.sitemaps.org/schemas/sitemap/0.9">'
        '<sitemap><loc>/one.xml</loc></sitemap></sitemapindex>',
        "https://example.com/robots.txt",
    )
    assert urls == []
    assert children == ["https://example.com/one.xml"]

    urls, children = parse_sitemap(
        '<urlset xmlns="http://www.sitemaps.org/schemas/sitemap/0.9">'
        '<url><loc>/a</loc></url><url><loc>/b</loc></url></urlset>',
        "https://example.com/sitemap.xml",
    )
    assert urls == ["https://example.com/a", "https://example.com/b"]
    assert children == []


async def test_sitemap_discovery_is_bounded_and_deterministic():
    documents = {
        "https://example.com/index.xml": '<sitemapindex><sitemap><loc>/one.xml</loc></sitemap></sitemapindex>',
        "https://example.com/one.xml": '<urlset><url><loc>/a</loc></url><url><loc>/b</loc></url></urlset>',
    }
    result = await discover_sitemap(
        ["https://example.com/index.xml"],
        lambda url: _async_value(documents[url]),
        lambda url: _async_value(True),
        max_urls=1,
    )
    assert result == ["https://example.com/a"]


async def _async_value(value):
    return value


async def test_post_request_sends_configured_body():
    class Response:
        status_code = 200
        text = '{"ok":true}'
        headers = {}

    class Session:
        def __init__(self):
            self.calls = []

        async def post(self, url, **kwargs):
            self.calls.append((url, kwargs))
            return Response()

    engine = ScraperEngine(_config(
        request_method="POST",
        request_body={"q": "x"},
        response_type="json",
        retry=RetryConfig(base_delay_seconds=0, max_delay_seconds=0),
    ))
    engine.session = Session()
    result = await engine._fetch_page("https://example.com/api")
    assert result.ok()
    assert engine.session.calls[0][1]["json"] == {"q": "x"}
