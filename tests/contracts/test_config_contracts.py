"""Configuration is a contract too: a typo must be an error, never a default.

A misspelled key in YAML is the quietest possible failure. The run succeeds, the
default applies, and the report describes an experiment nobody configured. Every
block therefore forbids unknown fields.
"""

from __future__ import annotations

from pathlib import Path

import pytest
import yaml
from pydantic import ValidationError

from pramaanx.config import (
    AlertPolicyConfig,
    ConfigModel,
    EvaluationConfig,
    GeneratorConfig,
    Settings,
    StorageConfig,
    TimeguardConfig,
    load_settings,
)

CONFIG_BLOCKS = [
    StorageConfig,
    TimeguardConfig,
    GeneratorConfig,
    AlertPolicyConfig,
    EvaluationConfig,
    Settings,
]

#: (dotted path, the plausible typo). Each is a real field name with one letter
#: moved -- the kind of thing that survives review.
NESTED_TYPOS = [
    ("evaluation", "match_min_socre", 0.5),
    ("evaluation", "time_bucket", ["0-1d"]),
    ("evaluation", "max_reporting_delay_day", 3.0),
    ("storage", "data_rooot", "/tmp/x"),
    ("storage", "parquet_compresion", "zstd"),
    ("timeguard", "stricct", True),
    ("timeguard", "max_future_skew_second", 0),
    ("generators", "proposal_budgets", 100),
    ("generators", "lookback_day", 30),
    ("alerting", "alert_treshold", 0.5),
    ("alerting", "min_evidence_item", 1),
]


class TestEveryBlockForbidsExtras:
    @pytest.mark.parametrize("model", CONFIG_BLOCKS, ids=lambda m: m.__name__)
    def test_block_rejects_unknown_fields(self, model: type[ConfigModel]) -> None:
        with pytest.raises(ValidationError) as error:
            model.model_validate({"definitely_not_a_field": 1})
        assert error.value.errors()[0]["type"] == "extra_forbidden"

    @pytest.mark.parametrize("model", CONFIG_BLOCKS, ids=lambda m: m.__name__)
    def test_block_inherits_the_shared_base(self, model: type[ConfigModel]) -> None:
        # Inheritance rather than a per-class setting, so a new block cannot be
        # added without the protection.
        assert issubclass(model, ConfigModel)
        assert model.model_config.get("extra") == "forbid"


class TestNestedTypos:
    @pytest.mark.parametrize(
        ("block", "typo", "value"), NESTED_TYPOS, ids=[f"{b}.{t}" for b, t, _ in NESTED_TYPOS]
    )
    def test_nested_typo_is_rejected(self, block: str, typo: str, value: object) -> None:
        with pytest.raises(ValidationError) as error:
            Settings.model_validate({block: {typo: value}})
        reported = error.value.errors()[0]
        assert reported["type"] == "extra_forbidden"
        assert reported["loc"] == (block, typo)

    def test_typo_in_a_yaml_file_is_rejected(self, tmp_path: Path) -> None:
        # The path that matters in practice: a hand-edited config file.
        config = tmp_path / "base.yaml"
        config.write_text(
            yaml.safe_dump({"evaluation": {"match_min_socre": 0.9}}), encoding="utf-8"
        )
        with pytest.raises(ValidationError, match="match_min_socre"):
            load_settings(config, environ={})

    def test_typo_in_an_override_is_rejected(self, tmp_path: Path) -> None:
        config = tmp_path / "base.yaml"
        config.write_text("horizon_days: 30\n", encoding="utf-8")
        with pytest.raises(ValidationError, match="match_min_socre"):
            load_settings(config, overrides={"evaluation": {"match_min_socre": 0.9}}, environ={})

    def test_typo_in_an_environment_variable_is_rejected(self, tmp_path: Path) -> None:
        config = tmp_path / "base.yaml"
        config.write_text("horizon_days: 30\n", encoding="utf-8")
        with pytest.raises(ValidationError, match="match_min_socre"):
            load_settings(config, environ={"PRAMAANX_EVALUATION__MATCH_MIN_SOCRE": "0.9"})

    def test_the_correctly_spelled_field_still_works(self, tmp_path: Path) -> None:
        config = tmp_path / "base.yaml"
        config.write_text(
            yaml.safe_dump({"evaluation": {"match_min_score": 0.9}}), encoding="utf-8"
        )
        assert load_settings(config, environ={}).evaluation.match_min_score == 0.9


class TestShippedConfigs:
    @pytest.mark.parametrize(
        "path",
        sorted(Path("configs").rglob("*.yaml")),
        ids=lambda p: str(p),
    )
    def test_every_shipped_config_validates(self, path: Path) -> None:
        # Catches a typo committed into the repository's own configs.
        raw = yaml.safe_load(path.read_text(encoding="utf-8")) or {}
        if "backtest" in raw:  # experiment file: settings live under a key
            Settings.model_validate(raw.get("settings", {}))
        else:
            load_settings(path, environ={})
