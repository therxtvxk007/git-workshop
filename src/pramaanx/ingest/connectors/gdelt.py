"""GDELT 2.0 Events connector.

Two decisions in here matter more than the parsing.

**Which timestamp counts.** A GDELT row carries an event date (``SQLDATE``)
that can refer to something days old, and a ``DATEADDED`` recording when GDELT
processed it. Neither is "when this project could have seen it". The 15-minute
export file is the unit of publication, so ``first_observed_at`` is the file's
slot time plus a conservative publication lag. Using ``SQLDATE`` here would
back-date every record and quietly leak.

**What is dropped on the way in.** GDELT ships per-actor ethnic and religion
code columns. This project forecasts population-level and organisational
events and must not use protected identity as a risk proxy, so those columns
are discarded at ingestion rather than filtered later: evidence that never
enters bronze cannot become a feature by accident.
"""

from __future__ import annotations

import io
import zipfile
from collections.abc import Iterator
from datetime import UTC, datetime, timedelta
from typing import Any

from pramaanx.config import Settings
from pramaanx.hashing import canonical_bytes
from pramaanx.ingest.base import (
    Connector,
    ConnectorError,
    FetchWindow,
    RawItem,
    register_connector,
)
from pramaanx.ingest.http import Fetcher, HttpClient, NotFoundError
from pramaanx.logging import get_logger
from pramaanx.schemas.observation import Modality, SourceRecord

log = get_logger(__name__)

DEFAULT_BASE_URL = "https://data.gdeltproject.org/gdeltv2"
GDELT_V2_START = datetime(2015, 2, 18, 23, 0, tzinfo=UTC)
SLOT_MINUTES = 15

#: 0-indexed positions in the GDELT 2.0 Events export (61 columns).
COLUMNS: dict[str, int] = {
    "global_event_id": 0,
    "event_date": 1,
    "actor1_code": 5,
    "actor1_name": 6,
    "actor1_country_code": 7,
    "actor1_known_group_code": 8,
    "actor1_type1_code": 12,
    "actor2_code": 15,
    "actor2_name": 16,
    "actor2_country_code": 17,
    "actor2_known_group_code": 18,
    "actor2_type1_code": 22,
    "is_root_event": 25,
    "event_code": 26,
    "event_base_code": 27,
    "event_root_code": 28,
    "quad_class": 29,
    "goldstein_scale": 30,
    "num_mentions": 31,
    "num_sources": 32,
    "num_articles": 33,
    "avg_tone": 34,
    "action_geo_type": 51,
    "action_geo_fullname": 52,
    "action_geo_country_code": 53,
    "action_geo_adm1_code": 54,
    "action_geo_lat": 56,
    "action_geo_long": 57,
    "action_geo_feature_id": 58,
    "date_added": 59,
    "source_url": 60,
}

#: Deliberately never read. See the module docstring.
EXCLUDED_COLUMNS: tuple[str, ...] = (
    "Actor1EthnicCode",
    "Actor1Religion1Code",
    "Actor1Religion2Code",
    "Actor2EthnicCode",
    "Actor2Religion1Code",
    "Actor2Religion2Code",
)

EXPECTED_FIELD_COUNT = 61


