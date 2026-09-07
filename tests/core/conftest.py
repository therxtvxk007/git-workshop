"""Fixtures for the as-of store and the contexts that read it."""

from __future__ import annotations

from collections.abc import Callable
from datetime import timedelta
from pathlib import Path

import pytest
from _builders import ORIGIN

from pramaanx.clock import FixedClock
from pramaanx.core.asof import RevisionStore
from pramaanx.core.contexts import (
    AvailabilityBasis,
    ForecastContext,
    InformationProfile,
    OriginRole,
)
from pramaanx.core.revisions import Revision, RevisionOperation


@pytest.fixture
def store(tmp_path: Path) -> RevisionStore:
    return RevisionStore(tmp_path / "store", clock=FixedClock(ORIGIN))


@pytest.fixture
def make_revision() -> Callable[..., Revision]:
    def _make(
        entity_id: str,
        order: int,
        *,
        days: float = 0.0,
        operation: RevisionOperation = RevisionOperation.UPSERT,
        source_id: str = "acled",
        table: str = "events",
        retrieved_days: float | None = None,
        basis: AvailabilityBasis = AvailabilityBasis.UNRESOLVED,
        evidence: str | None = None,
        payload: dict[str, object] | None = None,
    ) -> Revision:
        available = ORIGIN + timedelta(days=days)
        retrieved = ORIGIN + timedelta(days=retrieved_days if retrieved_days is not None else days)
        return Revision(
            table=table,
            source_id=source_id,
            entity_id=entity_id,
            source_revision_order=order,
            operation=operation,
            available_time=available,
            retrieved_time=retrieved,
            ingested_at=max(available, retrieved),
            availability_basis=basis,
            availability_evidence_ref=evidence,
            payload=payload if payload is not None else {"revision": order},
        )

    return _make


@pytest.fixture
def make_context() -> Callable[..., ForecastContext]:
    def _make(
        manifest: str,
        *,
        days: float = 0.0,
        profile: InformationProfile = InformationProfile.PROSPECTIVE_OBSERVED,
        role: OriginRole = OriginRole.RETRO_TEST,
        policy_hash: str = "policy-v1",
    ) -> ForecastContext:
        instant = ORIGIN + timedelta(days=days)
        return ForecastContext(
            issue_time=instant,
            cutoff_at=instant,
            input_manifest=manifest,
            profile=profile,
            role=role,
            policy_hash=policy_hash,
            boundary_version="lgd-2011",
        )

    return _make
