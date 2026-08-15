"""Tests for engine.run: run-scoped directories, manifest, resume safety.

Phase 2 (P2.5/P2.6/P2.9): job/run IDs, stable run directories, manifest with
config fingerprint, and safe resume/restart behavior.
"""

import json
import re

import pytest

from engine.run import RunContext, _slugify


def _config(name: str = "test config") -> dict:
    return {"name": name, "mode": "pagination", "fields": []}


def test_run_context_creates_isolated_directory(tmp_path):
    ctx = RunContext.create("my scraper", _config("my scraper"), output_root=tmp_path)
    assert ctx.directory.exists()
    assert ctx.directory.parent.parent == tmp_path / "my_scraper"
    # All mutable artifacts live inside the run directory.
    for path in [ctx.manifest_path, ctx.stream_path, ctx.checkpoint_path,
                 ctx.bloom_path, ctx.failures_path, ctx.export_directory,
                 ctx.debug_directory]:
        assert str(path).startswith(str(ctx.directory)), f"{path} escapes run dir"


def test_run_id_unique_and_manifest_created(tmp_path):
    ctx1 = RunContext.create("a", _config("a"), output_root=tmp_path)
    ctx2 = RunContext.create("a", _config("a"), output_root=tmp_path)
    assert ctx1.run_id != ctx2.run_id
    manifest = json.loads(ctx1.manifest_path.read_text(encoding="utf-8"))
    assert manifest["run_id"] == ctx1.run_id
    assert manifest["state"] == "running"
    assert manifest["config_digest"] == ctx1.config_digest
    assert manifest["resumed"] is False


def test_config_digest_stable_for_same_config(tmp_path):
    ctx1 = RunContext.create("a", _config("a"), output_root=tmp_path)
    ctx2 = RunContext.create("a", _config("a"), output_root=tmp_path)
    assert ctx1.config_digest == ctx2.config_digest


def test_config_digest_changes_with_config(tmp_path):
    ctx1 = RunContext.create("a", {"mode": "list"}, output_root=tmp_path)
    ctx2 = RunContext.create("a", {"mode": "pagination"}, output_root=tmp_path)
    assert ctx1.config_digest != ctx2.config_digest


def test_same_second_starts_do_not_collide(tmp_path):
    """P2.8: two runs created in the same second must not share a directory."""
    ctxs = {RunContext.create("collision", _config(), output_root=tmp_path).directory
            for _ in range(5)}
    assert len(ctxs) == 5


def test_existing_run_without_resume_raises(tmp_path):
    ctx1 = RunContext.create("a", _config(), output_root=tmp_path)
    with pytest.raises(FileExistsError):
        RunContext.create("a", _config(), output_root=tmp_path, run_id=ctx1.run_id)


def test_resume_requires_existing_run(tmp_path):
    with pytest.raises(FileNotFoundError):
        RunContext.create("a", _config(), output_root=tmp_path, resume=True, run_id="missing")


def test_resume_with_matching_config_succeeds(tmp_path):
    ctx1 = RunContext.create("a", _config(), output_root=tmp_path)
    ctx2 = RunContext.create("a", _config(), output_root=tmp_path, resume=True, run_id=ctx1.run_id)
    assert ctx2.directory == ctx1.directory


def test_resume_with_different_config_rejected(tmp_path):
    """P2.9: resuming a run with a different config fingerprint is refused."""
    ctx1 = RunContext.create("a", _config(), output_root=tmp_path)
    other = _config()
    other["fields"] = [{"name": "x", "selectors": []}]
    with pytest.raises(ValueError, match="does not match"):
        RunContext.create("a", other, output_root=tmp_path, resume=True, run_id=ctx1.run_id)


def test_update_manifest_merges_fields(tmp_path):
    ctx = RunContext.create("a", _config(), output_root=tmp_path)
    ctx.update_manifest(state="completed", failed_urls=3)
    manifest = json.loads(ctx.manifest_path.read_text(encoding="utf-8"))
    assert manifest["state"] == "completed"
    assert manifest["failed_urls"] == 3
    assert manifest["config_digest"] == ctx.config_digest  # preserved


def test_slugify_sanitizes_names():
    assert _slugify("My Scraper!") == "my_scraper"
    assert _slugify("a/b/c") == "a_b_c"
    assert _slugify("...") == "glider"
    assert re.fullmatch(r"[a-z0-9._-]+", _slugify("UPPER case 123")) is not None
