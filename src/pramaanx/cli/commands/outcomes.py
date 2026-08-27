"""Outcome registry construction."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Annotated, Any

import typer

from pramaanx.cli._app import (
    ConfigOption,
    DryRunOption,
    OutputOption,
    SetOption,
    _emit,
    _parse_moment,
    _settings,
    outcomes_app,
)
from pramaanx.hashing import hash_object

InputOption = Annotated[Path, typer.Option("--input", exists=True, dir_okay=False)]
DataOutputOption = Annotated[Path, typer.Option("--data-output", dir_okay=False)]


def _read_records(path: Path) -> list[dict[str, Any]]:
    text = path.read_text(encoding="utf-8")
    if not text.strip():
        return []
    if text.lstrip().startswith("["):
        value = json.loads(text)
        if not isinstance(value, list) or not all(isinstance(item, dict) for item in value):
            raise typer.BadParameter("input JSON must be an array of objects")
        return value
    records: list[dict[str, Any]] = []
    for line_number, line in enumerate(text.splitlines(), start=1):
        if not line.strip():
            continue
        value = json.loads(line)
        if not isinstance(value, dict):
            raise typer.BadParameter(f"JSONL line {line_number} is not an object")
        records.append(value)
    return records


def _write_records(path: Path, records: list[dict[str, Any]]) -> None:
    if path.exists():
        raise typer.BadParameter(f"refusing to overwrite existing output: {path}")
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        "".join(
            json.dumps(record, sort_keys=True, separators=(",", ":")) + "\n" for record in records
        ),
        encoding="utf-8",
    )


@outcomes_app.command("build")
def outcomes_build(
    config: ConfigOption = Path("configs/base.yaml"),
    set_: SetOption = None,
    dry_run: DryRunOption = False,
    output: OutputOption = None,
) -> None:
    """Derive the provisional outcome registry from post-event reporting."""
    from pramaanx.ingest.ledger import EvidenceLedger
    from pramaanx.ledger.resolutions import adjudication_summary, build_outcome_registry

    settings = _settings(config, set_)
    ledger = EvidenceLedger(settings)
    outcomes = build_outcome_registry(ledger, ledger.read_observations())
    written = 0 if dry_run else ledger.write_outcomes(outcomes).written
    _emit(
        {
            "kind": "outcomes",
            "dry_run": dry_run,
            "outcomes": len(outcomes),
            "written": written,
            "adjudication": adjudication_summary(outcomes),
        },
        output,
    )


@outcomes_app.command("normalize")
def outcomes_normalize(
    input_: InputOption,
    data_output: DataOutputOption,
    source: Annotated[str, typer.Option("--source")],
    source_version: Annotated[str, typer.Option("--source-version")],
    source_record_id_column: Annotated[str, typer.Option("--id-column")],
    event_family_column: Annotated[str, typer.Option("--event-family-column")],
    occurred_at_column: Annotated[str, typer.Option("--occurred-at-column")],
    first_resolvable_at_column: Annotated[str, typer.Option("--first-resolvable-at-column")],
    district_id_column: Annotated[str | None, typer.Option("--district-id-column")] = None,
    correction_version_column: Annotated[
        str | None, typer.Option("--correction-version-column")
    ] = None,
    dry_run: DryRunOption = False,
    output: OutputOption = None,
) -> None:
    """Normalize a pinned ACLED/UCDP-style export into incident JSONL."""
    from pramaanx.outcomes.normalize import IncidentColumnMap, normalize_incident_rows

    incidents = normalize_incident_rows(
        _read_records(input_),
        source=source,
        source_version=source_version,
        columns=IncidentColumnMap(
            source_record_id=source_record_id_column,
            event_family=event_family_column,
            occurred_at=occurred_at_column,
            first_resolvable_at=first_resolvable_at_column,
            district_id=district_id_column,
            correction_version=correction_version_column,
        ),
    )
    records = [incident.model_dump(mode="json") for incident in incidents]
    if not dry_run:
        _write_records(data_output, records)
    _emit(
        {
            "kind": "district-incidents",
            "dry_run": dry_run,
            "records": len(records),
            "source": source,
            "source_version": source_version,
            "input_hash": hash_object(_read_records(input_)),
            "output_hash": hash_object(records),
            "data_output": str(data_output),
        },
        output,
    )


@outcomes_app.command("build-panel")
def outcomes_build_panel(
    registry: Annotated[Path, typer.Option("--registry", exists=True, dir_okay=False)],
    incidents: Annotated[Path, typer.Option("--incidents", exists=True, dir_okay=False)],
    cutoff: Annotated[list[str], typer.Option("--cutoff")],
    observation_end: Annotated[str, typer.Option("--observation-end")],
    data_output: DataOutputOption,
    config: ConfigOption = Path("configs/base.yaml"),
    set_: SetOption = None,
    reporting_delay_days: Annotated[int, typer.Option("--reporting-delay-days", min=0)] = 0,
    dry_run: DryRunOption = False,
    output: OutputOption = None,
) -> None:
    """Build the dense district-cutoff-family outcome panel."""
    from pramaanx.geography.registry import DistrictRegistry, DistrictRegistryEntry
    from pramaanx.outcomes.models import NormalizedIncident
    from pramaanx.outcomes.panel import build_district_outcome_panel

    settings = _settings(config, set_)
    registry_rows = _read_records(registry)
    incident_rows = _read_records(incidents)
    panel = build_district_outcome_panel(
        registry=DistrictRegistry(
            DistrictRegistryEntry.model_validate(record) for record in registry_rows
        ),
        incidents=(NormalizedIncident.model_validate(record) for record in incident_rows),
        cutoffs=[_parse_moment(value) for value in cutoff],
        event_families=settings.district_forecasting.event_families,
        horizon_days=settings.district_forecasting.horizon_days,
        observation_end=_parse_moment(observation_end),
        reporting_delay_days=reporting_delay_days,
    )
    records = [row.model_dump(mode="json") for row in panel]
    if not dry_run:
        _write_records(data_output, records)
    _emit(
        {
            "kind": "district-outcome-panel",
            "dry_run": dry_run,
            "rows": len(records),
            "cutoffs": sorted(set(cutoff)),
            "input_hashes": {
                "registry": hash_object(registry_rows),
                "incidents": hash_object(incident_rows),
            },
            "output_hash": hash_object(records),
            "config_hash": settings.config_hash,
            "data_output": str(data_output),
        },
        output,
    )


@outcomes_app.command("validate-panel")
def outcomes_validate_panel(
    input_: InputOption,
    output: OutputOption = None,
) -> None:
    """Validate a previously committed district outcome panel."""
    from pramaanx.outcomes.models import DistrictOutcomeRow
    from pramaanx.outcomes.panel import validate_panel

    raw = _read_records(input_)
    rows = [DistrictOutcomeRow.model_validate(record) for record in raw]
    validate_panel(rows)
    _emit(
        {
            "kind": "district-outcome-panel-validation",
            "valid": True,
            "rows": len(rows),
            "input_hash": hash_object(raw),
        },
        output,
    )
