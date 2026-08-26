"""Connector options are a contract too.

`sources` used to be `dict[str, dict[str, Any]]`, which meant a misspelled
option was accepted, ignored, and replaced by a default. That is the quietest
failure in the system: with `publication_lag_minuts: 999` the connector reads 15
instead, ingestion succeeds, and every `first_observed_at` in bronze is wrong by
whatever the operator believed they had configured.
"""

from __future__ import annotations

import ast
from pathlib import Path

import pytest
import yaml
from pydantic import ValidationError

from pramaanx.config import (
    SOURCE_OPTION_MODELS,
    AcledSourceConfig,
    GdeltSourceConfig,
    Settings,
    SourceOptions,
    SyntheticSourceConfig,
    load_settings,
)
from pramaanx.ingest.base import available_connectors

CONNECTOR_DIR = Path(__file__).resolve().parents[2] / "src" / "pramaanx" / "ingest" / "connectors"


class TestTypoRejection:
    def test_publication_lag_minuts_is_rejected(self) -> None:
        with pytest.raises(ValidationError, match="publication_lag_minuts"):
            Settings.model_validate({"sources": {"gdelt": {"publication_lag_minuts": 999}}})

    def test_country_filer_is_rejected(self) -> None:
        with pytest.raises(ValidationError, match="country_filer"):
            Settings.model_validate({"sources": {"gdelt": {"country_filer": ["IN"]}}})

    def test_synthetic_typo_is_rejected(self) -> None:
        with pytest.raises(ValidationError, match="noise_per_dayy"):
            Settings.model_validate({"sources": {"synthetic": {"noise_per_dayy": 5}}})

    def test_the_error_names_the_source(self) -> None:
        # A bare "extra inputs are not permitted" gives no clue which block is
        # wrong when several sources are configured.
        with pytest.raises(ValidationError, match=r"invalid options for source 'gdelt'"):
            Settings.model_validate({"sources": {"gdelt": {"publication_lag_minuts": 1}}})

    def test_retired_acled_api_key_option_is_rejected(self) -> None:
        with pytest.raises(ValidationError, match="api_key"):
            Settings.model_validate({"sources": {"acled": {"api_key": "x"}}})

    def test_rejection_happens_at_load_time(self, tmp_path: Path) -> None:
        # Not when ingestion eventually runs: `pramaanx version` should fail.
        config = tmp_path / "base.yaml"
        config.write_text(
            yaml.safe_dump({"sources": {"gdelt": {"publication_lag_minuts": 999}}}),
            encoding="utf-8",
        )
        with pytest.raises(ValidationError, match="publication_lag_minuts"):
            load_settings(config, environ={})

    def test_typo_is_rejected_when_a_connector_is_built_directly(self) -> None:
        from pramaanx.ingest.connectors.gdelt import GdeltConnector

        with pytest.raises(ValidationError, match="publication_lag_minuts"):
            GdeltConnector(Settings(), {"publication_lag_minuts": 999})


class TestValidConfigurations:
    def test_valid_gdelt_configuration_loads(self) -> None:
        settings = Settings.model_validate(
            {
                "sources": {
                    "gdelt": {
                        "base_url": "https://example.org/gdeltv2",
                        "publication_lag_minutes": 30,
                        "max_rows_per_file": 500,
                        "country_filter": ["IN"],
                        "event_root_codes": ["14"],
                        "skip_missing_files": False,
                        "cache": False,
                        "timeout_seconds": 30.0,
                        "max_attempts": 2,
                        "backoff_seconds": 1.0,
                        "proxy": "socks5://127.0.0.1:1080",
                        "trust_env": False,
                        "ca_bundle": "/etc/ssl/corp.pem",
                        "verify": True,
                    }
                }
            }
        )
        options = settings.source_options("gdelt")
        assert isinstance(options, GdeltSourceConfig)
        assert options.publication_lag_minutes == 30
        assert options.proxy == "socks5://127.0.0.1:1080"

    def test_valid_synthetic_configuration_loads(self) -> None:
        settings = Settings.model_validate(
            {
                "sources": {
                    "synthetic": {
                        "seed": 7,
                        "world_start": "2025-01-01T00:00:00Z",
                        "world_end": "2026-07-01T00:00:00Z",
                        "noise_per_day": 5,
                    }
                }
            }
        )
        options = settings.source_options("synthetic")
        assert isinstance(options, SyntheticSourceConfig)
        assert options.seed == 7
        assert options.noise_per_day == 5.0

    def test_valid_acled_configuration_loads_without_credential_values(self) -> None:
        settings = Settings.model_validate(
            {
                "sources": {
                    "acled": {
                        "countries": ["India"],
                        "event_types": ["Protests"],
                        "page_size": 1000,
                        "max_pages": 200,
                        "access_token_env": "DEPLOYMENT_ACLED_TOKEN",
                        "max_retry_after_seconds": 30,
                    }
                }
            }
        )
        options = settings.source_options("acled")
        assert isinstance(options, AcledSourceConfig)
        assert options.page_size == 1000
        assert options.access_token_env == "DEPLOYMENT_ACLED_TOKEN"

    def test_acled_requires_https_and_bounded_pages(self) -> None:
        with pytest.raises(ValidationError, match="must use https"):
            Settings.model_validate({"sources": {"acled": {"base_url": "http://example.test"}}})
        with pytest.raises(ValidationError):
            Settings.model_validate({"sources": {"acled": {"page_size": 5001}}})

    def test_defaults_apply_when_a_source_is_unconfigured(self) -> None:
        assert Settings().source_options("gdelt").publication_lag_minutes == 15

    def test_unknown_source_lookup_raises(self) -> None:
        with pytest.raises(KeyError, match="unknown source 'unknown'"):
            Settings().source_options("unknown")

    def test_out_of_range_values_are_rejected(self) -> None:
        # Strictness is about more than spelling.
        with pytest.raises(ValidationError):
            Settings.model_validate({"sources": {"gdelt": {"max_attempts": 0}}})
        with pytest.raises(ValidationError):
            Settings.model_validate({"sources": {"gdelt": {"publication_lag_minutes": -5}}})


