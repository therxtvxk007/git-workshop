"""Strict connector for one configured data.gov.in resource.

The selected Phase 1C profile is a retrospective government aggregate.  Its
rows are contextual/base-rate evidence, not event reports.  The portal exposes
only date-precision publication/update metadata for that resource, so the
profile records those raw dates and an explicit conservative ``available_at``
instant.  No row is back-dated to the year it summarizes.

Offset pagination cannot provide a transactional snapshot while a source table
is changing.  This connector detects total changes, duplicate rows, gaps and
premature safety bounds, but cannot prove the absence of an offset-shift
omission.  That residual risk is documented rather than hidden.
"""

from __future__ import annotations

import json
import os
from collections.abc import Callable, Iterable, Mapping
from datetime import UTC, datetime
from typing import Any, Final
from urllib.parse import urlencode

from pramaanx.config import DataGovInSourceConfig, Settings
from pramaanx.hashing import canonical_bytes, hash_object, stable_id
from pramaanx.ingest.base import (
    Connector,
    ConnectorError,
    FetchWindow,
    RawItem,
    register_connector,
)
from pramaanx.ingest.http import HttpClient, HttpFetchError, sanitize_error_text
from pramaanx.schemas.observation import Modality, SourceRecord

API_KEY_ENV: Final = "PRAMAANX_DATA_GOV_IN_API_KEY"
API_KEY_PARAMETER: Final = "api-key"
SECRET_QUERY_PARAMETERS: Final = frozenset({API_KEY_PARAMETER})
SOURCE_VERSION: Final = "data-gov-in-resource-api@2026-08-26"

API_CONTRACT: Final[dict[str, Any]] = {
    "verified_against_current_official_docs": True,
    "verified_at": "2026-08-26",
    "genuinely_live_api_verified": True,
    "live_verified_at": "2026-08-27",
    "live_verification_scope": (
        "selected resource; raw first page plus forced multi-page terminal traversal"
    ),
    "resource_api": "https://api.data.gov.in/resource/{resource_id}",
    "auth": {"location": "query", "parameter": API_KEY_PARAMETER},
    "format": "json",
    "pagination": {
        "kind": "offset_limit",
        "fields": ["offset", "limit"],
        "response_echo_encoding": "integer_or_canonical_decimal_string",
        "live_observation": {
            "limit": "canonical_decimal_string",
            "offset": "accepted_across_forced_multi_page_traversal",
        },
    },
    "required_envelope_fields": ["status", "total", "count", "limit", "offset", "records"],
    "success_status": "ok",
    "instant_mapping": {
        "published_at": "null when portal metadata has date precision only",
        "first_observed_at": "profile.available_at",
        "claimed_event_time": "configured timezone-aware record field or null",
        "retrieved_at": "ledger clock",
    },
    "official_sources": [
        "https://www.data.gov.in/apis",
        "https://www.data.gov.in/help",
        "https://www.data.gov.in/terms-of-use",
        "https://www.data.gov.in/government-open-data-license-india",
    ],
}

PageFetcher = Callable[[str], bytes]


class DataGovInCredentialError(ConnectorError):
    """The environment-only API credential is absent."""


class DataGovInContractError(ConnectorError):
    """A response cannot prove a complete, internally consistent traversal."""


def _strict_nonnegative_int(value: Any, *, field: str) -> int:
    if isinstance(value, bool) or not isinstance(value, int) or value < 0:
        raise DataGovInContractError(f"{field} must be a non-negative integer, not {value!r}")
    return value


def _pagination_echo_int(value: Any, *, field: str) -> int:
    """Normalize only the two request-echo fields without weakening counts."""
    if isinstance(value, bool):
        raise DataGovInContractError(
            f"{field} must be a non-negative integer or canonical decimal string, not {value!r}"
        )
    if isinstance(value, int):
        if value >= 0:
            return value
    elif (
        isinstance(value, str)
        and 1 <= len(value) <= 20
        and value.isascii()
        and value.isdecimal()
        and (value == "0" or not value.startswith("0"))
    ):
        return int(value)
    raise DataGovInContractError(
        f"{field} must be a non-negative integer or canonical decimal string, not {value!r}"
    )


