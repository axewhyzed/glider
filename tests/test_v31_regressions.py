"""Regression coverage for the v3.1 deep review fixes."""

import asyncio
import json

import pytest

from engine.cookies import load_scoped_cookies
from engine.errors import ErrorCategory
from engine.network import RequestPurpose, UrlPolicyError, canonicalize_url
from engine.network import UrlPolicy
from engine.schemas import UrlPolicyConfig
from engine.schemas import Interaction, InteractionType, ScraperConfig
from engine.scraper import ScraperEngine
from engine.writer import JsonlStreamWriter


def test_port_zero_is_rejected():
    with pytest.raises(UrlPolicyError):
        canonicalize_url("https://example.com:0/")


def test_allowed_domains_apply_to_root_targets():
    policy = UrlPolicy(UrlPolicyConfig(allowed_domains=["example.com"]))
    assert policy.validate("https://example.com/") == "https://example.com/"
    with pytest.raises(UrlPolicyError):
        policy.validate("https://other.example/")


def test_interactions_require_action_inputs():
    with pytest.raises(ValueError):
        Interaction(type=InteractionType.CLICK)
    with pytest.raises(ValueError):
        Interaction(type=InteractionType.KEY_PRESS)
    with pytest.raises(ValueError):
        Interaction(type=InteractionType.WAIT, duration=-1)


def test_cookie_loader_enforces_exact_origin(tmp_path):
    path = tmp_path / "cookies.json"
    path.write_text(
        json.dumps([
            {"name": "session", "value": "ok", "url": "https://example.com/login"},
            {"name": "other", "value": "no", "url": "https://evil.example/"},
            {"name": "parent", "value": "no", "domain": ".example.com"},
        ]),
        encoding="utf-8",
    )
    cookies = load_scoped_cookies(path, "https://example.com/start")

    assert cookies.pairs == {"session": "ok", "parent": "no"}
    assert cookies.playwright[0]["url"] == "https://example.com/start"
    assert cookies.header_for("https://example.com/page") == "session=ok"
    assert cookies.header_for("https://other.example/page") is None


async def test_concurrent_dedup_reservation_emits_once():
    config = ScraperConfig(name="dedup", base_url="https://example.com", fields=[])
    engine = ScraperEngine(config)
    engine.batch_size = 100
    emitted = []

    async def capture(value):
        emitted.append(value)

    engine.output_callback = capture
    await asyncio.gather(*(
        engine._merge_data({"id": 1}, source_url="https://example.com/1")
        for _ in range(20)
    ))
    await engine._flush_remaining_batches()

    assert sum(len(batch["items"]) for batch in emitted) == 1
    assert engine.metrics.duplicates_detected == 19


async def test_url_dedup_without_source_url_does_not_collapse_records():
    from engine.schemas import DedupConfig, DedupMode

    config = ScraperConfig(
        name="dedup-url",
        base_url="https://example.com",
        fields=[],
        dedup=DedupConfig(mode=DedupMode.URL),
    )
    engine = ScraperEngine(config)
    emitted = []
    engine.batch_size = 1

    async def capture(value):
        emitted.append(value)

    engine.output_callback = capture
    await engine._merge_data({"id": 1})
    await engine._merge_data({"id": 2})

    assert [item["id"] for batch in emitted for item in batch["items"]] == [1, 2]


class _CancelledSession:
    async def get(self, url, **kwargs):
        raise asyncio.CancelledError()


async def test_cancelled_fetch_resolves_proxy_lease():
    config = ScraperConfig(
        name="proxy-cancel",
        base_url="https://example.com",
        fields=[],
        proxies=["http://proxy.example:8080"],
        proxy_failure_threshold=3,
    )
    engine = ScraperEngine(config)
    engine.session = _CancelledSession()  # type: ignore[assignment]

    with pytest.raises(asyncio.CancelledError):
        await engine._fetch_page("https://example.com/", purpose=RequestPurpose.ROOT)

    snapshot = await engine.proxy_health.snapshot()
    assert snapshot["http://proxy.example:8080"]["active_leases"] == 0


async def test_writer_serializes_concurrent_first_writes(tmp_path):
    writer = JsonlStreamWriter(tmp_path / "stream.jsonl")
    await asyncio.gather(*(writer.write({"items": [{"i": i}]}) for i in range(20)))
    await writer.close()

    lines = (tmp_path / "stream.jsonl").read_text(encoding="utf-8").splitlines()
    assert len(lines) == 20
    assert all(json.loads(line)["items"] for line in lines)
