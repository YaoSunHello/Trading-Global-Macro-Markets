from __future__ import annotations

from importlib import import_module
from pathlib import Path
from typing import Callable

import yaml

from .http import HttpClient, ProviderError
from .providers.base import ProviderAdapter


class ProviderRegistry:
    """Configurable provider registry backed by providers.yaml.

    Adding a provider = a new adapter class + one YAML entry. Nothing else changes."""

    def __init__(self, config: dict[str, dict], http_factory: Callable[[dict], HttpClient] | None = None):
        self.config = config
        self._http_factory = http_factory or (
            lambda c: HttpClient(min_interval_s=60.0 / c["rate_limit_per_min"] if c.get("rate_limit_per_min") else 0.0))
        self._cache: dict[str, ProviderAdapter] = {}

    @classmethod
    def from_yaml(cls, path: Path, **kw) -> "ProviderRegistry":
        doc = yaml.safe_load(Path(path).read_text()) or {}
        cfg = {}
        for p in doc.get("providers", []):
            if "provider_id" not in p or "adapter" not in p:
                raise ValueError(f"provider entry needs provider_id and adapter: {p}")
            cfg[p["provider_id"]] = p
        return cls(cfg, **kw)

    def ids(self, enabled_only: bool = False) -> list[str]:
        return [k for k, v in self.config.items() if v.get("enabled", True) or not enabled_only]

    def get(self, provider_id: str) -> ProviderAdapter:
        if provider_id not in self.config:
            raise ProviderError(f"provider '{provider_id}' is not registered")
        if provider_id not in self._cache:
            c = self.config[provider_id]
            mod, _, cls_name = c["adapter"].rpartition(".")
            adapter_cls = getattr(import_module(mod), cls_name)
            adapter = adapter_cls(self._http_factory(c), c)
            adapter.provider_id = provider_id
            self._cache[provider_id] = adapter
        return self._cache[provider_id]

    def register_instance(self, provider_id: str, adapter: ProviderAdapter) -> None:
        """Inject a ready adapter (tests, custom code)."""
        adapter.provider_id = provider_id
        self._cache[provider_id] = adapter