def slot_times(window: FetchWindow, *, lag_minutes: int) -> list[datetime]:
    """15-minute export slots whose publication time falls inside ``window``.

    Slots are enumerated arithmetically instead of by downloading the master
    file list: the schedule is fixed, so the URL set for a window is
    deterministic and needs no network round-trip to plan.
    """
    lag = timedelta(minutes=lag_minutes)
    first = max(window.start - lag, GDELT_V2_START)
    minute = (first.minute // SLOT_MINUTES) * SLOT_MINUTES
    slot = first.replace(minute=minute, second=0, microsecond=0)
    if slot + lag < window.start:
        slot += timedelta(minutes=SLOT_MINUTES)

    slots: list[datetime] = []
    while slot + lag < window.end:
        if slot >= GDELT_V2_START:
            slots.append(slot)
        slot += timedelta(minutes=SLOT_MINUTES)
    return slots


def parse_export_csv(data: bytes, *, strict: bool = False) -> list[dict[str, Any]]:
    """Parse the tab-separated Events export into selected, typed fields."""
    rows: list[dict[str, Any]] = []
    text = data.decode("utf-8", errors="replace")
    for line_number, line in enumerate(text.splitlines(), start=1):
        if not line.strip():
            continue
        fields = line.split("\t")
        if len(fields) < EXPECTED_FIELD_COUNT:
            message = (
                f"GDELT row {line_number} has {len(fields)} fields, expected at least "
                f"{EXPECTED_FIELD_COUNT}"
            )
            if strict:
                raise ConnectorError(message)
            log.warning("gdelt.short_row", line=line_number, fields=len(fields))
            continue
        record = {name: fields[index].strip() for name, index in COLUMNS.items()}
        rows.append({key: value for key, value in record.items() if value != ""})
    return rows


def _parse_date_added(value: str | None) -> datetime | None:
    if not value or len(value) != 14 or not value.isdigit():
        return None
    return datetime.strptime(value, "%Y%m%d%H%M%S").replace(tzinfo=UTC)


def _parse_event_date(value: str | None) -> datetime | None:
    if not value or len(value) != 8 or not value.isdigit():
        return None
    return datetime.strptime(value, "%Y%m%d").replace(tzinfo=UTC)


@register_connector
class GdeltConnector(Connector):
    """Ingests GDELT 2.0 Events export files into bronze."""

    source_id = "gdelt"
    tier = 0

    def __init__(
        self,
        settings: Settings,
        options: dict[str, Any] | None = None,
        fetcher: Fetcher | None = None,
    ) -> None:
        super().__init__(settings, options)
        self.base_url = str(self.options.get("base_url", DEFAULT_BASE_URL)).rstrip("/")
        self.publication_lag_minutes = int(
            self.options.get("publication_lag_minutes", SLOT_MINUTES)
        )
        self.max_rows_per_file = int(self.options.get("max_rows_per_file", 0))
        self.country_filter = {
            str(code).upper() for code in self.options.get("country_filter", []) if code
        }
        self.event_root_codes = {
            str(code) for code in self.options.get("event_root_codes", []) if code
        }
        self.skip_missing_files = bool(self.options.get("skip_missing_files", True))
        self._fetcher = fetcher or self._default_fetcher()

    def _default_fetcher(self) -> Fetcher:
        cache_dir = self.settings.storage.data_root / "http_cache" / self.source_id
        client = HttpClient(
            cache_dir=cache_dir if self.options.get("cache", True) else None,
            timeout_seconds=float(self.options.get("timeout_seconds", 60.0)),
            max_attempts=int(self.options.get("max_attempts", 4)),
            backoff_seconds=float(self.options.get("backoff_seconds", 2.0)),
            # Proxy behaviour is configurable per source and otherwise follows
            # the standard environment. See pramaanx.ingest.http.
            proxy=self.options.get("proxy"),
            trust_env=bool(self.options.get("trust_env", True)),
            ca_bundle=self.options.get("ca_bundle"),
            verify=bool(self.options.get("verify", True)),
        )
        return client.get

    @property
    def source_record(self) -> SourceRecord:
        return SourceRecord(
            source_id=self.source_id,
            source_type="event_database",
            display_name="GDELT 2.0 Events",
            tier=0,
            licence="GDELT Project terms of use",
            licence_url="https://www.gdeltproject.org/about.html#termsofuse",
            redistributable=False,
            base_url=self.base_url,
            source_version="gdelt-2.0-export",
            reliability_prior=0.55,
            notes=(
                "Machine-coded from news reporting; coding error and media attention bias "
                "are material. Ethnic and religion code columns are dropped at ingestion."
            ),
        )

    def file_url(self, slot: datetime) -> str:
        stamp = slot.strftime("%Y%m%d%H%M%S")
        return f"{self.base_url}/{stamp}.export.CSV.zip"

    def plan(self, window: FetchWindow) -> dict[str, Any]:
        slots = slot_times(window, lag_minutes=self.publication_lag_minutes)
        plan = super().plan(window)
        plan.update(
            {
                "base_url": self.base_url,
                "publication_lag_minutes": self.publication_lag_minutes,
                "proxy": self.options.get("proxy")
                or ("<environment>" if self.options.get("trust_env", True) else "<none>"),
                "files": len(slots),
                "first_file": self.file_url(slots[0]) if slots else None,
                "last_file": self.file_url(slots[-1]) if slots else None,
                "excluded_columns": list(EXCLUDED_COLUMNS),
                "filters": {
                    "country_filter": sorted(self.country_filter),
                    "event_root_codes": sorted(self.event_root_codes),
                    "max_rows_per_file": self.max_rows_per_file,
                },
            }
        )
        return plan

    def _keep(self, row: dict[str, Any]) -> bool:
        if self.country_filter:
            country = str(row.get("action_geo_country_code", "")).upper()
            if country not in self.country_filter:
                return False
        if not self.event_root_codes:
            return True
        return str(row.get("event_root_code", "")) in self.event_root_codes

    @staticmethod
    def _extract_csv(payload: bytes) -> bytes:
        with zipfile.ZipFile(io.BytesIO(payload)) as archive:
            names = [name for name in sorted(archive.namelist()) if name.lower().endswith(".csv")]
            if not names:
                raise ConnectorError("GDELT archive contains no CSV member")
            return archive.read(names[0])

    def fetch(self, window: FetchWindow) -> Iterator[RawItem]:
        lag = timedelta(minutes=self.publication_lag_minutes)
        for slot in slot_times(window, lag_minutes=self.publication_lag_minutes):
            url = self.file_url(slot)
            try:
                payload = self._fetcher(url)
            except NotFoundError:
                # Gaps in the archive are normal; a silent gap is not, so log it.
                log.warning("gdelt.missing_file", url=url)
                if self.skip_missing_files:
                    continue
                raise
            rows = parse_export_csv(self._extract_csv(payload))
            kept = 0
            for row in rows:
                if not self._keep(row):
                    continue
                if self.max_rows_per_file and kept >= self.max_rows_per_file:
                    break
                kept += 1
                yield self._to_item(row, slot, lag, url)
            log.debug("gdelt.file", url=url, rows=len(rows), kept=kept)

    def _to_item(self, row: dict[str, Any], slot: datetime, lag: timedelta, url: str) -> RawItem:
        date_added = _parse_date_added(row.get("date_added"))
        payload = {
            "source": "gdelt",
            "export_slot": slot.isoformat(),
            "export_url": url,
            **row,
        }
        return RawItem(
            payload=canonical_bytes(payload),
            # The publication instant, not the event date: see module docstring.
            first_observed_at=slot + lag,
            modality=Modality.TABULAR,
            published_at=slot + lag,
            claimed_event_time=_parse_event_date(row.get("event_date")),
            uri=row.get("source_url"),
            language="en",
            licence="GDELT Project terms of use",
            source_version="gdelt-2.0-export",
            metadata={
                "global_event_id": row.get("global_event_id"),
                "date_added": date_added.isoformat() if date_added else None,
            },
        )
