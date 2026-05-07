"""On-disk Drive cache: TTL bookkeeping under ``<cache>/.meta/``.

A single JSON file (``fetched-at.json``) maps relative cache paths to
their last-fetched epoch seconds. The hydrator consults
:meth:`is_fresh` before downloading and calls :meth:`record` after a
successful fetch.
"""

from __future__ import annotations

import json
import time
from pathlib import Path

_META_DIR = ".meta"
_META_FILE = "fetched-at.json"


class CacheMeta:
    """Tracks fetched-at timestamps for files inside a cache root."""

    def __init__(self, cache_root: Path, *, clock=None) -> None:
        self._root = cache_root
        self._meta_path = cache_root / _META_DIR / _META_FILE
        self._clock = clock or time.time
        self._data: dict[str, float] = self._load()

    def _load(self) -> dict[str, float]:
        if not self._meta_path.is_file():
            return {}
        try:
            with self._meta_path.open("r", encoding="utf-8") as fh:
                raw = json.load(fh)
        except (OSError, ValueError):
            return {}
        if not isinstance(raw, dict):
            return {}
        out: dict[str, float] = {}
        for key, value in raw.items():
            try:
                out[str(key)] = float(value)
            except (TypeError, ValueError):
                continue
        return out

    def is_fresh(self, rel_path: str, ttl_seconds: int) -> bool:
        """``True`` if ``rel_path`` was fetched within the last ``ttl`` seconds."""
        if ttl_seconds <= 0:
            return False
        last = self._data.get(rel_path)
        if last is None:
            return False
        return (self._clock() - last) < ttl_seconds

    def record(self, rel_path: str) -> None:
        """Stamp ``rel_path`` as fetched now and persist the meta file."""
        self._data[rel_path] = float(self._clock())
        self._meta_path.parent.mkdir(parents=True, exist_ok=True)
        with self._meta_path.open("w", encoding="utf-8") as fh:
            json.dump(self._data, fh, indent=2, sort_keys=True)
