"""Focused state, crawl, redirect, and sitemap regressions from the deep review."""

import asyncio
import json
from unittest.mock import AsyncMock

import pytest

from engine.checkpoint import CheckpointManager
from engine.errors import ErrorCategory, FetchError
from engine.network import FetchResult, RequestPurpose
from engine.run import RunContext
from engine.schemas import (
    DataField,
    Pagination,
    RetryConfig,
    ScraperConfig,
    Selector,
    SelectorType,
)
from engine.scraper import ScraperEngine
from engine.sitemap import discover_sitemap


def _nested_config() -> ScraperConfig:
    return ScraperConfig(
        name="luna-nested",
        base_url="https://site.com",
        mode="list",
        start_urls=["https://site.com/root"],
        min_delay=0,
        max_delay=0,
        max_depth=4,
        max_nested_urls=10,
        fields=[
            DataField(
                name="children",
                selectors=[Selector(type=SelectorType.CSS, value="a.link")],
                attribute="href",
                is_list=True,
                follow_url=True,
                nested_fields=[
                    DataField(
                        name="title",
                        selectors=[Selector(type=SelectorType.CSS, value="h1")],
                    )
                ],
            )
        ],
        url_policy={"resolve_dns": False},
    )


def _links(*urls: str) -> str:
    return "<html><body>" + "".join(
        f'<a class="link" href="{url}">{url}</a>' for url in urls
    ) + "</body></html>"


async def _init_checkpoint(engine: ScraperEngine, path) -> None:
    engine.checkpoint = CheckpointManager("luna", True, path)
    await engine.checkpoint.initialize()


@pytest.mark.parametrize("redirect_status", [301, 302, 303])
async def test_post_redirects_switch_to_get_without_body(redirect_status):
    class Response:
        def __init__(self, status_code, headers=None):
            self.status_code = status_code
            self.headers = headers or {}
            self.text = "<html><body>ok</body></html>"

    class Session:
        def __init__(self):
            self.calls = []
            self.responses = [
                Response(redirect_status, {"location": "/next"}),
                Response(200),
            ]

        async def post(self, url, **kwargs):
            self.calls.append(("POST", url, kwargs))
            return self.responses.pop(0)

        async def get(self, url, **kwargs):
            self.calls.append(("GET", url, kwargs))
            return self.responses.pop(0)

    config = ScraperConfig(
        name="redirect-method",
        base_url="https://example.com",
        fields=[],
        request_method="POST",
        request_body={"value": "x"},
        retry=RetryConfig(base_delay_seconds=0, max_delay_seconds=0),
    )
    engine = ScraperEngine(config)
    session = Session()
    engine.session = session  # type: ignore[assignment]

    result = await engine._fetch_page("https://example.com/start")

    assert result.ok()
    assert [call[0] for call in session.calls] == ["POST", "GET"]
    assert "json" not in session.calls[1][2]
    assert "data" not in session.calls[1][2]


async def test_run_unexpected_exception_finalizes_failed_manifest(tmp_path):
    config = ScraperConfig(
        name="luna-failed",
        base_url="https://example.com",
        mode="list",
        start_urls=["https://example.com/one"],
        fields=[],
        url_policy={"resolve_dns": False},
    )
    context = RunContext.create("luna-failed", {"name": "luna-failed"}, output_root=tmp_path)
    engine = ScraperEngine(config, run_context=context, dry_run=True)

    async def fail_setup():
        raise RuntimeError("setup exploded")

    engine._setup_resources = fail_setup  # type: ignore[assignment]

    with pytest.raises(RuntimeError, match="setup exploded"):
        await engine.run()

    manifest = json.loads(context.manifest_path.read_text(encoding="utf-8"))
    assert manifest["state"] == "failed"
    assert "setup exploded" in manifest["error"]


async def test_run_unexpected_exception_after_progress_is_partial(tmp_path):
    config = ScraperConfig(
        name="luna-partial",
        base_url="https://example.com",
        mode="list",
        start_urls=["https://example.com/one"],
        fields=[],
        url_policy={"resolve_dns": False},
    )
    context = RunContext.create("luna-partial", {"name": "luna-partial"}, output_root=tmp_path)
    engine = ScraperEngine(config, run_context=context, dry_run=True)

    async def no_setup():
        return None

    async def fail_after_progress(_incomplete):
        engine._has_progress = True
        raise RuntimeError("worker exploded")

    engine._setup_resources = no_setup  # type: ignore[assignment]
    engine._run_list_mode = fail_after_progress  # type: ignore[assignment]

    with pytest.raises(RuntimeError, match="worker exploded"):
        await engine.run()

    manifest = json.loads(context.manifest_path.read_text(encoding="utf-8"))
    assert manifest["state"] == "partial"


