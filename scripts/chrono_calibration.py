"""Strictly chronological calibration experiment.

Selects a calibration method under nested temporal validation and tests the
frozen choice on an untouched future block. Four rules are enforced, and each
one exists because breaking it produces a better-looking number than the system
has earned:

1. *Maturity gates the fit.* A calibrator for a forecast at cutoff T may only
   see folds whose horizon and reporting delay both closed by T. Being earlier
   is not enough.
2. *The choice is frozen before the test block is opened.* Methods are ranked on
   validation folds drawn from the development block only; the winner is then
   applied to a test block that took no part in the ranking.
3. *Skill is measured against earlier-period references.* Climatology is the
   base rate of matured earlier folds, not of the fold being scored. Persistence
   repeats the last matured window's positive streams.
4. *No t-tests across overlapping folds.* A 30-day horizon at a 7-day step puts
   the same days in five folds; intervals come from a moving-block bootstrap
   whose block spans the overlap.

Reported alongside: unique-outcome top-k, because the matcher is many-to-one and
label hits double-count a single event, and a one-to-one matching sensitivity
that re-scores everything under a greedy exclusive assignment.

Run:  uv run python scripts/chrono_calibration.py
"""

from __future__ import annotations

import json
from dataclasses import dataclass, field
from datetime import datetime
from pathlib import Path
from typing import Any

from pramaanx.calibration.base import IdentityCalibrator
from pramaanx.calibration.fitters import (
    MIN_SAMPLE_SIZE,
    BetaCalibrator,
    CalibrationSample,
    IsotonicCalibrator,
    PlattCalibrator,
)
from pramaanx.evaluation import metrics
from pramaanx.evaluation.backtest import Backtester, load_experiment
from pramaanx.evaluation.chrono import (
    climatology,
    is_mature,
    moving_block_bootstrap,
    one_to_one_labels,
    overlap_depth,
    paired_block_bootstrap,
    persistence,
    skill_score,
    unique_outcome_topk,
)
from pramaanx.hashing import stable_id

EXPERIMENT = Path("configs/experiments/chrono_calib_v1.yaml")
BUDGETS = (25, 50, 100)
METHODS = ("identity", "platt", "isotonic", "beta")
#: Fraction of the scoreable walk sealed as the untouched future test block.
TEST_FRACTION = 0.30
#: A validation fold needs at least this many matured folds behind it.
MIN_HISTORY_FOLDS = 2


def _new_calibrator(method: str) -> Any:
    return {
        "identity": IdentityCalibrator,
        "platt": PlattCalibrator,
        "isotonic": IsotonicCalibrator,
        "beta": BetaCalibrator,
    }[method]()


@dataclass
class FoldData:
    """One scoreable fold, flattened to arrays aligned by forecast."""

    index: int
    cutoff_at: datetime
    probabilities: list[float]
    labels: list[int]
    matched: list[bool]
    outcome_ids: list[str | None]
    match_scores: list[float]
    forecast_ids: list[str]
    stream_keys: list[str]
    outcomes_in_window: int
    one_to_one: list[bool] = field(default_factory=list)

    def labels_for(self, *, exclusive: bool) -> list[int]:
        return [int(v) for v in (self.one_to_one if exclusive else self.matched)]

    def positive_streams(self, *, exclusive: bool) -> set[str]:
        keep = self.one_to_one if exclusive else self.matched
        return {self.stream_keys[i] for i, hit in enumerate(keep) if hit}


def collect_folds() -> tuple[list[FoldData], int, float, int]:
    """Run the two backtest passes and flatten every scoreable fold."""
    spec, settings = load_experiment(EXPERIMENT)
    backtester = Backtester(settings)
    plans = backtester.forecasting_pass(spec)
    scoring = backtester.scoring_pass(spec, plans)

    folds: list[FoldData] = []
    for fold in scoring.folds:
        if not fold.scoreable:
            continue
        # Re-read from the ledger in the same order the scorer used, so
        # forecasts and matches stay aligned by position.
        forecasts = sorted(
            backtester.forecast_ledger.for_snapshot(fold.snapshot_hash),
            key=lambda item: item.forecast_id,
        )
        if len(forecasts) != len(fold.matches):
            raise RuntimeError(f"fold {fold.cutoff_at}: forecast/match length mismatch")
        data = FoldData(
            index=len(folds),
            cutoff_at=fold.cutoff_at,
            probabilities=[f.calibrated_probability for f in forecasts],
            labels=[1 if m.matched else 0 for m in fold.matches],
            matched=[m.matched for m in fold.matches],
            outcome_ids=[m.outcome_id for m in fold.matches],
            match_scores=[m.score for m in fold.matches],
            forecast_ids=[f.forecast_id for f in forecasts],
            stream_keys=[
                "|".join(
                    [
                        f.hypothesis.event_type,
                        f.hypothesis.most_likely_location() or "UNKNOWN_REGION",
                        ",".join(f.hypothesis.actor_ids) or "UNKNOWN_ACTOR",
                    ]
                )
                for f in forecasts
            ],
            outcomes_in_window=fold.outcomes_in_window,
        )
        data.one_to_one = one_to_one_labels(
            data.forecast_ids, data.matched, data.outcome_ids, data.match_scores
        )
        folds.append(data)
    return folds, spec.horizon_days, scoring.boundary.reporting_delay_days, spec.step_days


