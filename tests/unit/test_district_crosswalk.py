from __future__ import annotations

from datetime import date

import pytest

from pramaanx.geography import CrosswalkEdge, DistrictCrosswalk


def test_split_is_invisible_before_effective_date_and_weighted_after() -> None:
    crosswalk = DistrictCrosswalk(
        [
            CrosswalkEdge(
                from_district_id="IND-D-OLD",
                to_district_id="IND-D-A",
                effective_on=date(2025, 1, 1),
                allocation_weight=0.6,
                source_hash="sha256:notice",
            ),
            CrosswalkEdge(
                from_district_id="IND-D-OLD",
                to_district_id="IND-D-B",
                effective_on=date(2025, 1, 1),
                allocation_weight=0.4,
                source_hash="sha256:notice",
            ),
        ]
    )
    assert crosswalk.translate("IND-D-OLD", as_of=date(2024, 12, 31)) == {"IND-D-OLD": 1.0}
    assert crosswalk.translate("IND-D-OLD", as_of=date(2025, 1, 1)) == {
        "IND-D-A": 0.6,
        "IND-D-B": 0.4,
    }


def test_split_weights_must_conserve_mass() -> None:
    with pytest.raises(ValueError, match="sum"):
        DistrictCrosswalk(
            [
                CrosswalkEdge(
                    from_district_id="old",
                    to_district_id="new",
                    effective_on=date(2025, 1, 1),
                    allocation_weight=0.9,
                    source_hash="sha256:x",
                )
            ]
        )
