"""ReliefWeb API connector (Tier 0).

ReliefWeb is OCHA's humanitarian information service: situation reports,
assessments and appeals posted by relief organisations. It is a Tier-0 source
because it needs no credential -- only that callers identify themselves with an
appname ReliefWeb has approved -- and because its posting timestamps make honest
point-in-time reconstruction possible in a way most news archives do not.

Temporal semantics
------------------
Four distinct instants exist for a ReliefWeb report, and conflating any two of
them produces a leak. All four are preserved separately; none is ever
substituted for another:

===================== =========================================================
``date.created``      When ReliefWeb first posted the report. Kept raw in
                      ``metadata.date_created``.
``date.changed``      When the record was last modified on ReliefWeb. Kept raw
                      in ``metadata.date_changed``, or ``None`` when the API
                      omits it -- never back-filled with a computed instant.
``date.original``     The document's own publication date, as its author
                      published it. Kept raw in ``metadata.date_original``.
retrieval             When this project fetched it. Recorded by the ledger,
                      never used for admission.
===================== =========================================================

From those, two derived values:

``availability``
    ``max(date.created, date.changed)`` when ``changed`` exists, otherwise
    ``date.created`` alone. This is ``first_observed_at``, the only field
    admission uses. Never ``date.original``. When ``changed`` is absent the
    connector does **not** invent a modification instant; it says so by leaving
    ``metadata.date_changed`` null and ``revised_after_creation`` false.

``published_at``
    ``date.original`` when present, otherwise ``date.created``. The earliest
    publication claim the record makes about itself, taken as stated rather
    than reconciled against ``created`` -- a document whose author dates it
    after ReliefWeb posted it is a data anomaly to surface, not to smooth over.

Why the maximum. The API serves only the *current* version of a record -- there
is no version-history endpoint and no way to ask what a report said last year.
So the body in hand is the revised body, and the earliest moment this project
could honestly claim to have had *this* text is the moment it was last revised.
A report created in 2020 and edited in 2026 enters a 2026 snapshot, not a 2020
one.

That is deliberately conservative: it withholds evidence from early cutoffs
that a contemporaneous reader might really have had, in exchange for never
attributing to an early cutoff a sentence written later. For a system whose
entire claim rests on not seeing the future, that is the right direction to
err. A future connector could recover the earlier text from an external
archive; until one does, this is the honest bound.

``claimed_event_time`` is left unset. A report's metadata carries publication
dates, not the date of the situation it describes, and deriving an event time
from a publication date would be inventing one.

Pagination and what it does not guarantee
-----------------------------------------
Paging walks ``offset`` under a total sort (``date.changed:asc``, then
``id:asc``). The total order removes one failure mode: without the ``id``
tiebreaker, records sharing a timestamp reshuffle between requests and a page
boundary silently drops or repeats them.

It does not remove the other. Offset pagination over an index that mutates
mid-walk can still **omit** records: a report revised into an earlier position
while the walk is past that offset is never seen, and no client-side check can
detect the omission -- the response is perfectly well-formed. Deduplication
handles repeats, which are visible; nothing here handles drops, which are not.

The operational answer is overlapping windows: re-ingest each window with a
margin rather than treating one pass as complete. Bronze is content-addressed
and append-only, so re-ingesting is cheap and idempotent. This limitation is
stated in :attr:`SourceRecord.notes` as well, where a modeller will read it.

API contract
------------
Everything this connector assumes about the wire format lives in
:data:`API_CONTRACT`. Those assumptions were checked against ReliefWeb's
official documentation by external review on 2026-08-26 (the exact pages are
listed in ``API_CONTRACT["official_docs"]``), which is why
``official_docs_verified`` is true.

That is not the same as having called the API. ``live_api_verified`` is
separately false: this project's development environment has no egress to
``api.reliefweb.int``, so no response from the real service has ever been
parsed here. The two statuses are kept apart on purpose --
``tests/network/test_reliefweb_live.py`` is what would flip the second, and a
skipped or blocked run of it flips nothing.

Parsing fails loudly on an unexpected shape rather than returning an empty
page, so a contract drift shows up as an error and not as a quiet gap in the
ledger.
"""

from __future__ import annotations

import json
import os
from collections.abc import Iterator, Mapping
from dataclasses import dataclass
from datetime import UTC, datetime
from typing import Any
from urllib.parse import urlencode

