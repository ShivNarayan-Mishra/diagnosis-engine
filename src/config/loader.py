"""
Minimal pipeline_config.yaml loader.

Optional input, per the original plan doc's framing: the engine works without
it (falls back to type-guessing from values, cause_layer="unknown"). This file
only improves test selection and layer labeling when a config file exists.

No pipeline_config.yaml or loader existed anywhere in the project before this
phase — confirmed absent, built fresh here rather than assumed/reconstructed.
"""
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
    """
    Returns None if the file doesn't exist. That's the normal, expected case
    for a pipeline that hasn't supplied a config — callers should treat None
    exactly like "no config" (type-guessing + cause_layer='unknown'), not as
    an error.
    """
    p = Path(path)
    if not p.exists():
        return None

    with p.open("r") as f:
        raw = yaml.safe_load(f) or {}

    return PipelineConfig(
        name=raw.get("name"),
        factors=raw.get("factors", {}) or {},
    )