"""ACLED event API connector.

ACLED is a living, credentialed event database.  The timestamp that controls
cutoff admission is its ``timestamp`` field: ACLED documents this as the exact
time the current event body was uploaded to the API.  ``event_date`` is only the
claimed date of the underlying event and must never be used for availability.

Revisions are conservative by construction.  When ACLED changes an event, the
current row receives the later API timestamp; without an external versioned
archive the connector cannot reconstruct the earlier body for deep-history
cutoffs.  It therefore under-represents what was known at those early cutoffs
rather than leaking the revised body backwards.

The connector uses cursor pagination now.  ACLED says page pagination will be
deprecated for ordinary (dyadic) exports on 2026-10-01.  Every page is checked
against a stable total and stable query restrictions, duplicate ids and cursor
cycles are errors, and no item is yielded until the complete traversal has been
validated.
"""

from __future__ import annotations

import json
import os
from collections.abc import Iterator, Mapping
from dataclasses import dataclass
from datetime import UTC, datetime
from math import ceil
from typing import Any
from urllib.parse import urlencode

from pramaanx.config import AcledSourceConfig, Settings
from pramaanx.hashing import canonical_bytes
from pramaanx.ingest.base import (
    Connector,
    ConnectorError,
    FetchWindow,
    RawItem,
    register_connector,
)
from pramaanx.ingest.http import HttpClient
from pramaanx.schemas.observation import Modality, SourceRecord

ACLED_ENDPOINT = "https://acleddata.com/api/acled/read"
ACLED_TOKEN_ENDPOINT = "https://acleddata.com/oauth/token"
CONTRACT_VERIFIED_ON = "2026-08-26"

OFFICIAL_DOCS = (
    "https://acleddata.com/api-documentation/getting-started",
    "https://acleddata.com/api-documentation/elements-acleds-api",
    "https://acleddata.com/api-documentation/acled-endpoint",
    "https://acleddata.com/methodology/acled-codebook",
    "https://acleddata.com/eula",
)

API_CONTRACT: dict[str, Any] = {
    "verified_against_official_docs": True,
    "verified_on": CONTRACT_VERIFIED_ON,
    "genuinely_live_api_verified": False,
    "official_docs": OFFICIAL_DOCS,
    "authentication": "OAuth bearer token; password grant documented for scripts",
    "pagination": "cursor; start at 0 and stop only when next_cursor is null",
    "availability_field": "timestamp (Unix seconds; current body last uploaded to API)",
    "response_required": (
        "status",
        "success",
        "count",
        "total_count",
        "messages",
        "data",
        "filename",
        "data_query_restrictions",
        "next_cursor",
    ),
}

REQUESTED_FIELDS = (
    "event_id_cnty",
    "event_date",
    "year",
    "time_precision",
    "disorder_type",
    "event_type",
    "sub_event_type",
    "actor1",
    "assoc_actor_1",
    "inter1",
    "actor2",
    "assoc_actor_2",
    "inter2",
    "interaction",
    "civilian_targeting",
    "iso",
    "region",
    "country",
    "admin1",
    "admin2",
    "admin3",
    "location",
    "latitude",
    "longitude",
    "geo_precision",
    "source",
    "source_scale",
    "notes",
    "fatalities",
    "tags",
    "timestamp",
)

LICENCE = (
    "ACLED EULA, Content Usage Terms, and Attribution Policy; non-commercial use unless "
    "separately licensed, no credential sharing, and external materials must be "
    "transformative and non-reconstructable"
)


class AcledContractError(ConnectorError):
    """The API returned a shape that the verified contract does not recognize."""


class AcledAuthenticationError(ConnectorError):
    """ACLED credentials are absent or its OAuth response is invalid."""


class AcledIncompleteIngestError(ConnectorError):
    """A cursor walk ended before every row in the reported total was validated."""


@dataclass(frozen=True)
class AcledPage:
    items: tuple[dict[str, Any], ...]
    count: int
    total_count: int
    next_cursor: str | None
    restrictions: dict[str, Any]


def _required_int(value: Any, name: str, *, minimum: int = 0) -> int:
    if isinstance(value, bool) or not isinstance(value, int) or value < minimum:
        raise AcledContractError(f"{name} must be an integer >= {minimum}")
    return value


def _required_string(value: Any, name: str, *, allow_empty: bool = False) -> str:
    if not isinstance(value, str) or (not allow_empty and not value.strip()):
        qualifier = "a string" if allow_empty else "a non-empty string"
        raise AcledContractError(f"{name} must be {qualifier}")
    return value


