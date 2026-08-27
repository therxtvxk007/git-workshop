"""One vocabulary for "has this source's contract ever been checked against reality?".

Every Phase 1 connector already documents the shape it expects, in a module-level
``API_CONTRACT``. Three connectors, three vocabularies for the same three facts::

    reliefweb    official_docs_verified / official_docs_verified_on / live_api_verified
    acled        verified_against_official_docs / verified_on / genuinely_live_api_verified
    data_gov_in  verified_against_current_official_docs / verified_at /
                 genuinely_live_api_verified / live_verified_at

and ``gdelt`` declares nothing at all. So the question a reviewer actually asks --
*which of my evidence sources has ever been exercised against the real service?* --
took reading three modules in three dialects, and its answer reached no manifest.
A forecast could cite evidence from a source whose contract had never returned a
byte, and nothing downstream would say so.

This module normalises that one question and nothing else. The connector dicts
stay authoritative for connector-specific shape -- pagination style, envelope
keys, date fields -- because that detail is not comparable across sources and
flattening it would destroy it. What *is* comparable is the verification record,
and that is what :func:`contract_manifest` writes into every ingestion manifest
and every snapshot.

The distinction the state machine exists to protect is between *reading the
documentation* and *getting an answer back*. A connector written from current
official docs, with fixtures that pass, is a well-researched hypothesis about a
service nobody has called. :class:`VerificationState` keeps those apart and
refuses to let the second be claimed without evidence naming where it happened.
"""

from __future__ import annotations

from collections.abc import Iterable
from datetime import date
from enum import StrEnum
from typing import Any

from pydantic import model_validator

from pramaanx.schemas.base import PramaanModel, VersionedModel


class VerificationState(StrEnum):
    """How much is actually known about a source's contract.

    Ordered by how much they license you to claim. Only ``LIVE_VERIFIED``
    supports "this connector works"; the rest support "this connector is
    expected to work, for a stated reason".
    """

    #: No external service exists to verify -- a generated world, not a feed.
    SYNTHETIC = "synthetic"
    #: Neither documentation nor service has been checked. The default for a
    #: connector nobody has reviewed, and never a state to leave a source in.
    UNVERIFIED = "unverified"
    #: The contract was read from current official documentation on a recorded
    #: date, and fixtures exercise it. No response from the real service has
    #: ever been parsed.
    DOCS_ONLY = "docs_only"
    #: A response from the real service was fetched and satisfied the contract,
    #: on a recorded date, with evidence naming where that happened.
    LIVE_VERIFIED = "live_verified"


class PinnedResource(PramaanModel):
    """A specific upstream dataset this project depends on continuing to exist.

    data.gov.in publishes per-resource endpoints whose identifiers are stable
    only by convention: a department can withdraw a resource or reshape its
    columns without notice, and the API answers a withdrawn resource much the
    way it answers a typo. Pinning the identifier turns the first of those into
    a test failure rather than a silently empty ingestion.

    ``field_names`` pins the second, and is empty until a live response has
    actually been read. That distinction is the whole point: a schema pin
    copied from a fixture pins the fixture, and would report drift against a
    service it has never seen. Empty means *not captured yet*, which
    :meth:`drift_against` refuses to guess about.
    """

    resource_id: str
    title: str
    resource_page_url: str | None = None
    pinned_on: date
    #: Record field names observed in a real response. Empty until one is read.
    field_names: tuple[str, ...] = ()
    schema_captured_on: date | None = None

    @model_validator(mode="after")
    def _schema_pin_is_observed_or_absent(self) -> PinnedResource:
        if bool(self.field_names) != (self.schema_captured_on is not None):
            raise ValueError(
                f"{self.resource_id}: field_names and schema_captured_on must be set "
                "together. A field list with no capture date cannot be told apart from "
                "one copied out of a fixture, which is exactly the mistake this pin "
                "exists to prevent."
            )
        return self

    @property
    def schema_pinned(self) -> bool:
        return bool(self.field_names)

    def drift_against(self, observed: set[str]) -> tuple[set[str], set[str]]:
        """Fields that vanished and fields that appeared, against the pin.

        Raises when no schema has been captured: reporting "everything is new"
        against an empty pin would be drift noise, not a finding.
        """
        if not self.schema_pinned:
            raise ValueError(
                f"{self.resource_id} has no captured schema to compare against. "
                "Run the live probe and record what it returned before asking "
                "whether the resource has drifted."
            )
        pinned = set(self.field_names)
        return pinned - observed, observed - pinned


