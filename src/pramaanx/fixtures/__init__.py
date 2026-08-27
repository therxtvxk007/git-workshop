"""Frozen, reproducible evaluation fixtures.

A fixture here is not committed data. It is a *recipe plus a manifest of
hashes*: the synthetic world is seeded, so regenerating it on any machine must
reproduce the same snapshot identities, the same forecasts and the same report
hash. The manifest pins those values, and :func:`verify_manifest` fails loudly
when they drift.

That distinction matters. Committing 46 MB of generated bronze would put
derived bytes under review and invite someone to edit the fixture rather than
the generator that produced it. Pinning the hashes instead means the fixture
cannot silently change: either it regenerates exactly, or the build fails.
"""

from pramaanx.fixtures.calibration import (
    CalibrationSample,
    FixtureDriftError,
    FixtureManifest,
    build_manifest,
    load_calibration_sample,
    verify_manifest,
)

__all__ = [
    "CalibrationSample",
    "FixtureDriftError",
    "FixtureManifest",
    "build_manifest",
    "load_calibration_sample",
    "verify_manifest",
]
