from __future__ import annotations

from datetime import date

from pramaanx.geography import DistrictRegistry
from pramaanx.geography.registry import DistrictRegistryEntry
from pramaanx.schemas import DistrictRef


def entry(district_id: str, name: str, start: date, end: date | None) -> DistrictRegistryEntry:
    return DistrictRegistryEntry(
        district=DistrictRef(
            district_id=district_id,
            district_name=name,
            state_id="IND-S-1",
            state_name="State",
            boundary_version=f"boundary@{start.isoformat()}",
        ),
        lgd_district_code=district_id.removeprefix("IND-D-"),
        valid_from=start,
        valid_to=end,
        source_hash=f"sha256:{start.isoformat()}",
    )


def test_later_split_cannot_change_earlier_district_universe() -> None:
    before_split = entry("IND-D-100", "Original", date(2020, 1, 1), date(2025, 5, 31))
    original_after = entry("IND-D-100", "Original", date(2025, 6, 1), None)
    new_district = entry("IND-D-101", "New District", date(2025, 6, 1), None)

    old_registry = DistrictRegistry([before_split])
    expanded_registry = DistrictRegistry([before_split, original_after, new_district])

    cutoff = date(2024, 12, 31)
    assert expanded_registry.as_of(cutoff) == old_registry.as_of(cutoff)
    assert [district.district_id for district in expanded_registry.as_of(date(2025, 6, 1))] == [
        "IND-D-100",
        "IND-D-101",
    ]
