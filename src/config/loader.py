
from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

import yaml


@dataclass
class PipelineConfig:
    name: str | None = None
    factors: dict[str, dict[str, Any]] = field(default_factory=dict)

    def factor_type(self, key: str) -> str | None:
        """'categorical' | 'continuous' | None if this key isn't declared."""
        entry = self.factors.get(key)
        if entry is None:
            return None
        return entry.get("type")

    def factor_layer(self, key: str) -> str | None:
        """The cause_layer this factor maps to, or None if undeclared."""
        entry = self.factors.get(key)
        if entry is None:
            return None
        return entry.get("layer")


def load_pipeline_config(path: str | Path) -> PipelineConfig | None:

    p = Path(path)
    if not p.exists():
        return None

    with p.open("r") as f:
        raw = yaml.safe_load(f) or {}

    return PipelineConfig(
        name=raw.get("name"),
        factors=raw.get("factors", {}) or {},
    )