def eligible_history(
    folds: list[FoldData], target: FoldData, horizon: int, delay: float, limit_index: int | None
) -> list[FoldData]:
    """Matured folds strictly before ``target``, optionally capped to a block."""
    return [
        f
        for f in folds
        if f.index < target.index
        and (limit_index is None or f.index < limit_index)
        and is_mature(f.cutoff_at, target.cutoff_at, horizon, delay)
    ]


def score_fold(
    fold: FoldData, history: list[FoldData], method: str, *, exclusive: bool
) -> dict[str, Any] | None:
    """Fit ``method`` on matured history and score one fold. ``None`` if unfittable."""
    hist_probs = [p for f in history for p in f.probabilities]
    hist_labels = [y for f in history for y in f.labels_for(exclusive=exclusive)]
    if len(hist_probs) < MIN_SAMPLE_SIZE or len(set(hist_labels)) < 2:
        return None

    calibrator = _new_calibrator(method)
    if method != "identity":
        sample = CalibrationSample(
            probabilities=hist_probs,
            outcomes=hist_labels,
            sample_start=min(f.cutoff_at for f in history),
            sample_end=max(f.cutoff_at for f in history),
        )
        try:
            calibrator.fit(sample)
        except ValueError:
            return None

    probs = calibrator.apply_all(fold.probabilities)
    labels = fold.labels_for(exclusive=exclusive)

    clim_rate = climatology(hist_labels)
    if clim_rate is None:
        return None
    clim_ref = [clim_rate] * len(labels)
    last = max(history, key=lambda f: f.index)
    pers_ref = persistence(
        fold.stream_keys, last.positive_streams(exclusive=exclusive), fallback=clim_rate
    )

    row: dict[str, Any] = {
        "cutoff_at": fold.cutoff_at.isoformat(),
        "method": method,
        "n": len(labels),
        "positives": int(sum(labels)),
        "history_folds": len(history),
        "history_n": len(hist_probs),
        "climatology_rate": round(clim_rate, 9),
        "brier": metrics.brier_score(probs, labels),
        "log_loss": metrics.log_loss(probs, labels),
        "roc_auc": metrics.roc_auc(probs, labels),
        "ece": metrics.expected_calibration_error(probs, labels, 10),
        "skill_vs_climatology": skill_score(probs, labels, clim_ref),
        "skill_vs_persistence": skill_score(probs, labels, pers_ref),
    }
    for b in BUDGETS:
        top = unique_outcome_topk(
            probs,
            [bool(v) for v in labels],
            fold.outcome_ids,
            budget=b,
            outcomes_available=fold.outcomes_in_window,
        )
        row[f"top{b}"] = top.to_dict()
    return row


def run_block(
    folds: list[FoldData],
    targets: list[FoldData],
    horizon: int,
    delay: float,
    limit_index: int | None,
    *,
    exclusive: bool,
) -> dict[str, list[dict[str, Any]]]:
    """Score every method on every target fold that has matured history."""
    out: dict[str, list[dict[str, Any]]] = {m: [] for m in METHODS}
    for target in targets:
        history = eligible_history(folds, target, horizon, delay, limit_index)
        if len(history) < MIN_HISTORY_FOLDS:
            continue
        for method in METHODS:
            row = score_fold(target, history, method, exclusive=exclusive)
            if row is not None:
                out[method].append(row)
    return out


def summarise(rows: list[dict[str, Any]], block: int, key: str) -> dict[str, Any] | None:
    values = [r[key] for r in rows if r.get(key) is not None]
    if not values:
        return None
    return moving_block_bootstrap(values, block_length=block).to_dict()


