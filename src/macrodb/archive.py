from __future__ import annotations

import gzip
import hashlib
from datetime import datetime, timezone
from pathlib import Path


class RawArchive:
    """Content-addressed, gzip-compressed archive of raw API responses.

    Layout: <root>/<provider>/<YYYY>/<MM>/<sha256>.<ext>.gz. Files are written once and
    never modified; identical payloads dedupe to the same file."""

    def __init__(self, root: Path):
        self.root = Path(root)

    @staticmethod
    def _ext(content_type: str) -> str:
        ct = (content_type or "").lower()
        for key, ext in (("json", "json"), ("csv", "csv"), ("xml", "xml"), ("html", "html")):
            if key in ct:
                return ext
        return "bin"

    def put(self, provider_id: str, content: bytes, content_type: str = "",
            when: datetime | None = None) -> tuple[str, str, int]:
        """Returns (relative_path, sha256, byte_size)."""
        when = when or datetime.now(timezone.utc)
        sha = hashlib.sha256(content).hexdigest()
        rel = Path(provider_id) / f"{when:%Y}" / f"{when:%m}" / f"{sha}.{self._ext(content_type)}.gz"
        path = self.root / rel
        if not path.exists():
            path.parent.mkdir(parents=True, exist_ok=True)
            tmp = path.with_suffix(path.suffix + ".tmp")
            tmp.write_bytes(gzip.compress(content, mtime=0))
            tmp.replace(path)
        return rel.as_posix(), sha, len(content)

    def get(self, rel_path: str) -> bytes:
        return gzip.decompress((self.root / rel_path).read_bytes())