class SourceContract(VersionedModel):
    """What is believed about one source, and on what evidence.

    ``contract_version`` is bumped by hand when the believed contract changes.
    It is not derived from the content, because the point of the pinned hashes
    in ``tests/contracts/test_source_contracts.py`` is to make an *unannounced*
    change fail: a version that moved on its own could never catch one.
    """

    source_id: str
    contract_version: str
    state: VerificationState
    #: The test that would move this source to ``LIVE_VERIFIED``. Recorded even
    #: when unverified, so "how would we find out?" always has an answer.
    verification_route: str
    official_docs: tuple[str, ...] = ()
    docs_verified_on: date | None = None
    live_verified_on: date | None = None
    #: What the live check actually covered. A probe of one resource does not
    #: verify a portal, and the scope is where that gets said out loud.
    live_verification_scope: str | None = None
    #: Where the passing live check can be found: a CI run URL, a workflow run
    #: id, a recorded session. A claim with no address is not evidence.
    live_evidence: str | None = None
    #: Why this source is not live-verified. Required whenever it is not, so the
    #: gap is always attributable to something -- a missing credential, a
    #: pending approval -- rather than to nobody having got round to it.
    blocker: str | None = None
    pinned_resources: tuple[PinnedResource, ...] = ()

    @model_validator(mode="after")
    def _evidence_matches_claim(self) -> SourceContract:
        if self.state is VerificationState.LIVE_VERIFIED:
            missing = [
                name
                for name, value in (
                    ("live_verified_on", self.live_verified_on),
                    ("live_verification_scope", self.live_verification_scope),
                    ("live_evidence", self.live_evidence),
                )
                if value is None
            ]
            if missing:
                raise ValueError(
                    f"{self.source_id} claims live verification without {', '.join(missing)}. "
                    "A live claim carries its date, its scope and where it can be checked, "
                    "or it is not a live claim."
                )
            if self.blocker is not None:
                raise ValueError(
                    f"{self.source_id} is live-verified and also declares a blocker "
                    f"({self.blocker!r}); one of the two is stale"
                )
        else:
            if self.live_verified_on is not None or self.live_evidence is not None:
                raise ValueError(
                    f"{self.source_id} is {self.state.value} but carries live-verification "
                    "detail. Verification detail belongs only to a verified source; leaving "
                    "it behind after a downgrade is how a stale claim survives."
                )
            if self.state is not VerificationState.SYNTHETIC and self.blocker is None:
                raise ValueError(
                    f"{self.source_id} is {self.state.value} and names no blocker. "
                    "An unverified source must say what is missing, or nobody can act on it."
                )
        if self.state is VerificationState.DOCS_ONLY and self.docs_verified_on is None:
            raise ValueError(f"{self.source_id} claims its docs were verified but records no date")
        if self.state is VerificationState.UNVERIFIED and self.docs_verified_on is not None:
            raise ValueError(
                f"{self.source_id} is unverified but records a docs-verification date; "
                "it is docs_only, not unverified"
            )
        return self

    @property
    def contract_hash(self) -> str:
        """Content hash of the whole record, used as the drift alarm's fingerprint."""
        return self.content_hash()

    @property
    def live_verified(self) -> bool:
        return self.state is VerificationState.LIVE_VERIFIED

    def summary(self) -> str:
        """``source@version/state`` -- the short form that goes into manifests."""
        return f"{self.source_id}@{self.contract_version}/{self.state.value}"

    def manifest_entry(self) -> dict[str, Any]:
        """The provenance block one source contributes to an ingestion manifest."""
        entry: dict[str, Any] = {
            "contract_version": self.contract_version,
            "contract_hash": self.contract_hash,
            "state": self.state.value,
        }
        if self.live_verified_on is not None:
            entry["live_verified_on"] = self.live_verified_on.isoformat()
            entry["live_evidence"] = self.live_evidence
        if self.blocker is not None:
            entry["blocker"] = self.blocker
        return entry