def main() -> int:
    folds, horizon, delay, step = collect_folds()
    block = overlap_depth(horizon, step)
    n = len(folds)
    n_test = max(3, round(n * TEST_FRACTION))
    dev_end = n - n_test
    dev, test = folds[:dev_end], folds[dev_end:]

    print(f"scoreable folds: {n}  development: {len(dev)}  untouched test: {len(test)}")
    print(
        f"horizon {horizon}d + reporting delay {delay:.2f}d -> maturity lag "
        f"{horizon + delay:.2f}d = {(horizon + delay) / step:.1f} folds at a {step}d step"
    )
    print(f"bootstrap block length: {block} folds (overlap depth)")

    report: dict[str, Any] = {
        "kind": "chrono_calibration",
        "experiment": EXPERIMENT.name,
        "control_untouched": "e2e_v1",
        "protocol": {
            "horizon_days": horizon,
            "reporting_delay_days": round(delay, 6),
            "step_days": step,
            "maturity_lag_days": round(horizon + delay, 6),
            "bootstrap_block_folds": block,
            "scoreable_folds": n,
            "development_folds": len(dev),
            "test_folds": len(test),
            "test_window": [test[0].cutoff_at.isoformat(), test[-1].cutoff_at.isoformat()],
            "min_history_folds": MIN_HISTORY_FOLDS,
            "min_calibration_sample": MIN_SAMPLE_SIZE,
        },
    }

    # -- validation: rank methods inside the development block only ------
    val = run_block(folds, dev, horizon, delay, limit_index=dev_end, exclusive=False)
    report["validation"] = {}
    ranking: list[tuple[float, str]] = []
    for method in METHODS:
        rows = val[method]
        if not rows:
            report["validation"][method] = {"folds": 0, "note": "no fold had matured history"}
            continue
        mean_brier = sum(r["brier"] for r in rows) / len(rows)
        ranking.append((mean_brier, method))
        entry: dict[str, Any] = {
            "folds": len(rows),
            "mean_brier": round(mean_brier, 9),
            "brier_ci": summarise(rows, block, "brier"),
            "skill_vs_climatology_ci": summarise(rows, block, "skill_vs_climatology"),
            "skill_vs_persistence_ci": summarise(rows, block, "skill_vs_persistence"),
        }
        if method != "identity" and val["identity"]:
            paired = {r["cutoff_at"]: r for r in val["identity"]}
            common = [r for r in rows if r["cutoff_at"] in paired]
            if common:
                entry["brier_delta_vs_identity_ci"] = paired_block_bootstrap(
                    [paired[r["cutoff_at"]]["brier"] for r in common],
                    [r["brier"] for r in common],
                    block_length=block,
                ).to_dict()
        report["validation"][method] = entry

    if not ranking:
        print("no method could be fitted; the walk is too short for the maturity lag")
        report["frozen_choice"] = None
        _write(report)
        return 1

    ranking.sort()
    frozen = ranking[0][1]
    report["frozen_choice"] = frozen
    report["frozen_before_test"] = True
    print(f"\nfrozen choice (selected on development block only): {frozen}")

    # -- test: the frozen choice on folds that took no part in selection --
    for label, exclusive in (("test", False), ("test_one_to_one", True)):
        res = run_block(folds, test, horizon, delay, limit_index=None, exclusive=exclusive)
        block_report: dict[str, Any] = {}
        for method in METHODS:
            rows = res[method]
            if not rows:
                block_report[method] = {"folds": 0}
                continue
            block_report[method] = {
                "folds": len(rows),
                "is_frozen_choice": method == frozen,
                "mean_brier": round(sum(r["brier"] for r in rows) / len(rows), 9),
                "brier_ci": summarise(rows, block, "brier"),
                "skill_vs_climatology_ci": summarise(rows, block, "skill_vs_climatology"),
                "skill_vs_persistence_ci": summarise(rows, block, "skill_vs_persistence"),
                "roc_auc_ci": summarise(rows, block, "roc_auc"),
                "unique_topk": {
                    f"top{b}": {
                        "unique_recall": summarise(
                            [{"v": r[f"top{b}"]["unique_recall"]} for r in rows], block, "v"
                        ),
                        "duplication_ratio": summarise(
                            [{"v": r[f"top{b}"]["duplication_ratio"]} for r in rows], block, "v"
                        ),
                    }
                    for b in BUDGETS
                },
                "per_fold": rows,
            }
        report[label] = block_report

    _write(report)
    return 0


def _write(report: dict[str, Any]) -> None:
    run_id = stable_id("chrono", json.dumps(report, sort_keys=True, default=str))
    out = Path("runs") / run_id
    out.mkdir(parents=True, exist_ok=True)
    report["run_id"] = run_id
    (out / "report.json").write_text(json.dumps(report, indent=2, default=str), encoding="utf-8")
    print(f"\nwritten: {out / 'report.json'}")


if __name__ == "__main__":
    raise SystemExit(main())