from pramaanx.config import RELIEFWEB_API_VERSION, ReliefWebSourceConfig, Settings
from pramaanx.hashing import canonical_bytes
from pramaanx.ingest.base import (
    Connector,
    ConnectorError,
    FetchWindow,
    RawItem,
    register_connector,
)
from pramaanx.ingest.http import Fetcher, HttpClient, redact_url
from pramaanx.logging import get_logger
from pramaanx.schemas.observation import Modality, SourceRecord

log = get_logger(__name__)

APPNAME_ENV = "PRAMAANX_RELIEFWEB_APPNAME"

#: The API version, re-exported from the single definition in
#: :mod:`pramaanx.config`. An alias, never a second literal: the URL default,
#: the payload's ``api_version``, and every ``source_version`` string are all
#: built from this one value so they cannot drift apart.
API_VERSION = RELIEFWEB_API_VERSION

#: Where a caller applies for the mandatory, pre-approved appname.
APPNAME_REQUEST_URL = "https://apidoc.reliefweb.int/parameters"

#: What a plan says instead of the caller identity. A constant marker, so a
#: reader of `--dry-run` output can tell "withheld" from "not configured".
REDACTED_APPNAME = "<redacted>"

#: The official pages this contract was read from, and when.
OFFICIAL_DOCS = (
    "https://apidoc.reliefweb.int/endpoints",
    "https://apidoc.reliefweb.int/parameters",
    "https://apidoc.reliefweb.int/result-structure",
    "https://apidoc.reliefweb.int/fields-tables",
    "https://apidoc.reliefweb.int/faq",
    "https://reliefweb.int/terms-conditions",
)
OFFICIAL_DOCS_VERIFIED_ON = "2026-08-26"

#: What this connector believes about the ReliefWeb API.
#:
#: Three statuses, deliberately separate, because collapsing them is how a
#: verification claim becomes a lie:
#:
#: ``official_docs_verified``
#:     The contract below was read from the official documentation listed in
#:     ``official_docs`` on ``official_docs_verified_on``. True.
#: ``fixture_tested``
#:     The connector's handling of this shape is exercised by hand-written
#:     synthetic fixtures. True -- and it proves logic, not the wire format.
#: ``live_api_verified``
#:     A real response from ``api.reliefweb.int`` has been fetched and parsed.
#:     **False.** A skip, a 403, an established tunnel, an empty response or a
#:     successfully constructed URL is none of them a live verification.
API_CONTRACT: dict[str, Any] = {
    "api_version": API_VERSION,
    "official_docs_verified": True,
    "official_docs_verified_on": OFFICIAL_DOCS_VERIFIED_ON,
    "official_docs": list(OFFICIAL_DOCS),
    "fixture_tested": True,
    "live_api_verified": False,
    "live_api_status": (
        "unverified: this environment's egress policy refuses CONNECT to "
        "api.reliefweb.int, so no response from the real service has been parsed"
    ),
    "verification_route": "tests/network/test_reliefweb_live.py",
    "endpoint": "{base_url}/reports",
    "required_query_params": ["appname"],
    "appname": {
        "required": True,
        "preapproved_since": "2025-11-01",
        "transmitted_in": "url",
        "request_url": APPNAME_REQUEST_URL,
    },
    "pagination": {
        "style": "offset",
        "params": ["limit", "offset"],
        "limit_bounds": [0, 1000],
        "total_key": "totalCount",
        "page_count_key": "count",
        "residual_limitation": (
            "offset pagination over a mutating index can omit records; a total sort "
            "prevents reshuffling ties, not concurrent-mutation drops"
        ),
    },
    "envelope_keys": ["data", "count", "totalCount"],
    "item_keys": ["id", "fields"],
    "item_id_type": "integer",
    "date_fields": {
        "created": "fields.date.created",
        "changed": "fields.date.changed",
        "original": "fields.date.original",
    },
    "availability_rule": "max(date.created, date.changed)",
    "published_rule": "date.original when present, otherwise date.created",
    "sort": ["date.changed:asc", "id:asc"],
    "filter": {
        "outer_operator_param": "filter[operator]",
        "condition_operator_param": "filter[conditions][N][operator]",
        "window_fields": ["date.created", "date.changed"],
        "window_operator": "OR",
        "range_params": ["value[from]", "value[to]"],
        "range_bounds": "inclusive",
    },
}

