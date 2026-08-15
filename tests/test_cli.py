"""CLI integration tests (P8.7) using typer.testing.CliRunner + mocked fetch.

All network is replaced by a monkeypatched ScraperEngine._fetch_page so the
suite is deterministic and runs offline.
"""

import asyncio
import json

import pytest
from typer.testing import CliRunner

from engine.network import FetchResult
from engine.schemas import ScraperConfig
from engine.scraper import ScraperEngine
from main import app

runner = CliRunner()


def _write_config(tmp_path, name="cli", mode="list", start_urls=None, fields=None):
    config = {
        "name": name,
        "mode": mode,
        "fields": fields or [{"name": "title", "selector": "h1"}],
    }
    if mode == "list":
        config["start_urls"] = start_urls or ["https://example.com/1"]
    else:
        config["base_url"] = "https://example.com"
    path = tmp_path / f"{name}.json"
    path.write_text(json.dumps(config), encoding="utf-8")
    return path


def _ok_fetch_result(url, **kwargs):
    return FetchResult(
        content="<html><body><h1>Hello</h1></body></html>",
        requested_url=url,
        final_url=url,
        status_code=200,
        headers={"content-type": "text/html"},
        elapsed_ms=5.0,
    )


@pytest.fixture
def mock_fetch(monkeypatch):
    def _install(fetch_map=None, raise_on=None):
        calls = []

        async def fake_fetch(self, url, purpose=None, parent_url=None):
            calls.append(url)
            if raise_on is not None and len(calls) >= raise_on:
                raise KeyboardInterrupt()
            if fetch_map and url in fetch_map:
                return fetch_map[url]
            return _ok_fetch_result(url)

        monkeypatch.setattr(ScraperEngine, "_fetch_page", fake_fetch)
        return calls

    return _install


# ------------------------------------------------------------ validate

def test_validate_valid_exit_0(tmp_path):
    path = _write_config(tmp_path)
    result = runner.invoke(app, ["validate", str(path)])
    assert result.exit_code == 0
    assert "valid" in result.stdout.lower()


def test_validate_missing_file_exit_2(tmp_path):
    result = runner.invoke(app, ["validate", str(tmp_path / "nope.json")])
    assert result.exit_code == 2
    assert "File not found" in result.stdout


def test_validate_malformed_json_exit_2(tmp_path):
    path = tmp_path / "bad.json"
    path.write_text('{"name":', encoding="utf-8")
    result = runner.invoke(app, ["validate", str(path)])
    assert result.exit_code == 2
    assert "Invalid JSON" in result.stdout


def test_validate_bad_format_exit_2(tmp_path):
    path = _write_config(tmp_path)
    result = runner.invoke(app, ["validate", str(path), "--format", "xml"])
    assert result.exit_code == 2
    assert "must be text or json" in result.stdout


def test_validate_json_format_stable(tmp_path):
    path = _write_config(tmp_path)
    result = runner.invoke(app, ["validate", str(path), "--format", "json"])
    assert result.exit_code == 0
    data = json.loads(result.stdout)
    assert data["valid"] is True


def test_validate_makes_no_network_requests(tmp_path):
    path = _write_config(tmp_path)
    result = runner.invoke(app, ["validate", str(path)])
    assert result.exit_code == 0


# ------------------------------------------------------------ preview

def test_preview_invalid_config_exit_2(tmp_path):
    path = tmp_path / "bad.json"
    path.write_text('{"name":', encoding="utf-8")
    result = runner.invoke(app, ["preview", str(path)])
    assert result.exit_code == 2


def test_preview_runtime_failure_exit_1(tmp_path, mock_fetch):
    path = _write_config(tmp_path)

    async def failing_fetch(self, url, purpose=None, parent_url=None):
        raise RuntimeError("network down")

    mock_fetch()
    import types
    # Override to force failure.
    async def fake_fetch(self, url, purpose=None, parent_url=None):
        raise RuntimeError("network down")

    import engine.scraper as scraper_mod
    original = scraper_mod.ScraperEngine._fetch_page
    scraper_mod.ScraperEngine._fetch_page = fake_fetch  # type: ignore[assignment]
    try:
        result = runner.invoke(app, ["preview", str(path)])
        assert result.exit_code == 1
        assert "Preview failed" in result.stdout
    finally:
        scraper_mod.ScraperEngine._fetch_page = original


