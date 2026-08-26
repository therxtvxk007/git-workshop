"""Connector interface and registry.

Every source, however exotic, reduces to the same job: hand back raw bytes plus
an honest answer to "when could this project first have seen this?". That
answer -- ``first_observed_at`` -- is what cutoff filtering runs on, so a
connector that fakes it defeats the entire temporal guarantee.
"""

from __future__ import annotations

from abc import ABC, abstractmethod
from collections.abc import Iterable, Iterator, Mapping
from dataclasses import dataclass, field
from datetime import UTC, datetime
from typing import Any, ClassVar

from pramaanx.config import SOURCE_OPTION_MODELS, Settings, SourceOptions
from pramaanx.schemas.observation import Modality, SourceRecord


class ConnectorError(RuntimeError):
    """A connector failed while acquiring evidence."""


@dataclass(frozen=True)
class FetchWindow:
    """A half-open acquisition window ``[start, end)`` in UTC."""

    start: datetime
    end: datetime

    def __post_init__(self) -> None:
        if self.start.tzinfo is None or self.end.tzinfo is None:
            raise ValueError("FetchWindow bounds must be timezone-aware")
        if self.end <= self.start:
            raise ValueError(f"empty fetch window: {self.start} -> {self.end}")

    @property
    def days(self) -> float:
        return (self.end - self.start).total_seconds() / 86400.0

    def contains(self, moment: datetime) -> bool:
        return self.start <= moment < self.end

    @classmethod
    def from_dates(cls, start: str, end: str) -> FetchWindow:
        return cls(_parse_boundary(start), _parse_boundary(end))


def _parse_boundary(value: str) -> datetime:
    parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
    return parsed.replace(tzinfo=UTC) if parsed.tzinfo is None else parsed.astimezone(UTC)


@dataclass(frozen=True)
class RawItem:
    """One acquired payload, before it becomes an :class:`Observation`."""

    payload: bytes
    first_observed_at: datetime
    modality: Modality = Modality.TEXT
    published_at: datetime | None = None
    claimed_event_time: datetime | None = None
    uri: str | None = None
    language: str | None = None
    licence: str | None = None
    source_version: str = "unversioned"
    metadata: dict[str, Any] = field(default_factory=dict)

    def __post_init__(self) -> None:
        if self.first_observed_at.tzinfo is None:
            raise ValueError("RawItem.first_observed_at must be timezone-aware")


class Connector(ABC):
    """Base class for evidence connectors."""

    #: Stable identifier used in configs, manifests and provenance.
    source_id: str = ""
    #: 0 = required for the first working model, 1 = later extension,
    #: 2 = institutional/licensed.
    tier: int = 0
    #: The validated shape of this connector's options, from
    #: :data:`pramaanx.config.SOURCE_OPTION_MODELS`.
    options_model: ClassVar[type[SourceOptions]]

    def __init__(
        self, settings: Settings, options: SourceOptions | Mapping[str, Any] | None = None
    ) -> None:
        if not self.source_id:
            raise ConnectorError(f"{type(self).__name__} must define source_id")
        self.settings = settings
        # A plain mapping is validated here rather than trusted, so constructing
        # a connector directly rejects the same typos that loading a config
        # would. Options are typed from this point on: no .get() with a string
        # key that nothing checks.
        model = type(self).options_model
        if isinstance(options, SourceOptions):
            self.options = options
        else:
            self.options = model.model_validate(dict(options or {}))

    @property
    @abstractmethod
    def source_record(self) -> SourceRecord:
        """Provenance and licence terms for this source."""

    @abstractmethod
    def fetch(self, window: FetchWindow) -> Iterable[RawItem]:
        """Yield raw items whose ``first_observed_at`` falls inside ``window``."""

    def plan(self, window: FetchWindow) -> dict[str, Any]:
        """Describe what a fetch would do, without doing it (``--dry-run``)."""
        return {
            "source_id": self.source_id,
            "tier": self.tier,
            "window_start": window.start.isoformat(),
            "window_end": window.end.isoformat(),
            "window_days": round(window.days, 4),
            "options": self.options.model_dump(mode="json"),
            "implemented": type(self).fetch is not Connector.fetch,
        }

    def guarded_fetch(self, window: FetchWindow) -> Iterator[RawItem]:
        """Fetch and enforce that items really belong to the requested window."""
        for item in self.fetch(window):
            if not window.contains(item.first_observed_at):
                raise ConnectorError(
                    f"{self.source_id} returned an item first observed at "
                    f"{item.first_observed_at.isoformat()}, outside the requested window "
                    f"[{window.start.isoformat()}, {window.end.isoformat()})"
                )
            yield item


_REGISTRY: dict[str, type[Connector]] = {}


def register_connector(cls: type[Connector]) -> type[Connector]:
    """Class decorator that publishes a connector under its ``source_id``."""
    if not cls.source_id:
        raise ConnectorError(f"{cls.__name__} must define source_id before registration")
    if cls.source_id in _REGISTRY and _REGISTRY[cls.source_id] is not cls:
        raise ConnectorError(f"duplicate connector source_id: {cls.source_id}")
    registered = SOURCE_OPTION_MODELS.get(cls.source_id)
    if registered is None:
        raise ConnectorError(
            f"connector {cls.source_id!r} has no options model registered in "
            "pramaanx.config.SOURCE_OPTION_MODELS; its configuration would be unchecked"
        )
    cls.options_model = registered
    _REGISTRY[cls.source_id] = cls
    return cls


def get_connector_class(source_id: str) -> type[Connector]:
    from pramaanx.ingest import connectors  # noqa: F401  (populates the registry)

    if source_id not in _REGISTRY:
        known = ", ".join(sorted(_REGISTRY)) or "<none>"
        raise KeyError(f"unknown connector {source_id!r}; registered: {known}")
    return _REGISTRY[source_id]


def build_connector(source_id: str, settings: Settings) -> Connector:
    cls = get_connector_class(source_id)
    return cls(settings, settings.source_options(source_id))


def available_connectors() -> dict[str, type[Connector]]:
    from pramaanx.ingest import connectors  # noqa: F401

    return dict(sorted(_REGISTRY.items()))