#: Fields requested from the API, every one of them confirmed present in the
#: official fields table for ``/reports``. Parent field names rather than dotted
#: leaves: the table names the field, and asking for the field returns its
#: object. Combined with ``profile=list``, these are explicit additions to the
#: profile defaults. The profile may still return other documented defaults;
#: this tuple describes what the connector asks for, not an exact response
#: allowlist.
REQUESTED_FIELDS: tuple[str, ...] = (
    "id",
    "title",
    "body",
    "date.created",
    "date.changed",
    "date.original",
    "language",
    "source",
    "country",
    "primary_country",
    "disaster",
    "disaster_type",
    "format",
    "theme",
    "url",
    "origin",
)

#: ReliefWeb's terms of use. Deliberately descriptive rather than conclusive:
#: the terms restrict use to personal/non-commercial purposes and prohibit
#: resale and redistribution *unless* specific permission or a particular
#: document's own terms provide otherwise, and which of those applies to a given
#: use is a question for a human, not for this string.
LICENCE = (
    "ReliefWeb terms and conditions: personal/non-commercial use; no resale or "
    "redistribution absent specific permission or material-specific terms; "
    "attribution to the contributing organisation. Human review required per use."
)
LICENCE_URL = "https://reliefweb.int/terms-conditions"


class ReliefWebContractError(ConnectorError):
    """The API returned a shape this connector does not understand.

    Raised rather than skipped. An unrecognised envelope means the assumptions
    in :data:`API_CONTRACT` have drifted, and continuing would write a silent
    gap into an append-only ledger that later looks like a quiet news week.
    """


class ReliefWebIncompleteIngestError(ReliefWebContractError):
    """A bounded or contradictory page walk ended before all reported rows were read."""


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


@dataclass(frozen=True)
class Instants:
    """The three raw API instants and the one value derived from them.

    Raw and derived are kept in separate attributes so nothing downstream has to
    guess which it is holding. ``changed`` and ``original`` are ``None`` when the
    API omits them -- a missing instant is represented as missing, never
    back-filled from another field to keep an invariant tidy.
    """

    created: datetime
    changed: datetime | None
    original: datetime | None
    availability: datetime

    @property
    def published(self) -> datetime:
        """``date.original`` when present, otherwise ``date.created``."""
        return self.original if self.original is not None else self.created

    @property
    def revised_after_creation(self) -> bool:
        """Was the record modified after it was posted?

        ``False`` when ``changed`` is absent: the absence of a modification
        timestamp is not evidence of a modification.
        """
        return self.changed is not None and self.changed > self.created


def instants_of(dates: Mapping[str, Any], *, report_id: object = None) -> Instants:
    """Parse the API's date object into four instants, preserving each one.

    Raises :class:`ReliefWebContractError` if ``date.original`` postdates
    availability. That combination is a data anomaly -- the author claims to
    have published the document after ReliefWeb last touched it -- and the two
    ways to "fix" it silently are both worse than failing: clamping
    ``published_at`` down to availability rewrites what the record says about
    itself, and raising availability to match would import the document's own
    date into the field admission depends on.
    """
    created = parse_api_datetime(dates.get("created"), field="date.created")

    raw_changed = dates.get("changed")
    changed = (
        parse_api_datetime(raw_changed, field="date.changed") if raw_changed is not None else None
    )

    raw_original = dates.get("original")
    original = (
        parse_api_datetime(raw_original, field="date.original")
        if raw_original is not None
        else None
    )

    availability = max(created, changed) if changed is not None else created

    if original is not None and original > availability:
        where = f"report {report_id}" if report_id is not None else "record"
        raise ReliefWebContractError(
            f"{where}: date.original ({_iso(original)}) postdates availability "
            f"({_iso(availability)} = max(created, changed)). Publication cannot follow the "
            "last modification of the record that carries it; this is a timestamp anomaly in "
            "the source data, not something to normalise away."
        )
    return Instants(created=created, changed=changed, original=original, availability=availability)