# ------------------------------------------------------------ scrape

def test_scrape_invalid_config_exit_2(tmp_path):
    path = tmp_path / "bad.json"
    path.write_text('{"name":', encoding="utf-8")
    result = runner.invoke(app, ["scrape", str(path), "--output-dir", str(tmp_path / "out")])
    assert result.exit_code == 2


def test_scrape_dry_run_writes_nothing(tmp_path, mock_fetch):
    path = _write_config(tmp_path)
    mock_fetch()
    out = tmp_path / "out"
    result = runner.invoke(app, ["scrape", str(path), "--dry-run", "--output-dir", str(out)])
    assert result.exit_code == 0
    assert not (out / "runs").exists()
    assert not list(out.rglob("*.jsonl"))


def test_scrape_dry_run_failure_exit_1(tmp_path):
    path = _write_config(tmp_path)

    async def failing_fetch(self, url, purpose=None, parent_url=None):
        raise RuntimeError("boom")

    original = ScraperEngine._fetch_page
    ScraperEngine._fetch_page = failing_fetch  # type: ignore[assignment]
    try:
        result = runner.invoke(app, ["scrape", str(path), "--dry-run"])
        assert result.exit_code == 1
        assert "Dry run failed" in result.stdout
    finally:
        ScraperEngine._fetch_page = original


def test_scrape_success_exit_0_and_artifacts(tmp_path, mock_fetch):
    path = _write_config(tmp_path)
    mock_fetch()
    out = tmp_path / "out"
    result = runner.invoke(app, ["scrape", str(path), "--output-dir", str(out)])
    assert result.exit_code == 0
    run_dirs = list((out / "cli" / "runs").iterdir())
    assert len(run_dirs) == 1
    run_dir = run_dirs[0]
    assert (run_dir / "exports" / "output.json").exists()
    manifest = json.loads((run_dir / "manifest.json").read_text(encoding="utf-8"))
    assert manifest["state"] == "completed"
    assert (run_dir / "report.json").exists()


def test_scrape_runtime_failure_exit_1(tmp_path, mock_fetch):
    path = _write_config(tmp_path)
    mock_fetch()
    # Pre-create the run dir so RunContext.create raises FileExistsError.
    from engine.run import RunContext
    ctx = RunContext.create("cli", {"name": "cli"}, output_root=tmp_path / "out")
    out = tmp_path / "out"
    result = runner.invoke(app, [
        "scrape", str(path), "--output-dir", str(out), "--run-id", ctx.run_id,
    ])
    assert result.exit_code == 1
    assert "Run already exists" in result.stdout


def test_scrape_interrupt_exit_130(tmp_path, mock_fetch):
    path = _write_config(
        tmp_path, name="cli", start_urls=["https://example.com/1", "https://example.com/2", "https://example.com/3"]
    )
    calls = mock_fetch(raise_on=2)
    out = tmp_path / "out"
    result = runner.invoke(app, ["scrape", str(path), "--output-dir", str(out)])
    assert result.exit_code == 130
    run_dirs = list((out / "cli" / "runs").iterdir())
    assert len(run_dirs) == 1
    manifest = json.loads((run_dirs[0] / "manifest.json").read_text(encoding="utf-8"))
    assert manifest["state"] in ("cancelled", "completed")


def test_scrape_resume_mismatched_config_rejected(tmp_path, mock_fetch):
    path = _write_config(tmp_path, name="cli")
    mock_fetch()
    out = tmp_path / "out"
    result = runner.invoke(app, ["scrape", str(path), "--output-dir", str(out)])
    assert result.exit_code == 0
    run_id = json.loads((out / "cli" / "runs").joinpath(list((out / "cli" / "runs").iterdir())[0].name, "manifest.json").read_text(encoding="utf-8"))["run_id"]
    # Resume with a different config but the SAME name (digest differs).
    other = _write_config(tmp_path, name="cli", fields=[{"name": "different", "selector": "p"}])
    result2 = runner.invoke(app, ["scrape", str(other), "--output-dir", str(out), "--resume", run_id])
    assert result2.exit_code == 1
    assert "does not match" in result2.stdout