def parse_token_response(payload: bytes) -> str:
    """Return a bearer token without ever including it in an exception."""
    try:
        document = json.loads(payload)
    except (UnicodeDecodeError, json.JSONDecodeError) as error:
        raise AcledAuthenticationError("ACLED OAuth response was not valid JSON") from error
    if not isinstance(document, dict):
        raise AcledAuthenticationError("ACLED OAuth response must be an object")
    token = document.get("access_token")
    token_type = document.get("token_type")
    expires = document.get("expires_in")
    if not isinstance(token, str) or not token:
        raise AcledAuthenticationError("ACLED OAuth response lacks a non-empty access_token")
    if not isinstance(token_type, str) or token_type.lower() != "bearer":
        raise AcledAuthenticationError("ACLED OAuth response token_type is not Bearer")
    if isinstance(expires, bool) or not isinstance(expires, int) or expires <= 0:
        raise AcledAuthenticationError("ACLED OAuth response expires_in must be positive")
    return token


def parse_envelope(payload: bytes) -> AcledPage:
    """Parse one JSON cursor page and reject missing or contradictory structure."""
    try:
        document = json.loads(payload)
    except (UnicodeDecodeError, json.JSONDecodeError) as error:
        raise AcledContractError("ACLED response was not valid JSON") from error
    if not isinstance(document, dict):
        raise AcledContractError("ACLED response must be an object")

    missing = [name for name in API_CONTRACT["response_required"] if name not in document]
    if missing:
        raise AcledContractError(f"ACLED response is missing required fields: {missing}")
    if _required_int(document["status"], "status") != 200:
        raise AcledContractError("ACLED response status is not 200")
    if document["success"] is not True:
        raise AcledContractError("ACLED response success is not true")

    count = _required_int(document["count"], "count")
    total_count = _required_int(document["total_count"], "total_count")
    data = document["data"]
    if not isinstance(data, list):
        raise AcledContractError("data must be an array")
    if count != len(data):
        raise AcledContractError(f"count {count} does not equal len(data) {len(data)}")
    if total_count < count:
        raise AcledContractError("total_count cannot be smaller than count")
    if not all(isinstance(item, dict) for item in data):
        raise AcledContractError("every data entry must be an object")

    messages = document["messages"]
    if not isinstance(messages, list):
        raise AcledContractError("messages must be an array")
    if messages:
        raise AcledContractError("ACLED returned messages requiring operator review")
    _required_string(document["filename"], "filename", allow_empty=True)
    restrictions = document["data_query_restrictions"]
    if not isinstance(restrictions, dict):
        raise AcledContractError("data_query_restrictions must be an object")

    raw_cursor = document["next_cursor"]
    if raw_cursor is None:
        next_cursor = None
    elif isinstance(raw_cursor, bool) or not isinstance(raw_cursor, (int, str)):
        raise AcledContractError("next_cursor must be an integer, string, or null")
    else:
        next_cursor = str(raw_cursor)
        if not next_cursor:
            raise AcledContractError("next_cursor cannot be empty")

    return AcledPage(
        items=tuple(data),
        count=count,
        total_count=total_count,
        next_cursor=next_cursor,
        restrictions=dict(restrictions),
    )


def _parse_event_date(value: Any) -> datetime:
    text = _required_string(value, "event_date")
    try:
        parsed = datetime.strptime(text, "%Y-%m-%d").replace(tzinfo=UTC)
    except ValueError as error:
        raise AcledContractError("event_date must use YYYY-MM-DD") from error
    return parsed


def _parse_timestamp(value: Any) -> datetime:
    seconds = _required_int(value, "timestamp", minimum=1)
    try:
        return datetime.fromtimestamp(seconds, tz=UTC)
    except (OverflowError, OSError, ValueError) as error:
        raise AcledContractError("timestamp is outside the supported Unix range") from error


