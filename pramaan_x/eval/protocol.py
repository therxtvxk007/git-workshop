"""The locked temporal evaluation protocol.

One object defines every temporal decision in the benchmark, so that a result
can be attributed to a protocol rather than to whatever the caller happened to
pass. Nothing in the evaluation path is allowed to choose a window, an origin
or a fitting scope on its own.

The layout is::

    |<-- train -->|<- embargo ->|<-- calibration -->|<- embargo ->|<-- TEST -->|
    t0            t1            t1+E                t2            t2+E     t3

  * **train**        the only window whose labels may be seen by anything fitted
  * **embargo**      a gap wide enough that a label computed with a forward
                     lookahead inside one window cannot reach across into the
                     next. It is `max(embargo_days, label_lookahead_days)`.
  * **calibration**  where thresholds, widths and model variants are chosen
  * **test**         locked. Read once, reported, never used to select anything

Splits are temporal and contiguous. There is no random split anywhere in this
module and there must never be one: shuffling documents across time makes the
train set contain the future of the test set, which for a precursor-retrieval
task is the whole game.

Forecast origins are a fixed grid inside a window, spaced `origin_stride_days`
apart. Evaluating on a grid rather than at each event's own timestamp is what
makes snapshot indexing affordable, and it is conservative in the only
direction that matters: a query at event time T is evaluated at the last grid
origin O <= T, so documents in (O, T] are excluded from the index *and* from
the relevant set alike. Recall is therefore measured against what was
retrievable at O, not against a ground truth the retriever could not have seen.
"""

from __future__ import annotations

import hashlib
import json
from collections.abc import Sequence
from dataclasses import asdict, dataclass, field
from datetime import datetime, timedelta
from itertools import pairwise

from .availability import NaiveTimestampError, to_utc

#: Identifier of the protocol definition. Bump this when the *meaning* of a
#: field changes, so old artefacts cannot be silently compared with new ones.
PROTOCOL_VERSION = "oracle-target-retrieval/1"

#: What is allowed to be fitted, and on what. Recorded in every artefact.
PERMITTED_FITTING = (
    "bm25_corpus_statistics: documents available strictly before the fold origin",
    "hashing_idf: documents available strictly before the fold origin",
    "vector_index: documents available strictly before the fold origin",
    "lexicon_log_odds: training-window documents with training-window labels only",
    "learned_fusion_lambdamart: training-window queries only",
)

#: How a query's text is produced. This is the oracle assumption, stated once.
QUERY_GENERATION_RULE = (
    "oracle_target: the query text is the target location verbatim plus the "
    "top-n terms of the training-fitted lexicon for the target's event type. "
    "The target location and event type are GIVEN, not inferred. This is an "
    "evidence-retrieval protocol, not an event-forecasting protocol."
)

AVAILABILITY_RULE = (
    "available_at = max(published_at, retrieved_at); usable at origin T only if "
    "published_at < T and retrieved_at < T; missing retrieved_at is rejected "
    "unless the document carries an explicit trusted_historical_snapshot flag"
)


class ProtocolError(ValueError):
    """Raised when a protocol would be internally inconsistent."""