def availability_of(dates: Mapping[str, Any]) -> datetime:
    """The instant this representation became available.

    ``max(created, changed)``, or ``created`` alone when the API omits
    ``changed``. See the module docstring for why the maximum and not the
    minimum, and why never ``original``.
    """
    return instants_of(dates).availability


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

        Note what this cannot check. The appname is mandatory *and*, since
        1 November 2025, must be one ReliefWeb has approved in advance. Whether
        a given name is approved is knowable only to ReliefWeb: an unapproved
        name is well-formed here and refused at the origin with an HTTP 403.
        That is why the client classifies an origin 403 as
        :class:`~pramaanx.ingest.http.PermanentHttpError` rather than a proxy
        denial -- so it fails the run instead of skipping it.
        """
        configured = (self._options.appname or "").strip()
        if configured:
            return configured
        from_env = os.environ.get(APPNAME_ENV, "").strip()
        if from_env:
            return from_env
        raise ConnectorError(
            "ReliefWeb requires every caller to identify itself with an appname, and since "
            "2025-11-01 that appname must be pre-approved by ReliefWeb -- it is not a name "
            f"you can simply choose. Request one via {APPNAME_REQUEST_URL}, then set "
            f"{APPNAME_ENV} in the environment (see .env.example) or "
            "sources.reliefweb.appname in the configuration."
        )

    @property
    def source_version(self) -> str:
        """Provenance stamp. Built from :data:`API_VERSION`, never a literal."""
        return f"reliefweb-{API_VERSION}-{self._options.endpoint}"

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
            source_version=self.source_version,
            reliability_prior=0.75,
            notes=(
                "Curated humanitarian reporting from relief organisations. Coverage is "
                "response-driven: a crisis with no operational response is under-reported "
                "regardless of severity. first_observed_at is max(date.created, "
                "date.changed) because the API serves only the current revision. "
                "Offset pagination over a mutating index can omit records even under a "
                "total sort; ingest windows should overlap rather than be treated as "
                "complete single passes."
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
                max_retry_after_seconds=config.max_retry_after_seconds,
                proxy=config.proxy,
                trust_env=config.trust_env,
                ca_bundle=config.ca_bundle,
                verify=config.verify,
            )
        return self._client.get

    def build_url(self, window: FetchWindow, *, offset: int) -> str:
        """One page request, with every relationship stated rather than defaulted.

        Availability is ``max(date.created, date.changed)``. A changed-only
        query cannot implement that rule: it misses records where ``changed``
        is absent, and a source anomaly where ``changed < created`` can be
        selected in the earlier window and then rejected client-side. The date
        condition is therefore a nested OR: either raw instant intersects the
        window. The exact derived maximum and half-open boundary are applied
        again client-side.

        Two operators are written explicitly, never left to a default:

        ``filter[operator]=AND``
            The outer relationship. The date window and each value filter must
            all hold. Emitted even when the date condition stands alone, so the
            query does not change meaning the first time a filter is added.

        ``filter[conditions][N][operator]=OR``
            Within a condition carrying several values. "Any of these countries"
            is a union; an implicit AND here would ask for a report filed
            simultaneously under every listed country and quietly return
            nothing.
        """
        config = self._options
        params: list[tuple[str, str]] = [
            ("appname", self.appname()),
            ("limit", str(config.page_size)),
            ("offset", str(offset)),
            # The list profile's own field set, plus the explicit includes
            # below. Both are needed: the profile alone omits the body.
            ("profile", "list"),
        ]
        params += [("fields[include][]", name) for name in REQUESTED_FIELDS]
        # A total order, so paging is stable even when many records share a
        # timestamp. Without the id tiebreaker a page boundary can drop or
        # repeat records. Both keys are sortable per the official fields table.
        params += [("sort[]", "date.changed:asc"), ("sort[]", "id:asc")]

        # Outer AND: the date union and every configured taxonomy filter must
        # all hold. Inner OR: either timestamp may place the derived maximum in
        # the window. Fetching a few extra candidates is safe; filtering only
        # on changed can silently miss evidence.
        date_group = "filter[conditions][0]"
        params += [
            (f"{date_group}[operator]", "OR"),
            (f"{date_group}[conditions][0][field]", "date.created"),
            (f"{date_group}[conditions][0][value][from]", _iso(window.start)),
            (f"{date_group}[conditions][0][value][to]", _iso(window.end)),
            (f"{date_group}[conditions][1][field]", "date.changed"),
            (f"{date_group}[conditions][1][value][from]", _iso(window.start)),
            (f"{date_group}[conditions][1][value][to]", _iso(window.end)),
        ]
        index = 0
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
            if len(values) > 1:
                params.append((f"filter[conditions][{index}][operator]", "OR"))
        # Always, not only when a second condition exists: an unstated outer
        # operator is a dependency on an undocumented default.
        params.append(("filter[operator]", "AND"))

        return f"{config.base_url.rstrip('/')}/{config.endpoint}?{urlencode(params)}"

    # -- response parsing --------------------------------------------------
    @staticmethod
    def parse_envelope(payload: bytes, *, url: str) -> tuple[list[dict[str, Any]], int]:
        """Split a response into its items and the reported total.

        ``totalCount`` is **required**. It used to fall back to ``count`` and
        then to ``len(data)``, which is the most dangerous line this connector
        could contain: the pagination loop terminates when ``offset >= total``,
        so an envelope missing ``totalCount`` would report the first page's size
        as the total, stop after one page, and write a truncated window into an
        append-only ledger with no error anywhere. A missing or malformed total
        is a contract drift and must be loud.
        """
        display = redact_url(url)
        try:
            document = json.loads(payload)
        except json.JSONDecodeError as error:
            raise ReliefWebContractError(f"{display} returned a non-JSON body: {error}") from error
        if not isinstance(document, dict):
            raise ReliefWebContractError(
                f"{display} returned {type(document).__name__}, not an object"
            )
        if "error" in document:
            raise ReliefWebContractError(f"{display} returned an API error: {document['error']!r}")

        data = document.get("data")
        if not isinstance(data, list):
            raise ReliefWebContractError(
                f"{display} has no 'data' list; the API contract in API_CONTRACT has drifted "
                f"(keys present: {sorted(document)})"
            )
        for position, entry in enumerate(data):
            if not isinstance(entry, dict):
                raise ReliefWebContractError(
                    f"{display}: data[{position}] is {type(entry).__name__}, not an object; "
                    "every result item must be an object with 'id' and 'fields'"
                )

        total = _require_count(document, "totalCount", url=display)
        count = _require_count(document, "count", url=display)
        if count != len(data):
            raise ReliefWebContractError(
                f"{display} reported count={count} but returned {len(data)} items; the "
                "envelope contradicts itself and the page cannot be trusted"
            )
        if total < count:
            raise ReliefWebContractError(
                f"{display} reported totalCount={total} below count={count}; a page cannot "
                "hold more results than exist"
            )
        return data, total

    def _to_item(self, entry: Mapping[str, Any], *, url: str) -> RawItem:
        display = redact_url(url)
        if not isinstance(entry.get("fields"), dict):
            raise ReliefWebContractError(f"{display}: item has no 'fields' object: {entry!r}")
        fields: dict[str, Any] = dict(entry["fields"])
        identifier = _require_item_id(entry, fields, url=display)

        dates = fields.get("date")
        if not isinstance(dates, dict):
            raise ReliefWebContractError(f"{display}: report {identifier} has no date object")
        instants = instants_of(dates, report_id=identifier)

        # The payload is the API record plus the provenance needed to interpret
        # it, canonically serialised so identical records hash identically.
        payload = canonical_bytes(
            {
                "source": "reliefweb",
                "api_version": API_VERSION,
                "endpoint": self._options.endpoint,
                "report_id": str(identifier),
                "request_url": redact_url(url),
                "availability_basis": API_CONTRACT["availability_rule"],
                "fields": fields,
            }
        )
        return RawItem(
            payload=payload,
            # Availability, never the document's own publication date.
            first_observed_at=instants.availability,
            modality=Modality.TEXT,
            # The record's own earliest publication claim: date.original when
            # it exists, otherwise the ReliefWeb posting. Taken as stated.
            published_at=instants.published,
            # ReliefWeb report metadata carries publication dates, not the date
            # of the situation described. Deriving an event time from a
            # publication date would be inventing one.
            claimed_event_time=None,
            uri=_first_url(fields),
            language=_primary_language(fields),
            licence=LICENCE,
            source_version=self.source_version,
            metadata={
                "report_id": str(identifier),
                # Three raw instants, each exactly as the API gave it, plus the
                # derived one under its own name. date_changed is null when the
                # API omitted it -- it does NOT carry the computed availability.
                "date_created": _iso(instants.created),
                "date_changed": _iso(instants.changed) if instants.changed else None,
                "date_original": _iso(instants.original) if instants.original else None,
                "date_availability": _iso(instants.availability),
                "revised_after_creation": instants.revised_after_creation,
            },
        )

    # -- connector API -----------------------------------------------------
    def plan(self, window: FetchWindow) -> dict[str, Any]:
        """Describe the fetch without performing it. Makes no request."""
        plan = super().plan(window)
        config = self._options
        # The appname is resolved for the plan so that a missing identity fails
        # during --dry-run rather than on the first real request.
        # Resolved, never emitted. Resolving proves the identity exists so a
        # missing one fails during --dry-run rather than on the first real
        # request; emitting it would put the caller identity into stdout, into
        # whatever captures a CLI plan, and into any log that keeps it.
        self.appname()
        plan.update(
            {
                "endpoint": f"{config.base_url.rstrip('/')}/{config.endpoint}",
                "api_version": API_VERSION,
                "appname_configured": True,
                "appname_source": "config" if config.appname else APPNAME_ENV,
                "appname": REDACTED_APPNAME,
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
                "first_request_url": redact_url(self.build_url(window, offset=0)),
                "official_docs_verified": API_CONTRACT["official_docs_verified"],
                "live_api_verified": API_CONTRACT["live_api_verified"],
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
        reported_total: int | None = None

        for page in range(1, config.max_pages + 1):
            url = self.build_url(window, offset=offset)
            payload = fetcher(url)
            entries, total = self.parse_envelope(payload, url=url)
            if reported_total is None:
                reported_total = total
            elif total != reported_total:
                raise ReliefWebIncompleteIngestError(
                    f"{redact_url(url)} changed totalCount from {reported_total} to {total} "
                    "during pagination; the index mutated and completeness cannot be proven. "
                    "Retry with an overlapping window."
                )
            if not entries:
                if offset < total:
                    raise ReliefWebIncompleteIngestError(
                        f"{redact_url(url)} returned an empty page at offset {offset} while "
                        f"totalCount={total}; stopping would silently truncate the window"
                    )
                break

            if offset + len(entries) > total:
                raise ReliefWebContractError(
                    f"{redact_url(url)} returned {len(entries)} items at offset {offset}, "
                    f"which exceeds totalCount={total}; the pagination envelope contradicts "
                    "itself"
                )

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
            raise ReliefWebIncompleteIngestError(
                f"ReliefWeb pagination reached max_pages={config.max_pages} at offset "
                f"{offset} before totalCount={reported_total}; no partial observations will be "
                "committed. Narrow the window or raise max_pages."
            )

        log.info("reliefweb.fetch_complete", emitted=emitted, unique_records=len(seen))


def _require_count(document: Mapping[str, Any], key: str, *, url: str) -> int:
    """A required non-negative integer count. ``True`` is not 1.

    ``bool`` is a subclass of ``int`` in Python, so a plain ``isinstance(x, int)``
    accepts ``True`` and the pagination loop would then compare offsets against
    it. Rejected explicitly.
    """
    if key not in document:
        raise ReliefWebContractError(
            f"{url} has no {key!r}; the official result structure requires it, and inferring "
            "it from the page would let a truncated walk look like a complete one"
        )
    value = document[key]
    if isinstance(value, bool) or not isinstance(value, int):
        raise ReliefWebContractError(
            f"{url} reported a non-integer {key}: {value!r} ({type(value).__name__})"
        )
    if value < 0:
        raise ReliefWebContractError(f"{url} reported a negative {key}: {value!r}")
    return value


def _require_item_id(entry: Mapping[str, Any], fields: Mapping[str, Any], *, url: str) -> int:
    """The item's top-level integer ``id``, cross-checked against ``fields.id``.

    No fallback from a missing top-level ``id`` to ``fields.id``. The official
    result structure puts ``id`` at the item's top level; silently accepting it
    from somewhere else would hide exactly the drift this connector exists to
    surface, and the id is what deduplication and every ledger reference key on.
    """
    if "id" not in entry:
        raise ReliefWebContractError(
            f"{url}: item has no top-level id: {entry!r}. The official result structure "
            "places 'id' beside 'fields'; this connector does not substitute fields.id."
        )
    identifier = entry["id"]
    if isinstance(identifier, bool) or not isinstance(identifier, int):
        raise ReliefWebContractError(
            f"{url}: item id {identifier!r} is {type(identifier).__name__}, not the integer "
            "the official fields table specifies for a report id"
        )
    if "id" in fields:
        field_id = fields["id"]
        if isinstance(field_id, bool) or not isinstance(field_id, int):
            raise ReliefWebContractError(
                f"{url}: report {identifier} has a non-integer fields.id: {field_id!r}"
            )
        if field_id != identifier:
            raise ReliefWebContractError(
                f"{url}: item id {identifier} disagrees with fields.id {field_id}; the record "
                "does not agree with itself about which report it is"
            )
    return identifier


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
