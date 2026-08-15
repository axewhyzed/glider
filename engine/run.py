"""Run-scoped filesystem state for reliable, collision-free scraper jobs."""

from __future__ import annotations

import hashlib
import json
import re
import uuid
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, Optional

from engine.redact import redact_dict


def _slugify(value: str) -> str:
    value = re.sub(r"[^a-zA-Z0-9._-]+", "_", value.strip().lower())
    return value.strip("._-") or "glider"


def _utc_now() -> str:
    return datetime.now(timezone.utc).isoformat()


@dataclass(frozen=True)
class RunContext:
    """All mutable artifacts for one scrape invocation."""

    output_root: Path
    config_name: str
    run_id: str
    directory: Path
    config_digest: str
    manifest_path: Path
    stream_path: Path
    checkpoint_path: Path
    bloom_path: Path
    export_directory: Path
    debug_directory: Path
    failures_path: Path

    @classmethod
    def create(
        cls,
        config_name: str,
        config_data: Dict[str, Any],
        output_root: Path | str = Path("data"),
        run_id: Optional[str] = None,
        resume: bool = False,
    ) -> "RunContext":
        root = Path(output_root)
        slug = _slugify(config_name)
        run_id = run_id or datetime.now().strftime("%Y%m%d_%H%M%S") + "_" + uuid.uuid4().hex[:8]
        directory = root / slug / "runs" / run_id
        digest_payload = json.dumps(config_data, sort_keys=True, default=str).encode("utf-8")
        digest = hashlib.sha256(digest_payload).hexdigest()

        if resume and not directory.exists():
            raise FileNotFoundError(f"Run does not exist: {run_id}")
        if not resume and directory.exists():
            raise FileExistsError(f"Run already exists: {run_id}")

        directory.mkdir(parents=True, exist_ok=True)
        export_directory = directory / "exports"
        debug_directory = directory / "debug"
        export_directory.mkdir(exist_ok=True)
        debug_directory.mkdir(exist_ok=True)

        context = cls(
            output_root=root,
            config_name=config_name,
            run_id=run_id,
            directory=directory,
            config_digest=digest,
            manifest_path=directory / "manifest.json",
            stream_path=directory / "stream.jsonl",
            checkpoint_path=directory / "checkpoint.sqlite",
            bloom_path=directory / "dedupe.bloom",
            export_directory=export_directory,
            debug_directory=debug_directory,
            failures_path=directory / "failures.jsonl",
        )
        context._initialize_manifest(config_data, resume=resume)
        return context

    def _initialize_manifest(self, config_data: Dict[str, Any], resume: bool) -> None:
        if self.manifest_path.exists():
            existing = json.loads(self.manifest_path.read_text(encoding="utf-8"))
            if existing.get("config_digest") != self.config_digest:
                raise ValueError(
                    "The supplied configuration does not match the selected run; "
                    "refusing unsafe resume"
                )
            return

        manifest = {
            "run_id": self.run_id,
            "config_name": self.config_name,
            "config_digest": self.config_digest,
            "state": "running",
            "started_at": _utc_now(),
            "resumed": resume,
            # Redacted for display; the digest is still computed over the RAW
            # config so resume safety is unchanged.
            "config": redact_dict(config_data),
        }
        self.manifest_path.write_text(
            json.dumps(manifest, indent=2, ensure_ascii=False, default=str) + "\n",
            encoding="utf-8",
        )

    def update_manifest(self, **updates: Any) -> None:
        manifest = json.loads(self.manifest_path.read_text(encoding="utf-8"))
        manifest.update(updates)
        self.manifest_path.write_text(
            json.dumps(manifest, indent=2, ensure_ascii=False, default=str) + "\n",
            encoding="utf-8",
        )

    async def append_failure(self, entry: Dict[str, Any]) -> None:
        """Append one JSON line to failures.jsonl (crash-safe, flushed)."""
        import aiofiles

        self.failures_path.parent.mkdir(parents=True, exist_ok=True)
        async with aiofiles.open(self.failures_path, mode="a", encoding="utf-8") as f:
            await f.write(json.dumps(entry, ensure_ascii=False, default=str) + "\n")
            await f.flush()
