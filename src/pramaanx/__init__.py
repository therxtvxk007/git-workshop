"""PRAMAAN-X Zero-Base.

A cutoff-safe, open-world future-event forecasting system.

The pipeline is deliberately decomposed as::

    candidate discovery -> candidate adjudication -> calibration -> risk-controlled alerting

A model cannot score a future event that never enters the candidate pool, so the
discovery stage is evaluated in its own right (see :mod:`pramaanx.evaluation`).
"""

from __future__ import annotations

__version__ = "0.1.0"

__all__ = ["__version__"]