async def test_cleanup_continues_after_one_resource_fails():
    closed = []

    class Resource:
        def __init__(self, name, fail=False):
            self.name = name
            self.fail = fail

        async def close(self):
            closed.append(self.name)
            if self.fail:
                raise RuntimeError(f"{self.name} close failed")

    engine = ScraperEngine(
        ScraperConfig(name="cleanup", base_url="https://example.com", fields=[]),
        dry_run=True,
    )
    engine.checkpoint = Resource("checkpoint", fail=True)  # type: ignore[assignment]
    engine.browser_manager = Resource("browser")
    engine.session = Resource("session")  # type: ignore[assignment]
    engine.stream_writer = Resource("writer")  # type: ignore[assignment]

    errors = await engine._cleanup_resources()

    assert closed == ["checkpoint", "browser", "session", "writer"]
    assert any("checkpoint" in error for error in errors)


async def test_preview_cleans_up_when_setup_fails():
    config = ScraperConfig(
        name="preview-cleanup",
        base_url="https://example.com",
        fields=[],
    )
    engine = ScraperEngine(config, dry_run=True)
    engine._setup_resources = AsyncMock(side_effect=RuntimeError("preview setup failed"))  # type: ignore[assignment]
    engine._cleanup_resources = AsyncMock(return_value=[])  # type: ignore[assignment]

    with pytest.raises(RuntimeError, match="preview setup failed"):
        await engine.preview()

    engine._cleanup_resources.assert_awaited_once()  # type: ignore[attr-defined]


async def test_nested_empty_response_is_failed_and_resumable(tmp_path):
    engine = ScraperEngine(_nested_config())
    await _init_checkpoint(engine, tmp_path / "nested-empty.sqlite")

    async def empty_fetch(url, purpose=None, parent_url=None):
        return FetchResult(
            content="",
            requested_url=url,
            final_url=url,
            status_code=200,
            headers={},
        )

    engine._fetch_page = empty_fetch  # type: ignore[assignment]
    try:
        with pytest.raises(FetchError, match="nested"):
            await engine._process_content(_links("https://site.com/child"), "https://site.com/root")

        incomplete = await engine.checkpoint.get_incomplete_items(kind="nested")
        assert [item["url"] for item in incomplete] == ["https://site.com/child"]
        assert engine.checkpoint.is_done("https://site.com/child", kind="nested") is False
    finally:
        await engine.checkpoint.close()


async def test_nested_no_content_response_is_completed_empty_result(tmp_path):
    engine = ScraperEngine(_nested_config())
    await _init_checkpoint(engine, tmp_path / "nested-204.sqlite")

    async def empty_fetch(url, purpose=None, parent_url=None):
        return FetchResult(
            content="",
            requested_url=url,
            final_url=url,
            status_code=204,
            headers={},
        )

    engine._fetch_page = empty_fetch  # type: ignore[assignment]
    try:
        data, _ = await engine._process_content(
            _links("https://site.com/child"), "https://site.com/root"
        )
        assert data["children"][0]["_source_url"] == "https://site.com/child"
        assert engine.checkpoint.is_done("https://site.com/child", kind="nested") is True
    finally:
        await engine.checkpoint.close()


async def test_nested_unexpected_error_marks_checkpoint_failed(tmp_path):
    engine = ScraperEngine(_nested_config())
    await _init_checkpoint(engine, tmp_path / "nested-error.sqlite")

    async def broken_fetch(url, purpose=None, parent_url=None):
        raise RuntimeError("child transport adapter broke")

    engine._fetch_page = broken_fetch  # type: ignore[assignment]
    try:
        with pytest.raises(FetchError, match="nested"):
            await engine._process_content(_links("https://site.com/child"), "https://site.com/root")
        incomplete = await engine.checkpoint.get_incomplete_items(kind="nested")
        assert incomplete[0]["url"] == "https://site.com/child"
    finally:
        await engine.checkpoint.close()


