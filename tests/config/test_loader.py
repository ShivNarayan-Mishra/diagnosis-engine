"""
tests/config/test_loader.py

Direct unit tests for PipelineConfig / load_pipeline_config. Every prior
confirmation of this module's correctness was indirect -- exercised through
UnivariateDiagnosisEngine (test_config_populates_cause_layer) or observed via
run_benchmark.py's printed cause_layer output across five scenario types
(running_log_phase6.md) -- but nothing tested this module in isolation before
now. Closes the same category of gap test_scorer.py closed for scorer.py
(running_log_phase6.md Entry 5).
"""
from pathlib import Path

import pytest
import yaml

from src.config.loader import PipelineConfig, load_pipeline_config


def test_load_returns_none_when_file_does_not_exist(tmp_path):
    missing = tmp_path / "does_not_exist.yaml"
    assert load_pipeline_config(missing) is None


def test_load_returns_none_gracefully_not_an_error(tmp_path):
    """
    A missing config file is the normal, expected case for a pipeline that
    hasn't supplied one -- confirms this doesn't raise, matching the
    docstring's explicit contract ("callers should treat None exactly like
    'no config'... not as an error").
    """
    missing = tmp_path / "nope.yaml"
    try:
        result = load_pipeline_config(missing)
    except Exception as e:
        pytest.fail(f"load_pipeline_config raised {e!r} instead of returning None")
    assert result is None


def test_load_valid_config(tmp_path):
    config_path = tmp_path / "pipeline_config.yaml"
    config_path.write_text(
        """
name: "test-pipeline"
factors:
  tool_version:
    type: categorical
    layer: tool
  retrieval_score:
    type: continuous
    layer: retrieval
"""
    )
    config = load_pipeline_config(config_path)
    assert config is not None
    assert config.name == "test-pipeline"
    assert config.factor_type("tool_version") == "categorical"
    assert config.factor_layer("tool_version") == "tool"
    assert config.factor_type("retrieval_score") == "continuous"
    assert config.factor_layer("retrieval_score") == "retrieval"


def test_factor_type_and_layer_return_none_for_undeclared_key(tmp_path):
    config_path = tmp_path / "pipeline_config.yaml"
    config_path.write_text(
        """
name: "test-pipeline"
factors:
  tool_version:
    type: categorical
    layer: tool
"""
    )
    config = load_pipeline_config(config_path)
    assert config.factor_type("some_key_never_declared") is None
    assert config.factor_layer("some_key_never_declared") is None


def test_empty_yaml_file_does_not_crash(tmp_path):
    """
    yaml.safe_load on a completely empty file returns None, not {} --
    the `raw = yaml.safe_load(f) or {}` line exists specifically to catch
    this and guarantee raw is always a real dict. Confirms that guard
    actually works, not just that it's present in the source.
    """
    config_path = tmp_path / "empty.yaml"
    config_path.write_text("")

    config = load_pipeline_config(config_path)
    assert config is not None
    assert config.name is None
    assert config.factors == {}


def test_config_missing_name_field(tmp_path):
    config_path = tmp_path / "no_name.yaml"
    config_path.write_text(
        """
factors:
  intent:
    type: categorical
    layer: taxonomy
"""
    )
    config = load_pipeline_config(config_path)
    assert config.name is None
    assert config.factor_type("intent") == "categorical"


def test_config_missing_factors_field(tmp_path):
    config_path = tmp_path / "no_factors.yaml"
    config_path.write_text('name: "test-pipeline"\n')

    config = load_pipeline_config(config_path)
    assert config.name == "test-pipeline"
    assert config.factors == {}
    assert config.factor_type("anything") is None


def test_pipeline_config_default_construction():
    """
    PipelineConfig() with no arguments -- confirms the dataclass defaults
    (name=None, factors=field(default_factory=dict)) work standalone, not
    just via load_pipeline_config. Also guards against the classic mutable-
    default-argument trap: two separately-constructed PipelineConfig objects
    must not share the same underlying factors dict.
    """
    config_a = PipelineConfig()
    config_b = PipelineConfig()
    assert config_a.name is None
    assert config_a.factors == {}

    config_a.factors["leaked"] = {"type": "categorical", "layer": "tool"}
    assert "leaked" not in config_b.factors


def test_accepts_string_path_not_just_pathlib_path(tmp_path):
    """load_pipeline_config's type hint is `str | Path` -- confirm the str branch actually works, not just Path objects."""
    config_path = tmp_path / "pipeline_config.yaml"
    config_path.write_text('name: "string-path-test"\nfactors: {}\n')

    config = load_pipeline_config(str(config_path))
    assert config is not None
    assert config.name == "string-path-test"


def test_real_project_pipeline_config_loads_and_declares_all_five_factors():
    """
    Confirms the actual, current pipeline_config.yaml at the project root --
    not a synthetic tmp_path fixture -- loads correctly and declares every
    factor now used by any scenario built through Phase 6
    (running_log_phase6.md): tool_version, model_version, retrieval_score,
    intent, error_type. Skipped if run somewhere the real file isn't at the
    expected relative path (e.g. a sandbox without it), rather than failing
    for an unrelated reason.
    """
    real_config_path = Path("pipeline_config.yaml")
    if not real_config_path.exists():
        pytest.skip("pipeline_config.yaml not found relative to cwd — run pytest from the project root")

    config = load_pipeline_config(real_config_path)
    assert config is not None
    for key, expected_type, expected_layer in [
        ("tool_version", "categorical", "tool"),
        ("model_version", "categorical", "model"),
        ("retrieval_score", "continuous", "retrieval"),
        ("intent", "categorical", "taxonomy"),
        ("error_type", "categorical", "infra"),
    ]:
        assert config.factor_type(key) == expected_type, f"{key} type mismatch"
        assert config.factor_layer(key) == expected_layer, f"{key} layer mismatch"