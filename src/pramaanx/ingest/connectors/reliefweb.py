"""ReliefWeb API connector (Tier 0).

ReliefWeb is OCHA's humanitarian information service: situation reports,
assessments and appeals posted by relief organisations. It is a Tier-0 source
because it needs no credential -- only that callers identify themselves -- and
because its posting timestamps make honest point-in-time reconstruction
possible in a way most news archives do not.

Temporal semantics
------------------
Four distinct instants exist for a ReliefWeb report, and conflating any two of
them produces a leak:

===================== =========================================================
``date.created``      When ReliefWeb first posted the report. Publication.
``date.changed``      When the record was last modified on ReliefWeb.
``date.original``     The document's own publication date, as its author
                      published it -- often earlier than ``date.created``.
retrieval             When this project fetched it. Recorded by the ledger,
                      never used for admission.
===================== =========================================================

The availability rule, which :func:`availability_of` implements and
``tests/unit/test_reliefweb_connector.py`` pins:

    first_observed_at = max(date.created, date.changed)

Not ``date.created``, and never ``date.original``. The API serves only the
*current* version of a record -- there is no version-history endpoint and no
way to ask what a report said last year. So the body in hand is the revised
body, and the earliest moment this project could honestly claim to have had
*this* text is the moment it was last revised. A report created in 2020 and
edited in 2026 enters a 2026 snapshot, not a 2020 one.

That is deliberately conservative: it withholds evidence from early cutoffs
that a contemporaneous reader might really have had, in exchange for never
attributing to an early cutoff a sentence written later. For a system whose
entire claim rests on not seeing the future, that is the right direction to
err. A future connector could recover the earlier text from an external
archive; until one does, this is the honest bound.

``claimed_event_time`` is left unset. A report's metadata carries publication
dates, not the date of the situation it describes, and deriving an event time
from a publication date would be inventing one.

API contract
------------
Everything this connector assumes about the wire format lives in
:data:`API_CONTRACT` and the parsing below, in one place, because it could not
be checked against the official documentation when it was written -- the
development environment had no route to ``reliefweb.int``. Treat the field
paths as *asserted, not verified*: ``tests/network/test_reliefweb_live.py``
checks them against the real service and is the thing that turns the assertion
into a fact. Parsing fails loudly on an unexpected shape rather than returning
an empty page, so a contract drift shows up as an error and not as a quiet
gap in the ledger.
"""

from __future__ import annotations

import json
import os
from collections.abc import Iterator, Mapping
from datetime import UTC, datetime
from typing import Any
from urllib.parse import urlencode

from pramaanx.config import ReliefWebSourceConfig, Settings
from pramaanx.hashing import canonical_bytes
from pramaanx.ingest.base import (
    Connector,
    ConnectorError,
    FetchWindow,
    RawItem,
    register_connector,
)
from pramaanx.ingest.http import Fetcher, HttpClient
from pramaanx.logging import get_logger
from pramaanx.schemas.observation import Modality, SourceRecord

log = get_logger(__name__)

APPNAME_ENV = "PRAMAANX_RELIEFWEB_APPNAME"

#: What this connector believes about the ReliefWeb API. Asserted from prior
#: knowledge of the service, NOT verified against the official documentation --
#: see the module docstring. The live test checks every entry here.
API_CONTRACT: dict[str, Any] = {
    "verified_against_official_docs": False,
    "verification_route": "tests/network/test_reliefweb_live.py",
    "endpoint": "{base_url}/reports",
    "required_query_params": ["appname"],
    "pagination": {"style": "offset", "params": ["limit", "offset"], "total_key": "totalCount"},
    "envelope_keys": ["data", "totalCount"],
    "item_keys": ["id", "fields"],
    "date_fields": {
        "created": "fields.date.created",
        "changed": "fields.date.changed",
        "original": "fields.date.original",
    },
    "availability_rule": "max(date.created, date.changed)",
    "sort": ["date.changed:asc", "id:asc"],
}

#: Fields requested from the API. Kept explicit so a response carrying more
#: than this cannot silently widen what enters bronze.
REQUESTED_FIELDS: tuple[str, ...] = (
    "id",
    "title",
    "body",
    "url",
    "origin",
    "date.created",
    "date.changed",
    "date.original",
    "language.code",
    "language.name",
    "source.name",
    "source.shortname",
    "country.iso3",
    "country.name",
    "primary_country.iso3",
    "disaster.name",
    "disaster_type.name",
    "format.name",
    "theme.name",
)

