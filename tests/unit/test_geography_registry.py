from __future__ import annotations

from datetime import date

import pytest

from pramaanx.geography import (
    DistrictNameResolver,
    DistrictRegistry,
    LgdColumnMap,
    district_id_from_lgd,
    entries_from_lgd_rows,
)


def make_registry() -> DistrictRegistry:
    rows = [
        {"District Code": "594", "District": "Thrissur", "State Code": "32", "State": "Kerala"},
        {"District Code": "603", "District": "Pune", "State Code": "27", "State": "Maharashtra"},
    ]
    entries = entries_from_lgd_rows(
        rows,
        columns=LgdColumnMap(
            district_code="District Code",
            district_name="District",
            state_code="State Code",
            state_name="State",
        ),
        boundary_version="lgd@2026-08-01",
        valid_from=date(2026, 8, 1),
        source_hash="sha256:lgd",
    )
    return DistrictRegistry(entries)


def test_lgd_rows_become_stable_district_identities() -> None:
    registry = make_registry()
    districts = registry.as_of(date(2026, 8, 27))
    assert [district.district_id for district in districts] == ["IND-D-594", "IND-D-603"]
    assert registry.get("IND-D-594", as_of=date(2026, 8, 27)).district_name == "Thrissur"


def test_lgd_mapping_is_explicit_and_missing_columns_fail() -> None:
    with pytest.raises(ValueError, match="missing columns"):
        entries_from_lgd_rows(
            [{"District Code": "594"}],
            columns=LgdColumnMap(
                district_code="District Code",
                district_name="District",
                state_code="State Code",
                state_name="State",
            ),
            boundary_version="v1",
            valid_from=date(2026, 1, 1),
            source_hash="sha256:x",
        )


def test_invalid_lgd_code_and_overlapping_versions_fail() -> None:
    with pytest.raises(ValueError, match="numeric"):
        district_id_from_lgd("KL-TSR")

    registry = make_registry()
    duplicate = registry.entries[0].model_copy(update={"valid_from": date(2026, 8, 2)})
    with pytest.raises(ValueError, match="overlapping"):
        DistrictRegistry([*registry.entries, duplicate])


def test_name_resolution_preserves_unresolved_state() -> None:
    resolver = DistrictNameResolver(make_registry())
    assert resolver.resolve("  THRISSUR ", as_of=date(2026, 8, 27)).district_ids == ["IND-D-594"]
    assert resolver.resolve("Not a district", as_of=date(2026, 8, 27)).status == "unresolved"