def _validate_item(item: dict[str, Any]) -> tuple[str, datetime, datetime]:
    event_id = _required_string(item.get("event_id_cnty"), "event_id_cnty")
    event_date = _parse_event_date(item.get("event_date"))
    availability = _parse_timestamp(item.get("timestamp"))
    year = _required_int(item.get("year"), "year", minimum=1900)
    if year != event_date.year:
        raise AcledContractError("year does not match event_date")
    if event_date > availability:
        raise AcledContractError("event_date is after the API upload timestamp")
    _required_int(item.get("time_precision"), "time_precision", minimum=1)
    _required_int(item.get("geo_precision"), "geo_precision", minimum=1)
    _required_int(item.get("iso"), "iso", minimum=1)
    _required_int(item.get("fatalities"), "fatalities")
    for name in ("disorder_type", "event_type", "sub_event_type", "country", "location"):
        _required_string(item.get(name), name)
    for name in (
        "actor1",
        "assoc_actor_1",
        "inter1",
        "actor2",
        "assoc_actor_2",
        "inter2",
        "interaction",
        "civilian_targeting",
        "region",
        "admin1",
        "admin2",
        "admin3",
        "source",
        "source_scale",
        "notes",
        "tags",
    ):
        _required_string(item.get(name), name, allow_empty=True)
    for name, lower, upper in (("latitude", -90.0, 90.0), ("longitude", -180.0, 180.0)):
        value = item.get(name)
        if isinstance(value, bool) or not isinstance(value, (int, float)):
            raise AcledContractError(f"{name} must be numeric")
        if not lower <= float(value) <= upper:
            raise AcledContractError(f"{name} is outside [{lower}, {upper}]")
    return event_id, event_date, availability


