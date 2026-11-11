from __future__ import annotations

import os
from dataclasses import dataclass, field
from pathlib import Path


@dataclass
class Settings:
    """Filesystem layout. All paths derive from `home` unless overridden."""

    home: Path = field(default_factory=lambda: Path(os.environ.get("MACRODB_HOME", "data")))
    config_dir: Path = field(default_factory=lambda: Path(os.environ.get("MACRODB_CONFIG", "config")))

    def __post_init__(self):
        self.home = Path(self.home)
        self.config_dir = Path(self.config_dir)

    @property
    def db_path(self) -> Path:
        return self.home / "macrodb.duckdb"

    @property
    def raw_dir(self) -> Path:
        return self.home / "raw"

    @property
    def parquet_dir(self) -> Path:
        return self.home / "parquet"

    @property
    def reports_dir(self) -> Path:
        return self.home / "reports"

    @property
    def providers_yaml(self) -> Path:
        return self.config_dir / "providers.yaml"

    @property
    def reference_yaml(self) -> Path:
        return self.config_dir / "reference.yaml"

    @property
    def catalog_yaml(self) -> Path:
        return self.config_dir / "catalog.yaml"


def load_dotenv(path: str | Path = ".env") -> None:
    """Minimal .env reader (KEY=value lines). Real environment variables take precedence."""
    p = Path(path)
    if not p.is_file():
        return
    for line in p.read_text().splitlines():
        line = line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        k, v = line.split("=", 1)
        v = v.strip().strip("'\"")
        if v:
            os.environ.setdefault(k.strip(), v)
