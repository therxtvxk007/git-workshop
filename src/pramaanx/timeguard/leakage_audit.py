"""Automated leakage screening.

What this module can do: catch mechanical leaks. Bytes that changed under a
recorded hash, documents back-dated relative to an identical copy elsewhere,
pre-cutoff text that reads as if it were written after the outcome.

What it cannot do: certify that a run is leak-free. Subtle leakage -- a base
model that memorised the outcome, a summary that absorbed a future document, a
label that travelled into a prompt -- does not announce itself in a regex. The
findings below are review queues for a human, and are reported as suspicions
with a reason, never as a pass mark.
"""

from __future__ import annotations

import re
from collections.abc import Iterable, Sequence
from dataclasses import dataclass, field
from datetime import datetime
from enum import StrEnum

from pramaanx.config import TimeguardConfig
from pramaanx.hashing import hash_bytes, utc_isoformat
from pramaanx.ingest.ledger import EvidenceLedger
from pramaanx.logging import get_logger
from pramaanx.schemas.observation import Observation

log = get_logger(__name__)


class FindingKind(StrEnum):
    MUTATED_PAYLOAD = "mutated_payload"
    """Stored bytes no longer hash to the value recorded at ingestion. Bronze is
    supposed to be append-only; this is the loudest possible alarm."""

    MISSING_PAYLOAD = "missing_payload"
    """The ledger references a payload that is not on disk."""

    RETROSPECTIVE_LANGUAGE = "retrospective_language"
    """A document that dates its event at or after its own observation time and
    yet describes it in the past tense. Ordinary reporting of an older event is
    not flagged; this pattern is what a silently-updated body looks like."""

    BACKDATED_DUPLICATE = "backdated_duplicate"
    """The same bytes appear under two very different observation times."""

    IMPLAUSIBLE_LEAD = "implausible_lead"
    """A claimed event time far in the future relative to first observation,
    which tends to indicate a parsing error rather than genuine foresight."""


class Severity(StrEnum):
    CRITICAL = "critical"
    WARNING = "warning"
    INFO = "info"


@dataclass(frozen=True)
class LeakageFinding:
    kind: FindingKind
    severity: Severity
    observation_id: str
    detail: str

    def to_dict(self) -> dict[str, str]:
        return {
            "kind": str(self.kind),
            "severity": str(self.severity),
            "observation_id": self.observation_id,
            "detail": self.detail,
        }


@dataclass
class LeakageReport:
    cutoff_at: datetime | None
    observations_checked: int = 0
    findings: list[LeakageFinding] = field(default_factory=list)

    @property
    def critical(self) -> list[LeakageFinding]:
        return [item for item in self.findings if item.severity is Severity.CRITICAL]

    @property
    def clean(self) -> bool:
        """No *mechanical* leak was detected. Not a certificate of safety."""
        return not self.critical

    def counts_by_kind(self) -> dict[str, int]:
        counts: dict[str, int] = {}
        for finding in self.findings:
            counts[str(finding.kind)] = counts.get(str(finding.kind), 0) + 1
        return dict(sorted(counts.items()))

    def to_dict(self) -> dict[str, object]:
        return {
            "kind": "leakage_audit",
            "cutoff_at": utc_isoformat(self.cutoff_at) if self.cutoff_at else None,
            "observations_checked": self.observations_checked,
            "findings_by_kind": self.counts_by_kind(),
            "critical_count": len(self.critical),
            "mechanically_clean": self.clean,
            "caveat": (
                "Automated screening only. Memorisation, prompt contamination and "
                "human-in-the-loop leakage require the counterfactual and prospective "
                "tracks, not this report."
            ),
            "findings": [item.to_dict() for item in self.findings[:200]],
        }