@register_connector
class AcledConnector(Connector):
    """Ingest current ACLED dyadic events into the cutoff-safe bronze ledger."""

    source_id = "acled"
    tier = 0

    def __init__(
        self,
        settings: Settings,
        options: AcledSourceConfig | Mapping[str, Any] | None = None,
        *,
        environ: Mapping[str, str] | None = None,
        http_client: HttpClient | None = None,
    ) -> None:
        super().__init__(settings, options)
        config = self._options
        self.base_url = config.base_url
        self.token_url = config.token_url
        self.countries = tuple(
            sorted({value.strip() for value in config.countries if value.strip()})
        )
        self.event_types = tuple(
            sorted({value.strip() for value in config.event_types if value.strip()})
        )
        self.page_size = config.page_size
        self.max_pages = config.max_pages
        self._environ = dict(os.environ if environ is None else environ)
        self._http = http_client or HttpClient(
            cache_dir=None,  # ACLED is living data; a URL cache would hide revisions.
            timeout_seconds=config.timeout_seconds,
            max_attempts=config.max_attempts,
            backoff_seconds=config.backoff_seconds,
            max_retry_after_seconds=config.max_retry_after_seconds,
            min_interval_seconds=config.min_interval_seconds,
            proxy=config.proxy,
            trust_env=config.trust_env,
            ca_bundle=config.ca_bundle,
            verify=config.verify,
        )

    @property
    def _options(self) -> AcledSourceConfig:
        assert isinstance(self.options, AcledSourceConfig)
        return self.options

    @property
    def source_record(self) -> SourceRecord:
        return SourceRecord(
            source_id=self.source_id,
            source_type="event_database",
            display_name="Armed Conflict Location & Event Data (ACLED)",
            tier=self.tier,
            licence=LICENCE,
            licence_url="https://acleddata.com/eula",
            redistributable=False,
            base_url=self.base_url,
            source_version=f"acled-api-contract-{CONTRACT_VERIFIED_ON}",
            reliability_prior=0.70,
            notes=(
                "Human-coded living dataset with multi-stage review; event bodies may be "
                "revised. Availability uses the current row's API timestamp, so historical "
                "cutoffs are conservative without an external versioned archive. Raw ACLED "
                "data and credentials must not be redistributed."
            ),
        )

    def _credential_mode(self) -> str:
        config = self._options
        if self._environ.get(config.access_token_env, "").strip():
            return "access_token"
        username = self._environ.get(config.username_env, "").strip()
        password = self._environ.get(config.password_env, "")
        if username and password:
            return "oauth_password_grant"
        raise AcledAuthenticationError(
            "ACLED credentials are not configured: set the access-token environment variable "
            "or both the username and password environment variables named in source config"
        )

    def _access_token(self) -> str:
        config = self._options
        mode = self._credential_mode()
        if mode == "access_token":
            return self._environ[config.access_token_env].strip()
        payload = self._http.post_form(
            self.token_url,
            {
                "username": self._environ[config.username_env].strip(),
                "password": self._environ[config.password_env],
                "grant_type": "password",
                "client_id": "acled",
                "scope": "authenticated",
            },
            headers={"Accept": "application/json"},
        )
        return parse_token_response(payload)

    def plan(self, window: FetchWindow) -> dict[str, Any]:
        plan = super().plan(window)
        plan.update(
            {
                "base_url": self.base_url,
                "token_url": self.token_url,
                "credential_mode": self._credential_mode(),
                "credentials": "<redacted>",
                "pagination": "cursor",
                "page_size": self.page_size,
                "max_pages": self.max_pages,
                "countries": list(self.countries),
                "event_types": list(self.event_types),
                "requested_fields": list(REQUESTED_FIELDS),
                "availability_field": "timestamp",
                "proxy": self._options.proxy
                or ("<environment>" if self._options.trust_env else "<none>"),
            }
        )
        return plan

    @staticmethod
    def _unix_bounds(window: FetchWindow) -> tuple[int, int]:
        # ACLED timestamps have one-second resolution and its range syntax is
        # inclusive.  This is the smallest inclusive integer range covering the
        # half-open request; exact membership is checked again client-side.
        return int(window.start.timestamp()), ceil(window.end.timestamp()) - 1

    def page_url(self, window: FetchWindow, cursor: str) -> str:
        lower, upper = self._unix_bounds(window)
        params: list[tuple[str, str]] = [
            ("_format", "json"),
            ("timestamp", f"{lower}..{upper}"),
            ("cursor", cursor),
            ("limit", str(self.page_size)),
            ("with_total", "true"),
            ("fields", "|".join(REQUESTED_FIELDS)),
        ]
        if self.countries:
            params.append(("country", "|".join(self.countries)))
        if self.event_types:
            params.append(("event_type", "|".join(self.event_types)))
        return f"{self.base_url}?{urlencode(params)}"

    def fetch(self, window: FetchWindow) -> Iterator[RawItem]:
        token = self._access_token()
        headers = {"Authorization": f"Bearer {token}", "Accept": "application/json"}
        cursor = "0"
        seen_cursors = {cursor}
        seen_ids: set[str] = set()
        expected_total: int | None = None
        expected_restrictions: bytes | None = None
        received = 0
        collected: list[RawItem] = []

        for _page_number in range(1, self.max_pages + 1):
            url = self.page_url(window, cursor)
            page = parse_envelope(self._http.get(url, headers=headers))
            if expected_total is None:
                expected_total = page.total_count
            elif page.total_count != expected_total:
                raise AcledIncompleteIngestError(
                    f"total_count changed from {expected_total} to {page.total_count}"
                )
            restrictions = canonical_bytes(page.restrictions)
            if expected_restrictions is None:
                expected_restrictions = restrictions
            elif restrictions != expected_restrictions:
                raise AcledIncompleteIngestError("data_query_restrictions changed during walk")
            if not page.items and page.next_cursor is not None:
                raise AcledIncompleteIngestError("empty page carried a non-null next_cursor")

            received += page.count
            if expected_total is not None and received > expected_total:
                raise AcledIncompleteIngestError("cursor pages contain more rows than total_count")
            for item in page.items:
                event_id, _, availability = _validate_item(item)
                if event_id in seen_ids:
                    raise AcledIncompleteIngestError(f"duplicate event id across pages: {event_id}")
                seen_ids.add(event_id)
                if window.contains(availability):
                    collected.append(self._to_item(item, availability, url, page.restrictions))

            if page.next_cursor is None:
                if expected_total is None or received != expected_total:
                    raise AcledIncompleteIngestError(
                        f"terminal cursor after {received} rows, expected {expected_total}"
                    )
                break
            if page.next_cursor in seen_cursors:
                raise AcledIncompleteIngestError(f"cursor cycle detected: {page.next_cursor}")
            seen_cursors.add(page.next_cursor)
            cursor = page.next_cursor
        else:
            raise AcledIncompleteIngestError(
                f"max_pages={self.max_pages} reached before next_cursor became null"
            )

        yield from collected

    def _to_item(
        self,
        item: dict[str, Any],
        availability: datetime,
        request_url: str,
        restrictions: dict[str, Any],
    ) -> RawItem:
        _, event_date, _ = _validate_item(item)
        payload = {
            "source": "acled",
            "api_contract_verified_on": CONTRACT_VERIFIED_ON,
            "data_query_restrictions": restrictions,
            "event": item,
        }
        return RawItem(
            payload=canonical_bytes(payload),
            first_observed_at=availability,
            modality=Modality.TABULAR,
            published_at=availability,
            claimed_event_time=event_date,
            uri=request_url,
            language="en",
            licence=LICENCE,
            source_version=f"acled-api-contract-{CONTRACT_VERIFIED_ON}",
            metadata={
                "event_id_cnty": item["event_id_cnty"],
                "time_precision": item["time_precision"],
                "geo_precision": item["geo_precision"],
                "api_timestamp": item["timestamp"],
            },
        )
