"""Declared, availability-stamped feature construction.

A feature is declared in :mod:`pramaanx.features.spec` before it can be built
in :mod:`pramaanx.features.builders`. The declaration carries the range, the
window and the expected sign; the built vector carries the instant it was
computed as of and the graph cutoff it came from.

That pairing is what makes the audit question answerable from the artefact
alone: *could this number have been computed on the day it claims?* A feature
store without it is one careless join away from training on its own future.
"""

from __future__ import annotations

from pramaanx.features.builders import (
    COUNT_WINDOWS,
    ESCALATION_BASELINE_DAYS,
    ESCALATION_RECENT_DAYS,
    FEATURE_NAMES,
    SPECS,
    build_feature_table,
    build_features,
    series_from_clusters,
)
from pramaanx.features.spec import (
    REGISTRY,
    FeatureKind,
    FeatureRegistry,
    FeatureSpec,
    FeatureVector,
    SeriesKey,
)

__all__ = [
    "COUNT_WINDOWS",
    "ESCALATION_BASELINE_DAYS",
    "ESCALATION_RECENT_DAYS",
    "FEATURE_NAMES",
    "REGISTRY",
    "SPECS",
    "FeatureKind",
    "FeatureRegistry",
    "FeatureSpec",
    "FeatureVector",
    "SeriesKey",
    "build_feature_table",
    "build_features",
    "series_from_clusters",
]
