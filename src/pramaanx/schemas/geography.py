"""Versioned geographic references used by district forecasts."""

from __future__ import annotations

from pydantic import field_validator

from pramaanx.schemas.base import VersionedModel


class DistrictRef(VersionedModel):
    """A stable district identity under one recorded boundary version.

    Names are display attributes, never identifiers: district names and parent
    states can change while a historical forecast must remain reproducible.
    """

    district_id: str
    district_name: str
    state_id: str
    state_name: str
    boundary_version: str

    @field_validator(
        "district_id",
        "district_name",
        "state_id",
        "state_name",
        "boundary_version",
    )
    @classmethod
    def _require_value(cls, value: str) -> str:
        if not value.strip():
            raise ValueError("geography identifiers, names, and versions cannot be blank")
        return value