SOURCE_CONTRACTS: dict[str, SourceContract] = {
    "synthetic": SourceContract(
        source_id="synthetic",
        contract_version="1.0.0",
        state=VerificationState.SYNTHETIC,
        verification_route="tests/unit/test_connector_base.py",
    ),
    "gdelt": SourceContract(
        source_id="gdelt",
        contract_version="1.0.0",
        state=VerificationState.LIVE_VERIFIED,
        verification_route="tests/network/test_gdelt_live.py",
        official_docs=("https://www.gdeltproject.org/data.html#rawdatafiles",),
        docs_verified_on=date(2026, 8, 25),
        live_verified_on=date(2026, 8, 27),
        live_verification_scope=(
            "one 15-minute export file fetched from the public export archive, "
            "unzipped and parsed into observations; the archive's schema, not "
            "every GDELT product"
        ),
        live_evidence=("https://github.com/therxtvxk007/git-workshop/actions/runs/33086345335"),
    ),
    "data_gov_in": SourceContract(
        source_id="data_gov_in",
        contract_version="1.0.0",
        state=VerificationState.LIVE_VERIFIED,
        verification_route="tests/network/test_data_gov_in_live.py",
        official_docs=(
            "https://www.data.gov.in/apis",
            "https://www.data.gov.in/help",
            "https://www.data.gov.in/terms-of-use",
            "https://www.data.gov.in/government-open-data-license-india",
        ),
        docs_verified_on=date(2026, 8, 26),
        live_verified_on=date(2026, 8, 27),
        live_verification_scope=(
            "the selected resource only: raw first-page envelope plus a forced "
            "multi-page terminal traversal. Not every data.gov.in dataset, and "
            "not the portal's other APIs"
        ),
        live_evidence=(
            "docs/M1C_ACCEPTANCE.md, verification table: CPython 3.14.7, "
            "pytest 9.1.1, 2 passed in 2.54s"
        ),
        pinned_resources=(
            PinnedResource(
                resource_id="869c674d-59a4-4de3-8b09-f2b709983f51",
                title=(
                    "Attacker-wise Incidents of Violence by Extremists/Insurgents/"
                    "Terrorists during 2023"
                ),
                resource_page_url=(
                    "https://www.data.gov.in/resource/attacker-wise-incidents-violence-"
                    "extremists-insurgents-terrorists-during-2023"
                ),
                pinned_on=date(2026, 8, 27),
                # No schema pin. The 2026-08-27 live run recorded that the
                # envelope contract held and the traversal terminated; it did
                # not record the record field names, and the repository's only
                # data.gov.in records are openly synthetic fixtures. Capturing
                # this needs one live probe, not a guess.
            ),
        ),
    ),
    "reliefweb": SourceContract(
        source_id="reliefweb",
        contract_version="2.0.0",
        state=VerificationState.DOCS_ONLY,
        verification_route="tests/network/test_reliefweb_live.py",
        official_docs=(
            "https://apidoc.reliefweb.int/",
            "https://reliefweb.int/terms-conditions",
        ),
        docs_verified_on=date(2026, 8, 26),
        blocker=(
            "no approved ReliefWeb appname. Appnames have been approval-gated since "
            "2025-11-01, and this environment's egress policy additionally refuses "
            "CONNECT to api.reliefweb.int, so neither the credential nor the route "
            "currently exists"
        ),
    ),
    "acled": SourceContract(
        source_id="acled",
        contract_version="1.0.0",
        state=VerificationState.DOCS_ONLY,
        verification_route="tests/network/test_acled_live.py",
        official_docs=(
            "https://acleddata.com/api-documentation/",
            "https://acleddata.com/eula",
        ),
        docs_verified_on=date(2026, 8, 26),
        blocker=(
            "no myACLED account or credential. Access requires accepting the EULA "
            "under a declared institutional use, which is a decision a person makes, "
            "not a step code can take"
        ),
    ),
}
"""The verification record for every registered connector.

Keyed by ``source_id``. :func:`pramaanx.ingest.contracts.contract_for` is the
only supported way to read it -- a missing key is a bug worth an exception, not
a ``None`` that quietly writes an empty manifest entry.
"""


class UnknownSourceError(KeyError):
    """Raised when a source has no declared contract."""


def contract_for(source_id: str) -> SourceContract:
    """The contract for one source, or an error naming what is registered."""
    try:
        return SOURCE_CONTRACTS[source_id]
    except KeyError:
        known = ", ".join(sorted(SOURCE_CONTRACTS))
        raise UnknownSourceError(
            f"no source contract declared for {source_id!r}. Registered: {known}. "
            "A connector without a contract cannot say whether anything it returns "
            "has ever been checked, so it is not allowed to ingest."
        ) from None


def contract_manifest(source_ids: Iterable[str]) -> dict[str, dict[str, Any]]:
    """Manifest provenance for a set of sources, sorted for stable hashing."""
    return {
        source_id: contract_for(source_id).manifest_entry() for source_id in sorted(set(source_ids))
    }


def contract_summaries(source_ids: Iterable[str]) -> dict[str, str]:
    """``{source_id: "source@version/state"}`` -- the compact snapshot form."""
    return {source_id: contract_for(source_id).summary() for source_id in sorted(set(source_ids))}


def unverified(source_ids: Iterable[str] | None = None) -> list[SourceContract]:
    """Contracts that are not live-verified, worst first.

    What a status command prints and what a release gate reads. Ordered so the
    sources nobody has looked at surface above the ones merely waiting on a
    credential.
    """
    order = {
        VerificationState.UNVERIFIED: 0,
        VerificationState.DOCS_ONLY: 1,
        VerificationState.SYNTHETIC: 2,
    }
    ids = set(SOURCE_CONTRACTS) if source_ids is None else set(source_ids)
    contracts = [contract_for(source_id) for source_id in sorted(ids)]
    pending = [contract for contract in contracts if not contract.live_verified]
    return sorted(pending, key=lambda contract: (order[contract.state], contract.source_id))
