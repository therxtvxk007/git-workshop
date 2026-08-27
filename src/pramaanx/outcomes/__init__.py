"""District outcome panel construction.

This package is the boundary between "what happened" and "what was forecast".
Everything in it reads outcome data, so everything in it is refused inside a
forecasting pass -- see :mod:`pramaanx.isolation`.

The order is fixed: normalise source rows into incidents, decide when each
incident became knowable, then lay out the district x cutoff x family
rectangle. External forecasts (CAST, VIEWS) travel alongside as benchmarks and
are structurally barred from becoming labels.
"""

from __future__ import annotations

from pramaanx.outcomes.external import (
    ExternalForecastError,
    assert_not_used_as_labels,
    available_at,
    benchmark_alignment,
    normalise_cast_rows,
    normalise_views_rows,
)
from pramaanx.outcomes.normalize import (
    NormalisationError,
    NormalisationReport,
    NormalisationResult,
    deduplicate_incidents,
    normalise_acled_rows,
    normalise_ucdp_rows,
)
from pramaanx.outcomes.ontology import (
    ONTOLOGY_VERSION,
    EventFamily,
    OntologyError,
    classify_acled,
    classify_ucdp,
    known_families,
)
from pramaanx.outcomes.panel import (
    PanelError,
    PanelReport,
    PanelResult,
    build_district_panel,
    validate_panel,
)
from pramaanx.outcomes.reporting_delay import (
    DEFAULT_DELAY_DAYS,
    ReportingDelayError,
    ReportingDelayPolicy,
    observed_delay_days,
)

__all__ = [
    "DEFAULT_DELAY_DAYS",
    "ONTOLOGY_VERSION",
    "EventFamily",
    "ExternalForecastError",
    "NormalisationError",
    "NormalisationReport",
    "NormalisationResult",
    "OntologyError",
    "PanelError",
    "PanelReport",
    "PanelResult",
    "ReportingDelayError",
    "ReportingDelayPolicy",
    "assert_not_used_as_labels",
    "available_at",
    "benchmark_alignment",
    "build_district_panel",
    "classify_acled",
    "classify_ucdp",
    "deduplicate_incidents",
    "known_families",
    "normalise_acled_rows",
    "normalise_cast_rows",
    "normalise_ucdp_rows",
    "normalise_views_rows",
    "observed_delay_days",
    "validate_panel",
]