@dataclass(frozen=True)
class TemporalProtocol:
    """The full temporal contract for one benchmark run."""

    train_start: datetime
    train_end: datetime
    calibration_start: datetime
    calibration_end: datetime
    test_start: datetime
    test_end: datetime
    embargo_days: int
    label_lookahead_days: int
    origin_stride_days: int
    version: str = PROTOCOL_VERSION
    availability_rule: str = AVAILABILITY_RULE
    query_generation_rule: str = QUERY_GENERATION_RULE
    permitted_fitting: tuple[str, ...] = PERMITTED_FITTING
    notes: tuple[str, ...] = field(default_factory=tuple)

    def __post_init__(self) -> None:
        bounds = [
            ("train_start", self.train_start),
            ("train_end", self.train_end),
            ("calibration_start", self.calibration_start),
            ("calibration_end", self.calibration_end),
            ("test_start", self.test_start),
            ("test_end", self.test_end),
        ]
        for name, ts in bounds:
            if ts.tzinfo is None:
                raise ProtocolError(f"{name} must be timezone aware")
        for (a_name, a), (b_name, b) in pairwise(bounds):
            if not a <= b:
                raise ProtocolError(f"{a_name} ({a}) must not follow {b_name} ({b})")
        if self.train_end - self.train_start < timedelta(days=1):
            raise ProtocolError("training window must span at least one day")
        if self.test_end <= self.test_start:
            raise ProtocolError("test window must be non-empty")
        gap = self.effective_embargo_days
        if (self.calibration_start - self.train_end).days < gap:
            raise ProtocolError(
                f"train->calibration gap is {(self.calibration_start - self.train_end).days}d, "
                f"below the effective embargo of {gap}d"
            )
        if (self.test_start - self.calibration_end).days < gap:
            raise ProtocolError(
                f"calibration->test gap is {(self.test_start - self.calibration_end).days}d, "
                f"below the effective embargo of {gap}d"
            )
        if self.origin_stride_days < 1:
            raise ProtocolError("origin_stride_days must be >= 1")

    # ------------------------------------------------------------ windows ---

    @property
    def effective_embargo_days(self) -> int:
        """The gap that actually has to hold.

        A label built by looking `label_lookahead_days` forward from a document
        reaches into the future of its own window. An embargo narrower than
        that lookahead does not separate the windows, whatever it is called.
        """
        return max(int(self.embargo_days), int(self.label_lookahead_days))

    @property
    def label_cutoff(self) -> datetime:
        """Latest publication date a training document may have.

        Its label looks `label_lookahead_days` forward, and that lookahead must
        stay inside the training window.
        """
        return self.train_end - timedelta(days=self.label_lookahead_days)

    def window(self, name: str) -> tuple[datetime, datetime]:
        try:
            return {
                "train": (self.train_start, self.train_end),
                "calibration": (self.calibration_start, self.calibration_end),
                "test": (self.test_start, self.test_end),
            }[name]
        except KeyError:
            raise ProtocolError(f"unknown window {name!r}") from None

    def contains(self, name: str, ts: datetime) -> bool:
        start, end = self.window(name)
        return start <= to_utc(ts) < end

    # ------------------------------------------------------------ origins ---

    def origins(self, name: str) -> list[datetime]:
        """The forecast-origin grid for a window, `[start, end)`."""
        start, end = self.window(name)
        step = timedelta(days=self.origin_stride_days)
        out: list[datetime] = []
        t = start
        while t < end:
            out.append(t)
            t += step
        return out

    def origin_for(self, name: str, event_time: datetime) -> datetime | None:
        """The last grid origin at or before `event_time`, or None if the event
        precedes the window's first origin.

        Choosing the *last* origin before the event is what keeps the protocol
        honest: taking the next one would put the index past the event.
        """
        event_time = to_utc(event_time)
        start, end = self.window(name)
        if not (start <= event_time < end):
            return None
        step_days = self.origin_stride_days
        offset = (event_time - start).days // step_days * step_days
        return start + timedelta(days=int(offset))

    # -------------------------------------------------------- identity ---

    def to_dict(self) -> dict[str, object]:
        raw = asdict(self)
        for k, v in list(raw.items()):
            if isinstance(v, datetime):
                raw[k] = to_utc(v).isoformat()
            elif isinstance(v, tuple):
                raw[k] = list(v)
        raw["effective_embargo_days"] = self.effective_embargo_days
        raw["label_cutoff"] = to_utc(self.label_cutoff).isoformat()
        raw["n_test_origins"] = len(self.origins("test"))
        raw["n_train_origins"] = len(self.origins("train"))
        return raw

    def fingerprint(self) -> str:
        blob = json.dumps(self.to_dict(), sort_keys=True, default=str)
        return hashlib.sha256(blob.encode()).hexdigest()[:16]

    # ------------------------------------------------------ construction ---

    @classmethod
    def from_span(
        cls,
        start: datetime,
        end: datetime,
        *,
        train_frac: float = 0.55,
        calibration_frac: float = 0.15,
        embargo_days: int = 7,
        label_lookahead_days: int = 21,
        origin_stride_days: int = 7,
        notes: Sequence[str] = (),
    ) -> TemporalProtocol:
        """Derive the windows from a corpus span by fixed fractions.

        The fractions are protocol constants, not tuning knobs: they are chosen
        before any measurement and are not permitted to move in response to a
        test result. What is left after train, calibration and two embargoes is
        the test window, which is why the test window is never the thing being
        sized to taste.
        """
        try:
            start, end = to_utc(start), to_utc(end)
        except NaiveTimestampError as exc:
            raise ProtocolError(f"corpus span bounds must be timezone aware: {exc}") from exc
        total = (end - start).days
        gap = max(int(embargo_days), int(label_lookahead_days))
        usable = total - 2 * gap
        if usable < 3:
            raise ProtocolError(
                f"corpus spans {total}d; with a {gap}d embargo there is no room "
                f"for train/calibration/test windows"
            )
        train_days = max(1, int(usable * train_frac))
        cal_days = max(1, int(usable * calibration_frac))
        if train_days + cal_days >= usable:
            raise ProtocolError("train and calibration fractions leave no test window")
        train_end = start + timedelta(days=train_days)
        cal_start = train_end + timedelta(days=gap)
        cal_end = cal_start + timedelta(days=cal_days)
        test_start = cal_end + timedelta(days=gap)
        return cls(
            train_start=start,
            train_end=train_end,
            calibration_start=cal_start,
            calibration_end=cal_end,
            test_start=test_start,
            test_end=end,
            embargo_days=int(embargo_days),
            label_lookahead_days=int(label_lookahead_days),
            origin_stride_days=int(origin_stride_days),
            notes=tuple(notes),
        )