def _parse_claimed_instant(value: Any, *, field: str) -> datetime:
    if not isinstance(value, str) or not value.strip():
        raise DataGovInContractError(f"record field {field!r} must be a non-blank timestamp")
    try:
        parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError as error:
        raise DataGovInContractError(
            f"record field {field!r} is not a valid ISO-8601 timestamp"
        ) from error
    if parsed.tzinfo is None:
        raise DataGovInContractError(f"record field {field!r} must include a timezone")
    return parsed.astimezone(UTC)


def parse_envelope(
    payload: bytes,
    *,
    expected_offset: int,
    expected_limit: int,
    expected_total: int | None,
) -> tuple[list[dict[str, Any]], int]:
    """Parse one page without permissive fallbacks for pagination metadata."""

    def object_without_duplicate_keys(pairs: list[tuple[str, Any]]) -> dict[str, Any]:
        result: dict[str, Any] = {}
        for key, value in pairs:
            if key in result:
                raise DataGovInContractError(f"response contains duplicate JSON key {key!r}")
            result[key] = value
        return result

    def reject_nonfinite(value: str) -> Any:
        raise DataGovInContractError(f"response contains non-finite JSON number {value}")

    try:
        envelope = json.loads(
            payload,
            object_pairs_hook=object_without_duplicate_keys,
            parse_constant=reject_nonfinite,
        )
    except (UnicodeDecodeError, json.JSONDecodeError) as error:
        raise DataGovInContractError("data.gov.in response is not valid UTF-8 JSON") from error
    if not isinstance(envelope, dict):
        raise DataGovInContractError("data.gov.in response must be a JSON object")

    required = set(API_CONTRACT["required_envelope_fields"])
    missing = sorted(required - set(envelope))
    if missing:
        raise DataGovInContractError(f"response is missing required fields: {missing}")
    if envelope["status"] != API_CONTRACT["success_status"]:
        raise DataGovInContractError(
            f"response status is not {API_CONTRACT['success_status']!r}: {envelope['status']!r}"
        )

    total = _strict_nonnegative_int(envelope["total"], field="total")
    count = _strict_nonnegative_int(envelope["count"], field="count")
    # The live API represents pagination request echoes as JSON strings on at
    # least some resources. Normalize that semantically exact representation,
    # while keeping authoritative total/count fields strict JSON integers.
    limit = _pagination_echo_int(envelope["limit"], field="limit")
    offset = _pagination_echo_int(envelope["offset"], field="offset")
    records = envelope["records"]
    if not isinstance(records, list):
        raise DataGovInContractError("records must be a list")
    if any(not isinstance(record, dict) for record in records):
        raise DataGovInContractError("every records entry must be an object")
    if count != len(records):
        raise DataGovInContractError(f"count {count} does not equal records length {len(records)}")
    if offset != expected_offset or limit != expected_limit:
        raise DataGovInContractError(
            f"pagination echo changed: requested offset={expected_offset}, limit={expected_limit}; "
            f"received offset={offset}, limit={limit}"
        )
    if count > limit:
        raise DataGovInContractError(f"count {count} exceeds page limit {limit}")
    if offset + count > total:
        raise DataGovInContractError(f"offset + count ({offset + count}) exceeds total {total}")
    if expected_total is not None and total != expected_total:
        raise DataGovInContractError(f"total changed during traversal: {expected_total} -> {total}")
    if count == 0 and offset < total:
        raise DataGovInContractError("empty page arrived before the reported total was reached")
    return records, total


