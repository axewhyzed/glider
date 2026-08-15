"""Recursive extraction and nested-result semantics tests (P4.1-P4.6)."""

import asyncio
import json

import pytest

from engine.checkpoint import CheckpointManager
from engine.network import FetchResult, RequestPurpose
from engine.schemas import DataField, ScraperConfig, Selector, SelectorType, UrlPolicyConfig
from engine.scraper import ScraperEngine

CHILD_HTML = "<html><body><h1>Child title</h1></body></html>"


class RecorderSession:
    """Stub session that records fetch calls and returns canned content."""

    def __init__(self, content_map):
        self.content_map = content_map
        self.calls = []

    async def get(self, url, **kwargs):
        self.calls.append(url)
        return SimpleResponse(200, self.content_map.get(url, CHILD_HTML))


class SimpleResponse:
    def __init__(self, status_code, text, headers=None):
        self.status_code = status_code
        self.text = text
        self.headers = headers or {}


def _nested_config(tmp_path, max_depth=2):
    config = ScraperConfig(
        name="recursion",
        base_url="https://site.com",
        mode="list",
        start_urls=["https://site.com/root"],
        max_depth=max_depth,
        max_nested_urls=5,
        url_policy=UrlPolicyConfig(resolve_dns=False),
        fields=[
            DataField(
                name="children",
                selectors=[Selector(type=SelectorType.CSS, value="a.link")],
                attribute="href",
                is_list=True,
                follow_url=True,
                nested_fields=[
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
            )
        ],
    )
    engine = ScraperEngine(config)
    engine.checkpoint = CheckpointManager("recursion", True, tmp_path / "rec.sqlite")
    engine.session = RecorderSession({})  # type: ignore[assignment]
    return engine


def _page_html(links):
    anchors = "".join(f'<a class="link" href="{href}">{href}</a>' for href in links)
    return f"<html><body>{anchors}</body></html>"


async def test_child_fetched_once_across_parents(tmp_path):
    engine = _nested_config(tmp_path)
    await engine.checkpoint.initialize()
    try:
        parent_html = _page_html(["https://site.com/child"])
        data, _ = await engine._process_content(parent_html, "https://site.com/p1")
        data2, _ = await engine._process_content(parent_html, "https://site.com/p2")
        # Same child URL referenced by two parents -> one fetch (child_cache hit).
        assert len(engine.session.calls) == 1
        assert len(data["children"]) == 1
        assert len(data2["children"]) == 1
    finally:
        await engine.checkpoint.close()


async def test_repeated_child_attaches_to_all_parents(tmp_path):
    engine = _nested_config(tmp_path)
    await engine.checkpoint.initialize()
    try:
        parent_html = _page_html(["https://site.com/child"])
        results = []
        for parent in ["https://site.com/p1", "https://site.com/p2", "https://site.com/p3"]:
            data, _ = await engine._process_content(parent_html, parent)
            results.append(data)
        assert len(engine.session.calls) == 1  # 1 fetch, 3 attachments
        for data in results:
            assert data["children"][0]["_source_url"] == "https://site.com/child"
    finally:
        await engine.checkpoint.close()


async def test_done_child_not_refetched_on_resume(tmp_path):
    engine = _nested_config(tmp_path)
    await engine.checkpoint.initialize()
    try:
        # Simulate a prior run: child already done AND a persisted record exists
        # for this parent. The child must attach without any network fetch.
        await engine.checkpoint.mark_done("https://site.com/child", kind="nested")
        await engine.checkpoint.mark_child_result(
            "https://site.com/child",
            "https://site.com/p1",
            engine.config.fields[0].model_dump_json(exclude={"name"}, exclude_none=True),
            json.dumps({"title": "persisted", "children": []}),
        )
        parent_html = _page_html(["https://site.com/child"])
        data, _ = await engine._process_content(parent_html, "https://site.com/p1")
        assert engine.session.calls == []  # zero fetches
        assert data["children"][0]["title"] == "persisted"
    finally:
        await engine.checkpoint.close()


async def test_resume_reattaches_done_child_without_fetch(tmp_path):
    engine = _nested_config(tmp_path)
    await engine.checkpoint.initialize()
    try:
        await engine.checkpoint.mark_done("https://site.com/child", kind="nested")
        await engine.checkpoint.mark_child_result(
            "https://site.com/child",
            "https://site.com/p1",
            engine.config.fields[0].model_dump_json(exclude={"name"}, exclude_none=True),
            json.dumps({"title": "persisted"}),
        )
        parent_html = _page_html(["https://site.com/child"])
        data, _ = await engine._process_content(parent_html, "https://site.com/p1")
        assert data["children"][0]["title"] == "persisted"
        assert engine.session.calls == []  # zero fetches
    finally:
        await engine.checkpoint.close()


async def test_two_node_cycle_stops(tmp_path):
    engine = _nested_config(tmp_path, max_depth=5)
    await engine.checkpoint.initialize()
    try:
        # A -> B -> A: the deeper A must not be fetched again.
        a_html = _page_html(["https://site.com/b"])
        b_html = _page_html(["https://site.com/a"])
        engine.session.content_map["https://site.com/b"] = b_html
        data, _ = await engine._process_content(a_html, "https://site.com/a")
        # B fetched; B's child A is a cycle (depth 2 > depth 0) -> empty children.
        assert data["children"][0]["children"] == []
        assert engine.session.calls.count("https://site.com/b") == 1
        assert engine.session.calls.count("https://site.com/a") == 0  # never as child
    finally:
        await engine.checkpoint.close()


async def test_same_depth_revisit_is_not_cycle(tmp_path):
    engine = _nested_config(tmp_path, max_depth=3)
    await engine.checkpoint.initialize()
    try:
        # Two parents at the same depth link to the same child -> not a cycle.
        c_html = _page_html(["https://site.com/child"])
        data1, _ = await engine._process_content(c_html, "https://site.com/p1")
        data2, _ = await engine._process_content(c_html, "https://site.com/p2")
        assert len(data1["children"]) == 1
        assert len(data2["children"]) == 1
        assert engine.session.calls.count("https://site.com/child") == 1
    finally:
        await engine.checkpoint.close()


async def test_depth_exhaustion_returns_empty_list(tmp_path):
    engine = _nested_config(tmp_path, max_depth=1)
    await engine.checkpoint.initialize()
    try:
        # depth 0 -> child (depth 1) fetched; child's children are exhausted
        # (depth 2 >= max_depth 1).
        child_html = _page_html(["https://site.com/grandchild"])
        engine.session.content_map["https://site.com/child"] = child_html
        parent_html = _page_html(["https://site.com/child"])
        data, _ = await engine._process_content(parent_html, "https://site.com/p1")
        assert data["children"][0]["children"] == []
        assert "https://site.com/grandchild" not in engine.session.calls
    finally:
        await engine.checkpoint.close()


async def test_metadata_injected_on_fresh_fetch(tmp_path):
    engine = _nested_config(tmp_path)
    await engine.checkpoint.initialize()
    try:
        parent_html = _page_html(["https://site.com/child"])
        data, _ = await engine._process_content(parent_html, "https://site.com/p1")
        child = data["children"][0]
        assert child["_source_url"] == "https://site.com/child"
        assert child["_parent_url"] == "https://site.com/p1"
    finally:
        await engine.checkpoint.close()


async def test_metadata_injected_on_cache_hit(tmp_path):
    engine = _nested_config(tmp_path)
    await engine.checkpoint.initialize()
    try:
        parent_html = _page_html(["https://site.com/child"])
        await engine._process_content(parent_html, "https://site.com/p1")
        data2, _ = await engine._process_content(parent_html, "https://site.com/p2")
        child = data2["children"][0]
        assert child["_parent_url"] == "https://site.com/p2"  # attaching parent
        assert child["_source_url"] == "https://site.com/child"
    finally:
        await engine.checkpoint.close()
