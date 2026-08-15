"""Single persistent JSONL output writer (P7.6)."""

from __future__ import annotations

import asyncio
import json
from pathlib import Path
from typing import Any, Dict, Optional

import aiofiles


class JsonlStreamWriter:
    """Append-only JSONL writer, opened once and flushed per write.

    Owned by the engine when the CLI provides a run context, replacing the
    open-per-flush writer in main.py.
    """

    def __init__(self, path: Path) -> None:
        self.path = Path(path)
        self._file: Optional[Any] = None
        self._lock = asyncio.Lock()

    async def open(self) -> None:
        async with self._lock:
            await self._open_unlocked()

    async def _open_unlocked(self) -> None:
        if self._file is None:
            self.path.parent.mkdir(parents=True, exist_ok=True)
            self._file = await aiofiles.open(self.path, mode="a", encoding="utf-8")

    async def write(self, data: Dict[str, Any]) -> None:
        async with self._lock:
            await self._open_unlocked()
            # Serialize to one complete line before writing so a cancellation
            # can never leave a partial record on disk.
            line = json.dumps(data, ensure_ascii=False, default=str) + "\n"
            assert self._file is not None
            await self._file.write(line)
            await self._file.flush()

    async def close(self) -> None:
        async with self._lock:
            if self._file is not None:
                await self._file.close()
                self._file = None

    async def __aenter__(self) -> "JsonlStreamWriter":
        await self.open()
        return self

    async def __aexit__(self, *exc_info) -> None:
        await self.close()