def consumed_option_names(module_path: Path) -> set[str]:
    """Every option name a connector module reads off its config object.

    Found by parsing rather than importing, so the test describes what the code
    actually does even if an attribute is read on a path no test exercises.
    """
    tree = ast.parse(module_path.read_text(encoding="utf-8"))
    names: set[str] = set()
    for node in ast.walk(tree):
        # config.foo / self._options.foo
        if isinstance(node, ast.Attribute) and isinstance(node.value, ast.Name):
            if node.value.id == "config":
                names.add(node.attr)
        elif isinstance(node, ast.Attribute) and isinstance(node.value, ast.Attribute):
            if node.value.attr == "_options":
                names.add(node.attr)
        # any surviving self.options.get("x")
        elif isinstance(node, ast.Call):
            func = node.func
            if (
                isinstance(func, ast.Attribute)
                and func.attr == "get"
                and node.args
                and isinstance(node.args[0], ast.Constant)
                and isinstance(node.args[0].value, str)
                and isinstance(func.value, ast.Attribute)
                and func.value.attr == "options"
            ):
                names.add(node.args[0].value)
    return names


class TestEveryConsumedOptionIsDeclared:
    @pytest.mark.parametrize(
        ("module", "model"),
        [
            ("acled.py", AcledSourceConfig),
            ("gdelt.py", GdeltSourceConfig),
            ("synthetic.py", SyntheticSourceConfig),
        ],
    )
    def test_consumed_options_are_declared(self, module: str, model: type[SourceOptions]) -> None:
        declared = set(model.model_fields)
        consumed = consumed_option_names(CONNECTOR_DIR / module)
        undeclared = consumed - declared
        assert not undeclared, (
            f"{module} reads {sorted(undeclared)} off its options, but "
            f"{model.__name__} does not declare them. An undeclared option is an "
            "option a config file cannot legally set."
        )

    def test_no_connector_reads_options_by_string_key(self) -> None:
        # options.get("x") is how the silent-typo bug worked: a string key that
        # nothing validates. Attribute access on a strict model cannot.
        for module in ("acled.py", "gdelt.py", "synthetic.py"):
            source = (CONNECTOR_DIR / module).read_text(encoding="utf-8")
            assert 'options.get("' not in source, f"{module} still reads options by string key"

    def test_every_registered_connector_has_an_options_model(self) -> None:
        assert set(available_connectors()) <= set(SOURCE_OPTION_MODELS)
        for source_id, connector in available_connectors().items():
            assert connector.options_model is SOURCE_OPTION_MODELS[source_id]


class TestConfigHash:
    def test_source_options_are_part_of_the_config_hash(self) -> None:
        # An experiment run with a different publication lag is a different
        # experiment, and the manifest has to say so.
        base = Settings()
        changed = Settings(sources={"gdelt": {"publication_lag_minutes": 30}})
        assert base.config_hash != changed.config_hash

    def test_equal_source_options_hash_equally(self) -> None:
        first = Settings(sources={"synthetic": {"seed": 7}})
        second = Settings(sources={"synthetic": {"seed": 7}})
        assert first.config_hash == second.config_hash

    def test_shipped_configs_declare_only_known_options(self) -> None:
        for path in sorted(Path("configs").rglob("*.yaml")):
            raw = yaml.safe_load(path.read_text(encoding="utf-8")) or {}
            if "backtest" in raw:
                Settings.model_validate(raw.get("settings", {}))
            else:
                load_settings(path, environ={})