async def test_cycle_detection_is_branch_local(tmp_path):
    title = DataField(
        name="title",
        selectors=[Selector(type=SelectorType.CSS, value="h1")],
    )
    level = DataField(
        name="children",
        selectors=[Selector(type=SelectorType.CSS, value="a.link")],
        attribute="href",
        is_list=True,
        follow_url=True,
        nested_fields=[title],
    )
    config = ScraperConfig(
        name="branch-cycle",
        base_url="https://site.com",
        mode="list",
        start_urls=["https://site.com/a"],
        fields=[
            DataField(
                name="children",
                selectors=[Selector(type=SelectorType.CSS, value="a.link")],
                attribute="href",
                is_list=True,
                follow_url=True,
                nested_fields=[level],
            )
        ],
        min_delay=0,
        max_delay=0,
        max_depth=4,
        url_policy={"resolve_dns": False},
    )
    engine = ScraperEngine(config)
    await _init_checkpoint(engine, tmp_path / "branch-cycle.sqlite")
    calls = []
    bodies = {
        "https://site.com/x": "<html><body><h1>X</h1></body></html>",
        "https://site.com/y": _links("https://site.com/x"),
    }

    async def fetch(url, purpose=None, parent_url=None):
        calls.append(url)
        return FetchResult(
            content=bodies[url],
            requested_url=url,
            final_url=url,
            status_code=200,
            headers={},
        )

    engine._fetch_page = fetch  # type: ignore[assignment]
    try:
        await engine._process_content(_links("https://site.com/x"), "https://site.com/a")
        data, _ = await engine._process_content(
            _links("https://site.com/y"), "https://site.com/b"
        )
        assert data["children"][0]["children"][0]["title"] == "X"
        assert calls.count("https://site.com/x") == 2
    finally:
        await engine.checkpoint.close()


def test_child_cache_is_bounded():
    config = _nested_config()
    engine = ScraperEngine(config)
    for index in range(engine._child_cache_limit + 5):
        engine._cache_child((f"https://site.com/{index}", "field"), {"index": index})
    assert len(engine.child_cache) == engine._child_cache_limit


async def test_pagination_validates_and_uses_final_url_for_next_link():
    config = ScraperConfig(
        name="pagination-state",
        base_url="https://example.com/start",
        fields=[
            DataField(
                name="title",
                selectors=[Selector(type=SelectorType.CSS, value="h1")],
            )
        ],
        pagination=Pagination(
            selector=Selector(type=SelectorType.CSS, value="a.next"),
            max_pages=2,
        ),
        validation={"required_fields": ["title"], "fail_on_empty": True},
        min_delay=0,
        max_delay=0,
        url_policy={"resolve_dns": False},
    )
    engine = ScraperEngine(config)
    calls = []
    responses = {
        "https://example.com/start": FetchResult(
            content='<h1>first</h1><a class="next" href="page2">next</a>',
            requested_url="https://example.com/start",
            final_url="https://example.com/canonical/",
            status_code=200,
            headers={},
        ),
        "https://example.com/canonical/page2": FetchResult(
            content="<p>missing title</p>",
            requested_url="https://example.com/canonical/page2",
            final_url="https://example.com/canonical/page2",
            status_code=200,
            headers={},
        ),
    }

    async def fetch(url, purpose=None, parent_url=None):
        calls.append(url)
        return responses[url]

    engine._fetch_page = fetch  # type: ignore[assignment]
    await engine._run_pagination_mode()

    assert calls == [
        "https://example.com/start",
        "https://example.com/canonical/page2",
    ]
    assert int(engine.failed_urls) == 1


async def test_sitemap_queue_documents_and_response_size_are_bounded():
    documents = {
        "https://example.com/index.xml": (
            "<sitemapindex>"
            "<sitemap><loc>/a.xml</loc></sitemap>"
            "<sitemap><loc>/b.xml</loc></sitemap>"
            "</sitemapindex>"
        ),
        "https://example.com/a.xml": "<urlset><url><loc>/a</loc></url></urlset>",
        "https://example.com/b.xml": "<urlset><url><loc>/b</loc></url></urlset>",
    }
    calls = []

    async def fetch(url):
        calls.append(url)
        return documents[url]

    result = await discover_sitemap(
        ["https://example.com/index.xml"],
        fetch,
        lambda url: _true(),
        max_urls=10,
        max_queue=1,
        max_documents=10,
    )
    assert result == ["https://example.com/a"]
    assert calls == ["https://example.com/index.xml", "https://example.com/a.xml"]

    calls.clear()
    result = await discover_sitemap(
        ["https://example.com/index.xml"],
        fetch,
        lambda url: _true(),
        max_urls=10,
        max_bytes=10,
    )
    assert result == []
    assert calls == ["https://example.com/index.xml"]


async def _true():
    return True