class LeakageAuditor:
    """Screens a set of observations for mechanical leakage."""

    def __init__(self, ledger: EvidenceLedger, config: TimeguardConfig | None = None) -> None:
        self.ledger = ledger
        self.config = config or ledger.settings.timeguard
        markers = sorted(self.config.retrospective_markers, key=len, reverse=True)
        self._marker_re = (
            re.compile("|".join(re.escape(marker) for marker in markers), re.IGNORECASE)
            if markers
            else None
        )

    def audit(
        self,
        observations: Sequence[Observation],
        *,
        cutoff_at: datetime | None = None,
    ) -> LeakageReport:
        report = LeakageReport(cutoff_at=cutoff_at, observations_checked=len(observations))
        report.findings.extend(self._check_payloads(observations))
        report.findings.extend(self._check_duplicates(observations))
        report.findings.extend(self._check_claimed_times(observations))
        report.findings.sort(key=lambda item: (item.severity, item.kind, item.observation_id))
        if report.critical:
            log.error("leakage.critical", count=len(report.critical))
        return report

    # -- individual checks ------------------------------------------------
    def _check_payloads(self, observations: Iterable[Observation]) -> list[LeakageFinding]:
        findings: list[LeakageFinding] = []
        for observation in observations:
            if not self.ledger.payloads.exists(observation.payload_ref):
                findings.append(
                    LeakageFinding(
                        FindingKind.MISSING_PAYLOAD,
                        Severity.CRITICAL,
                        observation.observation_id,
                        f"payload_ref {observation.payload_ref} is not present on disk",
                    )
                )
                continue
            raw = self.ledger.payloads.get(observation.payload_ref)
            actual = hash_bytes(raw)
            if actual != observation.raw_content_hash:
                findings.append(
                    LeakageFinding(
                        FindingKind.MUTATED_PAYLOAD,
                        Severity.CRITICAL,
                        observation.observation_id,
                        f"stored bytes hash to {actual}, ledger recorded "
                        f"{observation.raw_content_hash}",
                    )
                )
                continue
            findings.extend(self._check_retrospective_text(observation, raw))
        return findings

    def _check_retrospective_text(
        self, observation: Observation, raw: bytes
    ) -> list[LeakageFinding]:
        """Flag past-tense text about an event the document dates as not-yet-past.

        Screening every document that contains "in the aftermath" would flag
        most of a news corpus and the queue would be abandoned within a day.
        The suspicious combination is narrower: the document places its event at
        or after the moment it was itself observed, and still writes about it as
        something that has happened.

        The limitation is worth stating: a document whose event time could not
        be parsed cannot be screened this way at all. That is a job for the time
        parser, not for a regex over the body.
        """
        if self._marker_re is None:
            return []
        claimed = observation.claimed_event_time
        if claimed is None or claimed < observation.first_observed_at:
            return []
        try:
            text = raw.decode("utf-8")
        except UnicodeDecodeError:
            return []
        match = self._marker_re.search(text)
        if match is None:
            return []
        return [
            LeakageFinding(
                FindingKind.RETROSPECTIVE_LANGUAGE,
                Severity.WARNING,
                observation.observation_id,
                f"retrospective phrase {match.group(0)!r} at offset {match.start()} in a "
                f"document dating its event at {claimed.isoformat()}, at or after its own "
                f"observation time",
            )
        ]

    @staticmethod
    def _check_duplicates(observations: Sequence[Observation]) -> list[LeakageFinding]:
        """Identical bytes with wildly different observation times.

        One copy is probably back-dated, and the earlier timestamp is the one
        that would smuggle the content past a cutoff.
        """
        by_hash: dict[str, list[Observation]] = {}
        for observation in observations:
            by_hash.setdefault(observation.raw_content_hash, []).append(observation)

        findings: list[LeakageFinding] = []
        for content_hash, group in sorted(by_hash.items()):
            if len(group) < 2:
                continue
            ordered = sorted(group, key=lambda item: item.first_observed_at)
            spread_days = (
                ordered[-1].first_observed_at - ordered[0].first_observed_at
            ).total_seconds() / 86400.0
            if spread_days < 1.0:
                continue
            findings.append(
                LeakageFinding(
                    FindingKind.BACKDATED_DUPLICATE,
                    Severity.WARNING,
                    ordered[0].observation_id,
                    f"content {content_hash[:19]}... appears {len(group)} times spanning "
                    f"{spread_days:.1f} days; earliest is "
                    f"{utc_isoformat(ordered[0].first_observed_at)}",
                )
            )
        return findings

    @staticmethod
    def _check_claimed_times(observations: Iterable[Observation]) -> list[LeakageFinding]:
        findings: list[LeakageFinding] = []
        for observation in observations:
            claimed = observation.claimed_event_time
            if claimed is None:
                continue
            lead_days = (claimed - observation.first_observed_at).total_seconds() / 86400.0
            if lead_days > 365.0:
                findings.append(
                    LeakageFinding(
                        FindingKind.IMPLAUSIBLE_LEAD,
                        Severity.INFO,
                        observation.observation_id,
                        f"claimed_event_time is {lead_days:.0f} days after first observation; "
                        "check the time parser before trusting this record",
                    )
                )
        return findings