@register_connector
class DataGovInConnector(Connector):
    """Ingest one strictly profiled data.gov.in table into bronze."""

    source_id = "data_gov_in"
    tier = 0

    def __init__(
        self,
        settings: Settings,
        options: DataGovInSourceConfig | Mapping[str, Any] | None = None,
        *,
        fetcher: PageFetcher | None = None,
        environ: Mapping[str, str] | None = None,
    ) -> None:
        super().__init__(settings, options)
        self._environ = os.environ if environ is None else environ
        self._api_key = self._environ.get(API_KEY_ENV, "").strip()
        self._fetcher = fetcher or self._default_fetcher()

    @property
    def _options(self) -> DataGovInSourceConfig:
        assert isinstance(self.options, DataGovInSourceConfig)
        return self.options

    def _default_fetcher(self) -> PageFetcher:
        config = self._options
        cache_dir = self.settings.storage.data_root / "http_cache" / self.source_id
        client = HttpClient(
            cache_dir=cache_dir if config.cache else None,
            timeout_seconds=config.timeout_seconds,
            max_attempts=config.max_attempts,
            backoff_seconds=config.backoff_seconds,
            max_retry_after_seconds=config.max_retry_after_seconds,
            proxy=config.proxy,
            trust_env=config.trust_env,
            ca_bundle=config.ca_bundle,
            verify=config.verify,
        )
        return lambda url: client.get(
            url,
            secret_query_parameters=SECRET_QUERY_PARAMETERS,
            accepted_content_types=frozenset({"application/json"}),
        )

    def _validate_operational_config(self) -> None:
        config = self._options
        if not config.resource_id:
            raise DataGovInContractError("data_gov_in resource_id is not configured")
        if config.available_at is None:
            raise DataGovInContractError(
                "data_gov_in available_at is required; do not infer availability from row dates"
            )
        if not self._api_key:
            raise DataGovInCredentialError(
                f"{API_KEY_ENV} is required (the value is environment-only and was not logged)"
            )
        dated_metadata = [
            value
            for value in (config.portal_published_date, config.portal_updated_date)
            if value is not None
        ]
        if dated_metadata and config.available_at.date() < max(dated_metadata):
            raise DataGovInContractError(
                "available_at cannot precede portal publication/update metadata"
            )

    def _profile_source_version(self) -> str:
        config = self._options
        updated = (
            config.portal_updated_date.isoformat() if config.portal_updated_date else "unknown"
        )
        available = (
            config.available_at.astimezone(UTC).isoformat()
            if config.available_at is not None
            else "unconfigured"
        )
        return (
            f"{SOURCE_VERSION}:{config.resource_id or 'unconfigured'}:"
            f"updated-{updated}:available-{available}"
        )

    @property
    def source_record(self) -> SourceRecord:
        config = self._options
        return SourceRecord(
            source_id=self.source_id,
            source_type="government_aggregate",
            display_name=f"data.gov.in — {config.resource_title}",
            tier=self.tier,
            licence=config.licence,
            licence_url=config.licence_url,
            redistributable=config.redistributable,
            base_url=config.resource_page_url,
            source_version=self._profile_source_version(),
            reliability_prior=0.65,
            notes=(
                "Official retrospective aggregate; contextual/base-rate use only. "
                "Portal accuracy and currency are not guaranteed; verify against the "
                "publishing department. Raw redistribution remains disabled pending review."
            ),
        )

    def plan(self, window: FetchWindow) -> dict[str, Any]:
        self._validate_operational_config()
        config = self._options
        available_at = config.available_at
        assert available_at is not None
        return {
            "source_id": self.source_id,
            "tier": self.tier,
            "window_start": window.start.isoformat(),
            "window_end": window.end.isoformat(),
            "window_days": round(window.days, 4),
            "resource_id": config.resource_id,
            "resource_title": config.resource_title,
            "profile_role": config.profile_role,
            "available_at": available_at.astimezone(UTC).isoformat(),
            "would_fetch": window.contains(available_at.astimezone(UTC)),
            "page_size": config.page_size,
            "max_pages": config.max_pages,
            "max_items": config.max_items,
            "api_key": {"configured": True, "source": API_KEY_ENV},
            "proxy": "<configured>"
            if config.proxy
            else ("<environment>" if config.trust_env else "<none>"),
            "implemented": True,
        }

    def page_url(self, *, offset: int) -> str:
        self._validate_operational_config()
        config = self._options
        query = urlencode(
            [
                (API_KEY_PARAMETER, self._api_key),
                ("format", "json"),
                ("offset", str(offset)),
                ("limit", str(config.page_size)),
            ]
        )
        return f"{config.base_url}/{config.resource_id}?{query}"

    def fetch(self, window: FetchWindow) -> Iterable[RawItem]:
        self._validate_operational_config()
        config = self._options
        available_at = config.available_at
        assert available_at is not None
        available_at = available_at.astimezone(UTC)
        if not window.contains(available_at):
            return []

        rows: list[tuple[str, dict[str, Any]]] = []
        seen: set[str] = set()
        expected_total: int | None = None
        offset = 0
        for page_number in range(1, config.max_pages + 1):
            url = self.page_url(offset=offset)
            try:
                payload = self._fetcher(url)
            except Exception as error:
                # Shared HTTP failures are already sanitized and carry the
                # operator-relevant distinction between origin refusal and
                # proxy policy. Preserve those subclasses across the connector
                # boundary; only unknown injected/transport exceptions need
                # conversion and URL-secret scrubbing here.
                if isinstance(error, (ConnectorError, HttpFetchError)):
                    raise
                safe = sanitize_error_text(str(error), url, SECRET_QUERY_PARAMETERS)
                raise ConnectorError(f"data.gov.in request failed: {safe}") from None
            records, total = parse_envelope(
                payload,
                expected_offset=offset,
                expected_limit=config.page_size,
                expected_total=expected_total,
            )
            expected_total = total
            if total > config.max_items:
                raise DataGovInContractError(
                    f"reported total {total} exceeds max_items {config.max_items}; "
                    "refusing a silently truncated traversal"
                )
            for record in records:
                row_id = self._record_id(record)
                if row_id in seen:
                    raise DataGovInContractError(
                        f"duplicate stable record id across pages: {row_id}"
                    )
                seen.add(row_id)
                rows.append((row_id, record))
            offset += len(records)
            if offset == total:
                break
            if page_number == config.max_pages:
                raise DataGovInContractError(
                    f"max_pages {config.max_pages} reached before total {total}; "
                    "no partial result was emitted"
                )
        else:  # pragma: no cover - loop always exits or raises at its bound
            raise DataGovInContractError("pagination ended without a verified terminal page")

        return [self._to_item(row_id, record, available_at) for row_id, record in sorted(rows)]

    def _record_id(self, record: dict[str, Any]) -> str:
        config = self._options
        if not config.stable_id_fields:
            return stable_id("dgi", config.resource_id, hash_object(record))
        components: list[str] = []
        for field in config.stable_id_fields:
            value = record.get(field)
            if value is None or isinstance(value, (dict, list, bool)) or not str(value).strip():
                raise DataGovInContractError(
                    f"stable ID field {field!r} is missing, blank, or non-scalar"
                )
            components.append(str(value).strip())
        return stable_id("dgi", config.resource_id, *components)

    def _to_item(self, row_id: str, record: dict[str, Any], available_at: datetime) -> RawItem:
        config = self._options
        claimed = None
        if config.claimed_event_time_field is not None:
            claimed = _parse_claimed_instant(
                record.get(config.claimed_event_time_field),
                field=config.claimed_event_time_field,
            )
        payload = canonical_bytes(
            {
                "source": self.source_id,
                "source_version": self._profile_source_version(),
                "resource": {
                    "id": config.resource_id,
                    "title": config.resource_title,
                    "organization": config.organization,
                    "sector": config.sector,
                    "update_frequency": config.update_frequency,
                    "profile_role": config.profile_role,
                    "portal_published_date": (
                        config.portal_published_date.isoformat()
                        if config.portal_published_date
                        else None
                    ),
                    "portal_updated_date": (
                        config.portal_updated_date.isoformat()
                        if config.portal_updated_date
                        else None
                    ),
                    "available_at": available_at.isoformat(),
                },
                "record_id": row_id,
                "record": record,
            }
        )
        return RawItem(
            payload=payload,
            first_observed_at=available_at,
            modality=Modality.TABULAR,
            # The portal exposes only a date for this profile. Do not fabricate
            # a midnight publication instant from it.
            published_at=None,
            claimed_event_time=claimed,
            uri=config.resource_page_url,
            language="en",
            licence=config.licence,
            source_version=self._profile_source_version(),
            metadata={"resource_id": config.resource_id, "record_id": row_id},
        )
