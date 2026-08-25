"""Configuration layering, overrides and hashing."""

from __future__ import annotations

from pathlib import Path

import pytest
from pydantic import ValidationError

from pramaanx.config import Settings, dotted_overrides, load_settings


def write(path: Path, text: str) -> Path:
    path.write_text(text, encoding="utf-8")
    return path


class TestLayering:
    def test_includes_are_merged_with_the_child_winning(self, tmp_path: Path) -> None:
        write(tmp_path / "base.yaml", "horizon_days: 90\nrandom_seed: 1\n")
        child = write(tmp_path / "child.yaml", "include: base.yaml\nhorizon_days: 30\n")
        settings = load_settings(child, environ={})
        assert settings.horizon_days == 30
        assert settings.random_seed == 1

    def test_circular_includes_are_rejected(self, tmp_path: Path) -> None:
        write(tmp_path / "a.yaml", "include: b.yaml\n")
        write(tmp_path / "b.yaml", "include: a.yaml\n")
        with pytest.raises(ValueError, match="circular"):
            load_settings(tmp_path / "a.yaml", environ={})

    def test_explicit_overrides_beat_everything(self, tmp_path: Path) -> None:
        config = write(tmp_path / "base.yaml", "horizon_days: 90\n")
        settings = load_settings(
            config, overrides={"horizon_days": 7}, environ={"PRAMAANX_HORIZON_DAYS": "45"}
        )
        assert settings.horizon_days == 7

    def test_environment_maps_onto_nested_keys(self, tmp_path: Path) -> None:
        config = write(tmp_path / "base.yaml", "horizon_days: 90\n")
        settings = load_settings(
            config,
            environ={"PRAMAANX_GENERATORS__PROPOSAL_BUDGET": "42", "PRAMAANX_LOG_LEVEL": "DEBUG"},
        )
        assert settings.generators.proposal_budget == 42
        assert settings.log_level == "DEBUG"

    def test_source_credentials_are_not_settings(self, tmp_path: Path) -> None:
        # PRAMAANX_ACLED_API_KEY is read by a connector, not folded into config,
        # so a credential can never end up inside a config hash.
        config = write(tmp_path / "base.yaml", "horizon_days: 90\n")
        settings = load_settings(config, environ={"PRAMAANX_ACLED_API_KEY": "secret"})
        assert "secret" not in settings.model_dump_json()


class TestDottedOverrides:
    def test_parses_nested_paths_and_types(self) -> None:
        assert dotted_overrides(["risk.target=0.9", "generators.enabled=[a, b]"]) == {
            "risk": {"target": 0.9},
            "generators": {"enabled": ["a", "b"]},
        }

    def test_malformed_override_is_rejected(self) -> None:
        with pytest.raises(ValueError, match=r"key\.path=value"):
            dotted_overrides(["nonsense"])


class TestValidation:
    def test_unknown_keys_are_rejected(self) -> None:
        with pytest.raises(ValidationError):
            Settings.model_validate({"not_a_real_setting": 1})

    def test_alert_thresholds_must_be_ordered(self) -> None:
        with pytest.raises(ValidationError, match="alert >= watch >= monitor"):
            Settings.model_validate({"alerting": {"alert_threshold": 0.1, "watch_threshold": 0.5}})

    def test_config_hash_tracks_content_not_object_identity(self) -> None:
        assert Settings().config_hash == Settings().config_hash
        assert Settings().config_hash != Settings(horizon_days=7).config_hash


class TestLoggingStreams:
    """Reconfiguring logging must never leave a logger holding a dead stream."""

    def test_logging_survives_a_replaced_stderr(self, capsys: pytest.CaptureFixture[str]) -> None:
        import io
        import sys

        from pramaanx.logging import configure_logging, get_logger

        configure_logging("INFO", "json")
        logger = get_logger("test.stream")
        logger.info("first")

        # Exactly what a CLI reconfiguring in-process, a supervisor redirecting
        # output, or a test harness swapping capture buffers does.
        original = sys.stderr
        replacement = io.StringIO()
        sys.stderr = replacement
        try:
            logger.info("second")
            assert "second" in replacement.getvalue()
        finally:
            sys.stderr = original

    def test_logging_survives_a_closed_stderr(self) -> None:
        import io
        import sys

        from pramaanx.logging import configure_logging, get_logger

        configure_logging("INFO", "json")
        logger = get_logger("test.closed")

        original = sys.stderr
        closed = io.StringIO()
        sys.stderr = closed
        logger.info("before close")
        closed.close()
        replacement = io.StringIO()
        sys.stderr = replacement
        try:
            # Binding the stream at configuration time raised
            # "I/O operation on closed file" here.
            logger.info("after close")
            assert "after close" in replacement.getvalue()
        finally:
            sys.stderr = original