#: ReliefWeb's terms require attribution and forbid wholesale redistribution;
#: individual documents carry their contributing organisation's own terms.
LICENCE = "ReliefWeb terms of service (attribution required; per-document terms apply)"
LICENCE_URL = "https://reliefweb.int/terms-conditions"


class ReliefWebContractError(ConnectorError):
    """The API returned a shape this connector does not understand.

    Raised rather than skipped. An unrecognised envelope means the assumptions
    in :data:`API_CONTRACT` have drifted, and continuing would write a silent
    gap into an append-only ledger that later looks like a quiet news week.
    """


def _iso(value: datetime) -> str:
    return value.astimezone(UTC).strftime("%Y-%m-%dT%H:%M:%S+00:00")


def parse_api_datetime(value: Any, *, field: str) -> datetime:
    """Parse a ReliefWeb timestamp into an aware UTC datetime."""
    if not isinstance(value, str) or not value.strip():
        raise ReliefWebContractError(f"{field} is missing or not a string: {value!r}")
    try:
        parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError as error:
        raise ReliefWebContractError(f"{field} is not an ISO-8601 instant: {value!r}") from error
    # ReliefWeb returns offsets; a bare local time would be ambiguous, and
    # guessing UTC for it is how an hour of leakage gets in.
    if parsed.tzinfo is None:
        raise ReliefWebContractError(f"{field} has no timezone offset: {value!r}")
    return parsed.astimezone(UTC)


def availability_of(dates: Mapping[str, Any]) -> datetime:
    """The instant this representation became available.

    ``max(created, changed)``. See the module docstring for why the maximum and
    not the minimum, and why never ``original``.
    """
    created = parse_api_datetime(dates.get("created"), field="date.created")
    raw_changed = dates.get("changed")
    if raw_changed is None:
        # Treat an absent changed as "never revised". Defensive: the API is
        # expected to always set it.
        return created
    changed = parse_api_datetime(raw_changed, field="date.changed")
    return max(created, changed)


