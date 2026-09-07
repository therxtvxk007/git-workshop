"""Chronological roles, purged and written down.

An origin plays exactly one role. That is the whole protocol, and the reason it
needs a manifest rather than a convention is that three of the failures it
prevents are invisible in the code that would cause them (S33.1):

* **Selection on the test set.** If "which baseline was better" is decided on
  the same origins the result is reported over, the reported number includes
  the choice. Roles are assigned by date band, before any score exists.
* **Purge.** A training label whose outcome window has not closed by the fit
  cutoff has not happened yet. Purging by a fixed number of rows is not the
  same rule and does not follow the window when the window changes.
* **Availability, not just maturity.** A label may be mature and still not have
  been published when the fit ran. That is a separate condition and it is the
  one that lets a fit read a correction from its own future.

Roles attach to origins rather than to rows, so every district and family at an
origin stays together. Splitting a panel by row would put the same month on
both sides of the boundary.
"""

from __future__ import annotations

from collections.abc import Sequence
from datetime import datetime, timedelta

from pydantic import Field, model_validator

from pramaanx.core.contexts import OriginRole
from pramaanx.core.errors import ContractViolationError
from pramaanx.hashing import hash_object, utc_isoformat
from pramaanx.schemas.base import UtcDatetime, VersionedModel

#: Role bands, in the order they occur in time. The order is the protocol.
ROLE_ORDER: tuple[OriginRole, ...] = (
    OriginRole.TRAIN,
    OriginRole.SELECT,
    OriginRole.CALIBRATE,
    OriginRole.RETRO_TEST,
    OriginRole.PROSPECTIVE,
)


class SplitManifest(VersionedModel):
    """The frozen assignment of origins to roles, with its purge rule."""

    origins: tuple[UtcDatetime, ...]
    #: ISO origin -> role. A mapping rather than a parallel list, so a reordered
    #: origin list cannot silently reassign every role.
    roles: dict[str, str] = Field(default_factory=dict)
    window_days: int = Field(gt=0)
    maturation_days: int = Field(ge=0)
    #: Whether a later fit may train on origins from a *later* role band once
    #: their labels have matured. Off by default: a walk-forward promotion is a
    #: protocol decision, and the plan requires the manifest to state it rather
    #: than let it be inferred from the fact that a label now exists.
    walk_forward: bool = False
    boundary_versions: tuple[str, ...] = ()
    calendar: dict[str, str] = Field(default_factory=dict)

    @model_validator(mode="after")
    def _every_origin_has_one_role(self) -> SplitManifest:
        keys = {utc_isoformat(origin) for origin in self.origins}
        missing = sorted(keys - set(self.roles))
        extra = sorted(set(self.roles) - keys)
        if missing or extra:
            raise ContractViolationError(
                "role assignment does not cover the origins exactly",
                missing=missing[:5],
                extra=extra[:5],
            )
        if list(self.origins) != sorted(self.origins):
            raise ContractViolationError("origins must be chronological")
        return self

    def role_of(self, origin: datetime) -> OriginRole:
        key = utc_isoformat(origin)
        if key not in self.roles:
            raise ContractViolationError("origin is not in this split", origin=key)
        return OriginRole(self.roles[key])

    def origins_with(self, role: OriginRole) -> tuple[datetime, ...]:
        return tuple(
            origin for origin in self.origins if self.roles[utc_isoformat(origin)] == str(role)
        )

    def label_settled_at(self, origin: datetime) -> datetime:
        """When this origin's outcome may be used: window end plus maturation."""
        return origin + timedelta(days=self.window_days + self.maturation_days)

    def training_origins_for(self, issue_time: datetime) -> tuple[datetime, ...]:
        """Origins a fit at ``issue_time`` may learn from.

        Two conditions. The origin is earlier, and its label has settled by the
        fit cutoff. Without ``walk_forward`` the origin must also be in the
        train band, so a selection origin cannot quietly become training data
        once enough time has passed.
        """
        eligible: list[datetime] = []
        for origin in self.origins:
            if origin >= issue_time:
                continue
            if self.label_settled_at(origin) > issue_time:
                continue
            if not self.walk_forward and self.role_of(origin) is not OriginRole.TRAIN:
                continue
            eligible.append(origin)
        return tuple(eligible)

    def purged_for(self, issue_time: datetime) -> tuple[datetime, ...]:
        """Earlier origins the purge rule excludes, and why they are excluded.

        Reported rather than silently dropped: the size of the purge is a fact
        about the protocol that belongs in the run manifest.
        """
        return tuple(
            origin
            for origin in self.origins
            if origin < issue_time and self.label_settled_at(origin) > issue_time
        )

    def identity(self) -> str:
        return hash_object(
            {
                "origins": [utc_isoformat(origin) for origin in self.origins],
                "roles": dict(sorted(self.roles.items())),
                "window_days": self.window_days,
                "maturation_days": self.maturation_days,
                "walk_forward": self.walk_forward,
                "boundary_versions": list(self.boundary_versions),
                "calendar": dict(sorted(self.calendar.items())),
            }
        )


def chronological_split(
    origins: Sequence[datetime],
    *,
    select_from: datetime,
    calibrate_from: datetime,
    retro_test_from: datetime,
    prospective_from: datetime,
    window_days: int,
    maturation_days: int,
    walk_forward: bool = False,
    boundary_versions: Sequence[str] = (),
    calendar: dict[str, str] | None = None,
) -> SplitManifest:
    """Assign roles by preregistered date bands.

    Dates rather than fractions. A fraction moves every boundary when an origin
    is added, which makes "the same split" mean two different things across two
    runs of the same protocol.
    """
    boundaries = (select_from, calibrate_from, retro_test_from, prospective_from)
    if list(boundaries) != sorted(boundaries):
        raise ContractViolationError(
            "role boundaries must be in chronological order",
            boundaries=[utc_isoformat(item) for item in boundaries],
        )
    if not origins:
        raise ContractViolationError("a split needs at least one origin")

    roles: dict[str, str] = {}
    for origin in origins:
        if origin >= prospective_from:
            role = OriginRole.PROSPECTIVE
        elif origin >= retro_test_from:
            role = OriginRole.RETRO_TEST
        elif origin >= calibrate_from:
            role = OriginRole.CALIBRATE
        elif origin >= select_from:
            role = OriginRole.SELECT
        else:
            role = OriginRole.TRAIN
        roles[utc_isoformat(origin)] = str(role)

    return SplitManifest(
        origins=tuple(sorted(origins)),
        roles=roles,
        window_days=window_days,
        maturation_days=maturation_days,
        walk_forward=walk_forward,
        boundary_versions=tuple(boundary_versions),
        calendar=dict(calendar or {}),
    )


def check_purge(manifest: SplitManifest, *, issue_time: datetime) -> None:
    """No training label's window plus maturation extends past the fit cutoff.

    The one invariant this whole module exists to guarantee, checked directly
    rather than inferred from the fact that the selection ran.
    """
    offenders = [
        utc_isoformat(origin)
        for origin in manifest.training_origins_for(issue_time)
        if manifest.label_settled_at(origin) > issue_time
    ]
    if offenders:
        raise ContractViolationError(
            "a training origin's outcome had not settled by the fit cutoff",
            issue_time=utc_isoformat(issue_time),
            origins=offenders[:5],
        )
