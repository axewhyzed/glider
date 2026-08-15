"""Redaction + manifest security tests (P9.4)."""

import json

from engine.redact import redact_dict, redact_text
from engine.run import RunContext


def test_redact_bearer_and_cookie():
    text = "Authorization: Bearer abc123xyz Cookie: session=topsecret"
    out = redact_text(text)
    assert "abc123xyz" not in out
    assert "topsecret" not in out
    assert "[REDACTED]" in out


def test_redact_query_params():
    out = redact_text("https://api.com/x?token=sekret&api_key=key123")
    assert "sekret" not in out
    assert "key123" not in out


def test_redact_url_credentials():
    out = redact_text("https://user:pass@example.com/")
    assert "user:pass" not in out


def test_redact_dict_secrets():
    data = {
        "authentication": {
            "type": "oauth_password",
            "client_secret": "secret-value",
            "password": "pw",
        },
        "name": "ok",
    }
    out = redact_dict(data)
    assert out["authentication"]["client_secret"] == "[REDACTED]"
    assert out["authentication"]["password"] == "[REDACTED]"
    assert out["name"] == "ok"


def test_manifest_contains_no_secrets(tmp_path):
    ctx = RunContext.create(
        "sec",
        {
            "name": "sec",
            "authentication": {"type": "oauth_password", "client_secret": "supersecret", "password": "hunter2"},
        },
        output_root=tmp_path,
    )
    manifest = json.loads(ctx.manifest_path.read_text(encoding="utf-8"))
    serialized = json.dumps(manifest)
    assert "supersecret" not in serialized
    assert "hunter2" not in serialized
    assert "[REDACTED]" in serialized


def test_digest_uses_raw_config(tmp_path):
    """Digest must be stable regardless of redacted manifest display."""
    raw = {"name": "sec", "authentication": {"client_secret": "rawval"}}
    ctx1 = RunContext.create("sec", raw, output_root=tmp_path)
    # Manifest is redacted but digest is over raw config.
    assert ctx1.config_digest == RunContext.create("sec", raw, output_root=tmp_path).config_digest
    manifest = json.loads(ctx1.manifest_path.read_text(encoding="utf-8"))
    assert "rawval" not in json.dumps(manifest)