@register_connector
class ReliefWebConnector(Connector):
    """Ingests ReliefWeb reports into bronze, ordered and deduplicated."""

    source_id = "reliefweb"
    tier = 0

    def __init__(
        self,
        settings: Settings,
        options: ReliefWebSourceConfig | Mapping[str, Any] | None = None,
        fetcher: Fetcher | None = None,
    ) -> None:
        super().__init__(settings, options)
        self._explicit_fetcher = fetcher
        self._client: HttpClient | None = None

    @property
    def _options(self) -> ReliefWebSourceConfig:
        assert isinstance(self.options, ReliefWebSourceConfig)
        return self.options

    # -- identity ---------------------------------------------------------
    def appname(self) -> str:
        """The identity ReliefWeb requires of every caller.

        Config first, environment second. Absent both, this is an error and not
        a default: calling an API anonymously that asks you not to is a decision
        nobody should make by omission.
        """
        configured = (self._options.appname or "").strip()
        if configured:
            return configured
        from_env = os.environ.get(APPNAME_ENV, "").strip()
        if from_env:
            return from_env
        raise ConnectorError(
            "ReliefWeb requires callers to identify themselves. Set "
            f"{APPNAME_ENV} in the environment (see .env.example) or "
            "sources.reliefweb.appname in the configuration."
        )

    @property
    def source_record(self) -> SourceRecord:
        return SourceRecord(
            source_id=self.source_id,
            source_type="humanitarian_reporting",
            display_name="ReliefWeb (OCHA)",
            tier=0,
            licence=LICENCE,
            licence_url=LICENCE_URL,
            redistributable=False,
            base_url=self._options.base_url,
            source_version=f"reliefweb-v1-{self._options.endpoint}",
            reliability_prior=0.75,
            notes=(
                "Curated humanitarian reporting from relief organisations. Coverage is "
                "response-driven: a crisis with no operational response is under-reported "
                "regardless of severity. first_observed_at is max(date.created, "
                "date.changed) because the API serves only the current revision."
            ),
        )

    # -- request building --------------------------------------------------
    def _client_for(self) -> Fetcher:
        if self._explicit_fetcher is not None:
            return self._explicit_fetcher
        if self._client is None:
            config = self._options
            cache_dir = self.settings.storage.data_root / "http_cache" / self.source_id
            self._client = HttpClient(
                cache_dir=cache_dir if config.cache else None,
                timeout_seconds=config.timeout_seconds,
                max_attempts=config.max_attempts,
                backoff_seconds=config.backoff_seconds,
                min_interval_seconds=config.min_interval_seconds,
                proxy=config.proxy,
                trust_env=config.trust_env,
                ca_bundle=config.ca_bundle,
                verify=config.verify,
            )
        return self._client.get

    def build_url(self, window: FetchWindow, *, offset: int) -> str:
        """One page request.

        Filtering is on ``date.changed`` because that is what availability
        tracks. The window is applied again client-side, because the API's range
        bounds are inclusive while a :class:`FetchWindow` is half-open.
        """
        config = self._options
        params: list[tuple[str, str]] = [
            ("appname", self.appname()),
            ("limit", str(config.page_size)),
            ("offset", str(offset)),
            ("profile", "list"),
        ]
        params += [("fields[include][]", name) for name in REQUESTED_FIELDS]
        # A total order, so paging is stable even when many records share a
        # timestamp. Without the id tiebreaker a page boundary can drop or
        # repeat records.
        params += [("sort[]", "date.changed:asc"), ("sort[]", "id:asc")]

        index = 0
        params += [
            (f"filter[conditions][{index}][field]", "date.changed"),
            (f"filter[conditions][{index}][value][from]", _iso(window.start)),
            (f"filter[conditions][{index}][value][to]", _iso(window.end)),
        ]
        for values, field in (
            (config.languages, "language.code"),
            (config.countries, "country.iso3"),
            (config.disaster_types, "disaster_type.name"),
            (config.formats, "format.name"),
        ):
            if not values:
                continue
            index += 1
            params.append((f"filter[conditions][{index}][field]", field))
            params += [(f"filter[conditions][{index}][value][]", value) for value in values]
        if index:
            params.append(("filter[operator]", "AND"))

        return f"{config.base_url.rstrip('/')}/{config.endpoint}?{urlencode(params)}"

    # -- response parsing --------------------------------------------------
    @staticmethod
    def parse_envelope(payload: bytes, *, url: str) -> tuple[list[dict[str, Any]], int]:
        """Split a response into its items and the reported total."""
        try:
            document = json.loads(payload)
        except json.JSONDecodeError as error:
            raise ReliefWebContractError(f"{url} returned a non-JSON body: {error}") from error
        if not isinstance(document, dict):
            raise ReliefWebContractError(f"{url} returned {type(document).__name__}, not an object")
        if "error" in document:
            raise ReliefWebContractError(f"{url} returned an API error: {document['error']!r}")
        data = document.get("data")
        if not isinstance(data, list):
            raise ReliefWebContractError(
                f"{url} has no 'data' list; the API contract in API_CONTRACT has drifted "
                f"(keys present: {sorted(document)})"
            )
        total = document.get("totalCount", document.get("count", len(data)))
        if not isinstance(total, int):
            raise ReliefWebContractError(f"{url} reported a non-integer totalCount: {total!r}")
        return data, total

    def _to_item(self, entry: Mapping[str, Any], *, url: str) -> RawItem:
        if not isinstance(entry.get("fields"), dict):
            raise ReliefWebContractError(f"{url}: item has no 'fields' object: {entry!r}")
        fields: dict[str, Any] = dict(entry["fields"])
        identifier = entry.get("id", fields.get("id"))
        if identifier is None:
            raise ReliefWebContractError(f"{url}: item has no id: {entry!r}")

        dates = fields.get("date")
        if not isinstance(dates, dict):
            raise ReliefWebContractError(f"{url}: report {identifier} has no date object")
        available_at = availability_of(dates)
        created = parse_api_datetime(dates.get("created"), field="date.created")
        original = (
            parse_api_datetime(dates["original"], field="date.original")
            if dates.get("original")
            else None
        )

        # The payload is the API record plus the provenance needed to interpret
        # it, canonically serialised so identical records hash identically.
        payload = canonical_bytes(
            {
                "source": "reliefweb",
                "api_version": "v1",
                "endpoint": self._options.endpoint,
                "report_id": str(identifier),
                "request_url": _redact_appname(url),
                "availability_basis": API_CONTRACT["availability_rule"],
                "fields": fields,
            }
        )
        return RawItem(
            payload=payload,
            # Availability, never the document's own publication date.
            first_observed_at=available_at,
            modality=Modality.TEXT,
            # The earliest publication claim: the author's own date when it
            # exists, otherwise the ReliefWeb posting.
            published_at=min(original, created) if original else created,
            # ReliefWeb report metadata carries publication dates, not the date
            # of the situation described. Deriving an event time from a
            # publication date would be inventing one.
            claimed_event_time=None,
            uri=_first_url(fields),
            language=_primary_language(fields),
            licence=LICENCE,
            source_version=f"reliefweb-v1-{self._options.endpoint}",
            metadata={
                "report_id": str(identifier),
                "date_created": _iso(created),
                "date_changed": _iso(available_at),
                "date_original": _iso(original) if original else None,
                "revised_after_publication": available_at > created,
            },
        )

    # -- connector API -----------------------------------------------------
    def plan(self, window: FetchWindow) -> dict[str, Any]:
        """Describe the fetch without performing it. Makes no request."""
        plan = super().plan(window)
        config = self._options
        # The appname is resolved for the plan so that a missing identity fails
        # during --dry-run rather than on the first real request.
        plan.update(
            {
                "endpoint": f"{config.base_url.rstrip('/')}/{config.endpoint}",
                "appname": self.appname(),
                "appname_source": "config" if config.appname else APPNAME_ENV,
                "page_size": config.page_size,
                "max_pages": config.max_pages,
                "max_items": config.max_items or None,
                "availability_rule": API_CONTRACT["availability_rule"],
                "filters": {
                    "languages": config.languages,
                    "countries": config.countries,
                    "disaster_types": config.disaster_types,
                    "formats": config.formats,
                },
                "first_request_url": _redact_appname(self.build_url(window, offset=0)),
                "api_contract_verified_against_official_docs": API_CONTRACT[
                    "verified_against_official_docs"
                ],
            }
        )
        plan["options"].pop("appname", None)
        return plan

    def fetch(self, window: FetchWindow) -> Iterator[RawItem]:
        config = self._options
        fetcher = self._client_for()
        seen: set[str] = set()
        emitted = 0
        offset = 0

        for page in range(1, config.max_pages + 1):
            url = self.build_url(window, offset=offset)
            payload = fetcher(url)
            entries, total = self.parse_envelope(payload, url=url)
            if not entries:
                break

            fresh = 0
            for entry in entries:
                item = self._to_item(entry, url=url)
                identifier = str(item.metadata["report_id"])
                # The same record can surface on two pages when the underlying
                # index shifts mid-pagination. Deduplicating on report id keeps
                # bronze from carrying the same evidence twice under two hashes.
                if identifier in seen:
                    log.debug("reliefweb.duplicate_skipped", report_id=identifier, page=page)
                    continue
                seen.add(identifier)
                fresh += 1
                # The API's range bounds are inclusive; the window is half-open.
                if not window.contains(item.first_observed_at):
                    continue
                yield item
                emitted += 1
                if config.max_items and emitted >= config.max_items:
                    log.info("reliefweb.max_items_reached", emitted=emitted)
                    return

            offset += len(entries)
            log.debug("reliefweb.page", page=page, entries=len(entries), fresh=fresh, total=total)
            if offset >= total:
                break
        else:
            log.warning(
                "reliefweb.max_pages_reached",
                max_pages=config.max_pages,
                note="the window may be incompletely ingested; narrow it or raise max_pages",
            )

        log.info("reliefweb.fetch_complete", emitted=emitted, unique_records=len(seen))


def _redact_appname(url: str) -> str:
    """Strip the caller identity out of anything that gets persisted or logged."""
    import re

    return re.sub(r"appname=[^&]*", "appname=REDACTED", url)


def _first_url(fields: Mapping[str, Any]) -> str | None:
    for key in ("url", "origin"):
        value = fields.get(key)
        if isinstance(value, str) and value.startswith(("http://", "https://")):
            return value
    return None


def _primary_language(fields: Mapping[str, Any]) -> str | None:
    languages = fields.get("language")
    if isinstance(languages, list):
        for entry in languages:
            if isinstance(entry, dict) and isinstance(entry.get("code"), str):
                return str(entry["code"]).lower()
    if isinstance(languages, dict) and isinstance(languages.get("code"), str):
        return str(languages["code"]).lower()
    return None
