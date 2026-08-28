"""Article records, licence-bounded retention, and syndication identity.

Three things go wrong with news evidence, and this module exists to make each
of them impossible rather than unlikely.

**Storing text nobody granted the right to store.** A publisher's licence is a
property of the *source*, not of the article that happens to be in hand, and
"we did not know" is the state in which the mistake gets made. So retention is
decided by :class:`LicenceClass` before a body is ever written, and the unknown
case retains hashes and metadata -- never text. Failing closed costs a feature;
failing open costs a takedown.

**Counting one story five times.** Indian news carries a large volume of wire
copy: one PTI or ANI report appears under five mastheads within the hour. Five
copies are five *documents* and one *information lineage*, and a forecasting
system that treats them as five independent confirmations has invented
corroboration out of a distribution contract. :func:`group_syndication` assigns
lineage, and it is the lineage count -- not the document count -- that any
downstream independence feature is allowed to read.

**Letting a later edit rewrite an earlier snapshot.** Publishers silently
revise: a death toll changes, an attribution is added, a headline is softened.
If a record were mutable, evidence "as of" a past cutoff would drift every time
upstream edited. So a revision is a *new record* pointing at the one it
supersedes, and :func:`latest_as_of` picks the newest revision that was
resolvable at the cutoff. Nothing is ever overwritten, which is what makes a
point-in-time reconstruction reconstructable.
"""

from __future__ import annotations

import re
import unicodedata
from collections.abc import Iterable, Mapping, Sequence
from dataclasses import dataclass
from datetime import datetime
from enum import StrEnum
from pathlib import Path
from urllib.parse import parse_qsl, urlencode, urlsplit, urlunsplit

from pydantic import Field, model_validator

from pramaanx.hashing import hash_object, hash_text, stable_id
from pramaanx.schemas.base import UtcDatetime, VersionedModel

PARSER_VERSION = "news-article/1.0.0"
"""Bumped whenever canonicalisation or hashing changes meaning.

Recorded on every record, because a content hash is only comparable against
another hash produced by the same rules. Two records with different parser
versions may disagree about identity for reasons that have nothing to do with
the article.
"""

#: Query parameters that identify a *referral*, not a document. Left in place
#: they would split one article into as many canonical URLs as there are
#: campaigns pointing at it, and every one of those would count as an
#: independent source.
TRACKING_PARAMETERS: frozenset[str] = frozenset(
    {
        "cmpid",
        "fbclid",
        "gclid",
        "igshid",
        "mc_cid",
        "mc_eid",
        "mkt_tok",
        "msclkid",
        "ncid",
        "ref",
        "referrer",
        "s_kwcid",
        "src",
        "twclid",
        "utm_campaign",
        "utm_content",
        "utm_id",
        "utm_medium",
        "utm_name",
        "utm_source",
        "utm_term",
        "wtmc",
        "yclid",
    }
)

_DEFAULT_PORTS = {"http": "80", "https": "443"}
_WHITESPACE = re.compile(r"\s+")
_SHINGLE_SIZE = 5


class CanonicalUrlError(ValueError):
    """A URL cannot be canonicalised without guessing or leaking a credential."""


class LicenceClass(StrEnum):
    """What may be *stored* about an article, from most to least permissive.

    This is a storage decision, not a legal opinion. It records what the source
    registry asserts the project is allowed to keep, and every value below
    ``FULL_TEXT_PERMITTED`` narrows what :func:`apply_retention` will write.

    ``UNKNOWN`` and ``PROHIBITED`` are deliberately different states with the
    same storage outcome. Collapsing them would lose the distinction between
    "nobody has checked this publisher's terms" -- an action item -- and "the
    terms were read and they say no" -- a settled fact.
    """

    #: Text may be stored and re-read in full.
    FULL_TEXT_PERMITTED = "full_text_permitted"
    #: A bounded quotation may be stored; the rest may not.
    SNIPPET_ONLY = "snippet_only"
    #: Headline, byline, URL and timestamps only. No body.
    METADATA_ONLY = "metadata_only"
    #: Hashes only. Enough to detect duplication and revision, not to read.
    HASH_ONLY = "hash_only"
    #: Terms have not been established. Treated as ``HASH_ONLY`` when storing.
    UNKNOWN = "unknown"
    #: Terms were read and forbid retention. Treated as ``HASH_ONLY``.
    PROHIBITED = "prohibited"


class RedistributionPermission(StrEnum):
    """Whether stored content may leave this project, and how far."""

    PUBLIC = "public"
    INTERNAL_ONLY = "internal_only"
    NONE = "none"
    UNKNOWN = "unknown"


#: The licence classes that permit any body text at all. Anything else keeps
#: hashes alone.
_TEXT_PERMITTED = frozenset({LicenceClass.FULL_TEXT_PERMITTED, LicenceClass.SNIPPET_ONLY})

#: Licence classes that retain no content whatsoever, not even a headline.
_FAIL_CLOSED = frozenset({LicenceClass.UNKNOWN, LicenceClass.PROHIBITED})

#: Maximum characters retained under :attr:`LicenceClass.SNIPPET_ONLY`.
#: Conservative on purpose: a "snippet" long enough to substitute for the
#: article is not a snippet.
SNIPPET_MAX_CHARS = 300


class RetentionDecision(StrEnum):
    """Why a body was or was not stored. Recorded, never inferred later."""

    STORED_FULL = "stored_full"
    STORED_SNIPPET = "stored_snippet"
    METADATA_KEPT = "metadata_kept"
    HASH_KEPT = "hash_kept"
    #: The licence was unknown or prohibited, so the fail-closed path ran.
    WITHHELD_FAIL_CLOSED = "withheld_fail_closed"


@dataclass(frozen=True)
class RetainedContent:
    """The result of applying a licence to acquired text."""

    headline: str | None
    body_text: str | None
    body_hash: str
    normalised_content_hash: str
    decision: RetentionDecision
    body_characters: int


def canonical_url(raw: str) -> str:
    """Reduce a URL to the document it addresses.

    Scheme and host are lower-cased, default ports and fragments dropped,
    tracking parameters removed, remaining parameters sorted, and a trailing
    slash trimmed from a non-root path. A leading ``www.`` is stripped because a
    publisher that serves the same article on both hosts would otherwise
    contribute two "independent" sources.

    Userinfo raises rather than being dropped: a URL carrying ``user:token@``
    is a credential, and a credential that reaches a record reaches every
    manifest, log and hash downstream of it.
    """
    text = raw.strip()
    if not text:
        raise CanonicalUrlError("empty URL")
    split = urlsplit(text)
    if not split.scheme or not split.netloc:
        raise CanonicalUrlError(
            f"URL is not absolute: {raw!r}. A relative URL cannot be canonicalised "
            "without guessing the publisher it belongs to."
        )
    if split.scheme.lower() not in {"http", "https"}:
        raise CanonicalUrlError(f"unsupported URL scheme {split.scheme!r} in {raw!r}")
    if "@" in split.netloc:
        raise CanonicalUrlError(
            f"URL {raw!r} carries userinfo. Credentials must never enter a record; "
            "supply them through the environment named by the source registry."
        )

    scheme = split.scheme.lower()
    host = (split.hostname or "").lower()
    if not host:
        raise CanonicalUrlError(f"URL has no host: {raw!r}")
    host = host.removeprefix("www.")
    netloc = host
    if split.port is not None and str(split.port) != _DEFAULT_PORTS.get(scheme):
        netloc = f"{host}:{split.port}"

    kept = [
        (key, value)
        for key, value in parse_qsl(split.query, keep_blank_values=True)
        if key.lower() not in TRACKING_PARAMETERS
    ]
    query = urlencode(sorted(kept))

    path = split.path or "/"
    if len(path) > 1 and path.endswith("/"):
        path = path.rstrip("/") or "/"

    return urlunsplit((scheme, netloc, path, query, ""))


def canonical_url_hash(raw: str) -> str:
    """Content hash of the canonical form of ``raw``."""
    return hash_text(canonical_url(raw))


def normalise_for_comparison(text: str) -> str:
    """Fold a document to the form used for duplicate detection.

    NFKC first, so a Devanagari string composed two different ways compares
    equal; then case folding, punctuation removal and whitespace collapse. The
    result is never stored as content and never shown to a reader -- it exists
    only to be hashed.
    """
    folded = unicodedata.normalize("NFKC", text).casefold()
    stripped = "".join(
        " " if unicodedata.category(char).startswith(("P", "S", "Z")) else char for char in folded
    )
    return _WHITESPACE.sub(" ", stripped).strip()


def normalised_content_hash(headline: str | None, body: str | None) -> str:
    """Identity hash for "is this the same story text?".

    Headline and body are hashed together but kept separable, so a feed that
    supplies only a headline still gets a usable identity rather than a hash of
    the empty string shared with every other body-less record.
    """
    return hash_object(
        {
            "headline": normalise_for_comparison(headline or ""),
            "body": normalise_for_comparison(body or ""),
            "parser_version": PARSER_VERSION,
        }
    )


_SCRIPT_RANGES: tuple[tuple[str, int, int], ...] = (
    ("Latin", 0x0041, 0x024F),
    ("Arabic", 0x0600, 0x06FF),
    ("Devanagari", 0x0900, 0x097F),
    ("Bengali", 0x0980, 0x09FF),
    ("Gurmukhi", 0x0A00, 0x0A7F),
    ("Gujarati", 0x0A80, 0x0AFF),
    ("Oriya", 0x0B00, 0x0B7F),
    ("Tamil", 0x0B80, 0x0BFF),
    ("Telugu", 0x0C00, 0x0C7F),
    ("Kannada", 0x0C80, 0x0CFF),
    ("Malayalam", 0x0D00, 0x0D7F),
)

#: Returned when no letter in the text falls in a known range. Never guessed
#: as Latin: "we cannot tell" and "it is English" are different claims.
SCRIPT_UNKNOWN = "Unknown"


def dominant_script(text: str) -> str:
    """The script most letters in ``text`` belong to.

    A provisional signal for coverage accounting -- "is this feed producing any
    Malayalam at all?" -- not a linguistic analysis. WP2 owns real language and
    script detection; this exists so that a source-health report can notice a
    regional-language feed going silent before that package lands. Ties are
    broken by the range order above so the answer is deterministic.
    """
    counts: dict[str, int] = {}
    for char in text:
        code = ord(char)
        for name, low, high in _SCRIPT_RANGES:
            if low <= code <= high:
                counts[name] = counts.get(name, 0) + 1
                break
    if not counts:
        return SCRIPT_UNKNOWN
    order = {name: index for index, (name, _, _) in enumerate(_SCRIPT_RANGES)}
    return min(counts, key=lambda name: (-counts[name], order[name]))


def apply_retention(
    *,
    licence: LicenceClass,
    headline: str | None,
    body: str | None,
) -> RetainedContent:
    """Decide what may be written, before anything is written.

    Hashes are computed from the *acquired* text in every case, including the
    cases where that text is then discarded. That is the point: duplicate
    detection, revision detection and independence accounting all work on
    hashes, so a source whose terms forbid retention still contributes to them
    without a single stored character.
    """
    body_hash = hash_text(body if body is not None else "")
    content_hash = normalised_content_hash(headline, body)
    characters = len(body or "")

    if licence in _FAIL_CLOSED:
        return RetainedContent(
            headline=None,
            body_text=None,
            body_hash=body_hash,
            normalised_content_hash=content_hash,
            decision=RetentionDecision.WITHHELD_FAIL_CLOSED,
            body_characters=characters,
        )
    if licence is LicenceClass.HASH_ONLY:
        return RetainedContent(
            headline=None,
            body_text=None,
            body_hash=body_hash,
            normalised_content_hash=content_hash,
            decision=RetentionDecision.HASH_KEPT,
            body_characters=characters,
        )
    if licence is LicenceClass.METADATA_ONLY:
        return RetainedContent(
            headline=headline,
            body_text=None,
            body_hash=body_hash,
            normalised_content_hash=content_hash,
            decision=RetentionDecision.METADATA_KEPT,
            body_characters=characters,
        )
    if licence is LicenceClass.SNIPPET_ONLY:
        snippet = None if body is None else body[:SNIPPET_MAX_CHARS]
        return RetainedContent(
            headline=headline,
            body_text=snippet,
            body_hash=body_hash,
            normalised_content_hash=content_hash,
            decision=RetentionDecision.STORED_SNIPPET,
            body_characters=characters,
        )
    return RetainedContent(
        headline=headline,
        body_text=body,
        body_hash=body_hash,
        normalised_content_hash=content_hash,
        decision=RetentionDecision.STORED_FULL,
        body_characters=characters,
    )


class ArticleRecord(VersionedModel):
    """One acquired article, at one point in its revision history.

    Four timestamps are kept apart on purpose, because collapsing any pair of
    them produces a leak that looks like a result:

    ``published_at``
        when the publisher says it went out;
    ``modified_at``
        when the publisher last edited it, if it says;
    ``retrieved_at``
        when this project fetched these bytes;
    ``first_resolvable_at``
        the earliest moment this project could legitimately have acted on it.

    Cutoff filtering reads ``first_resolvable_at`` and nothing else. A
    publisher's own ``published_at`` is a claim, sometimes back-dated, and a
    system that filters on it will happily use an article that did not reach
    anyone until the following week.
    """

    observation_id: str
    source_id: str
    source_record_id: str
    canonical_url: str
    canonical_url_hash: str

    headline: str | None = None
    body_text: str | None = None
    body_hash: str
    normalised_content_hash: str
    body_characters: int = Field(default=0, ge=0)

    original_language: str | None = None
    detected_language: str | None = None
    script: str = SCRIPT_UNKNOWN

    published_at: UtcDatetime | None = None
    modified_at: UtcDatetime | None = None
    retrieved_at: UtcDatetime
    first_resolvable_at: UtcDatetime

    byline: str | None = None
    wire_service: str | None = None
    syndication_group_id: str | None = None
    source_lineage_id: str | None = None

    licence_class: LicenceClass
    redistribution: RedistributionPermission
    retention_decision: RetentionDecision

    source_version: str = "unversioned"
    parser_version: str = PARSER_VERSION
    #: Identity hash over the *acquisition facts* only -- source, URL, content,
    #: timestamps, licence. Deliberately distinct from the inherited
    #: :meth:`~pramaanx.schemas.base.PramaanModel.content_hash`, which covers the
    #: whole record including annotations added later. Syndication grouping and
    #: snapshotting both write fields, and neither may change what this record
    #: *is*, so identity is computed once and stored.
    article_content_hash: str
    snapshot_hash: str | None = None

    #: Set when the publisher claims a publication time later than the moment
    #: this project downloaded the article. That is a clock problem, not a
    #: scoop, and it is recorded rather than quietly corrected -- a source whose
    #: timestamps drift is a source whose delay statistics mean nothing.
    publisher_timestamp_disputed: bool = False

    #: The record this one supersedes. Revisions are new records, never edits.
    revision_of: str | None = None
    revision_index: int = Field(default=0, ge=0)

    @model_validator(mode="after")
    def _check_timeline(self) -> ArticleRecord:
        if self.first_resolvable_at > self.retrieved_at:
            raise ValueError(
                f"{self.observation_id}: first_resolvable_at "
                f"({self.first_resolvable_at.isoformat()}) is after retrieved_at "
                f"({self.retrieved_at.isoformat()}). An article cannot become usable "
                "later than the moment it was fetched."
            )
        if self.published_at is not None and self.published_at > self.retrieved_at:
            # The two invariants genuinely conflict here, and only one of them
            # is load-bearing. ``first_resolvable_at <= retrieved_at`` is what
            # cutoff safety rests on and is never negotiable; "resolvable no
            # earlier than published" is a sanity check on a publisher's claim,
            # and the claim is the only unverified input in the pair. So the
            # claim gives way -- but visibly, never silently.
            if not self.publisher_timestamp_disputed:
                raise ValueError(
                    f"{self.observation_id}: published_at "
                    f"({self.published_at.isoformat()}) is after retrieved_at "
                    f"({self.retrieved_at.isoformat()}), which cannot be true. A record "
                    "in this state must set publisher_timestamp_disputed, so that the "
                    "source's delay statistics can be discounted rather than believed."
                )
        elif self.published_at is not None and self.first_resolvable_at < self.published_at:
            raise ValueError(
                f"{self.observation_id}: first_resolvable_at is before published_at. "
                "Nothing is resolvable before it exists."
            )
        if (
            self.modified_at is not None
            and self.published_at is not None
            and self.modified_at < self.published_at
        ):
            raise ValueError(
                f"{self.observation_id}: modified_at precedes published_at. One of the two "
                "timestamps is wrong, and guessing which would corrupt every revision "
                "comparison built on them."
            )
        return self

    @model_validator(mode="after")
    def _check_retention_matches_licence(self) -> ArticleRecord:
        """A record may not carry text its licence class does not permit.

        Enforced on the record rather than only in :func:`apply_retention`, so
        that a hand-built record, a deserialised one, or a future caller that
        skips the helper is refused the same way.
        """
        if self.licence_class not in _TEXT_PERMITTED and self.body_text is not None:
            raise ValueError(
                f"{self.observation_id}: licence class {self.licence_class.value!r} stores "
                "no body text, but body_text is set. Retention is decided by the licence, "
                "not by what happened to be available."
            )
        if (
            self.licence_class is LicenceClass.SNIPPET_ONLY
            and self.body_text is not None
            and len(self.body_text) > SNIPPET_MAX_CHARS
        ):
            raise ValueError(
                f"{self.observation_id}: snippet of {len(self.body_text)} characters "
                f"exceeds the {SNIPPET_MAX_CHARS}-character limit"
            )
        if self.licence_class in _FAIL_CLOSED:
            if self.retention_decision is not RetentionDecision.WITHHELD_FAIL_CLOSED:
                raise ValueError(
                    f"{self.observation_id}: licence class {self.licence_class.value!r} must "
                    f"record {RetentionDecision.WITHHELD_FAIL_CLOSED.value!r}, not "
                    f"{self.retention_decision.value!r}"
                )
            if self.headline is not None:
                raise ValueError(
                    f"{self.observation_id}: an unknown or prohibited licence retains no "
                    "headline either. A headline is content."
                )
        return self

    @property
    def content_group_hash(self) -> str:
        """Exact-match identity used as the first syndication signal."""
        return self.normalised_content_hash

    def usable_at(self, cutoff: datetime) -> bool:
        """Whether this record may be read at ``cutoff``."""
        return self.first_resolvable_at <= cutoff

    @staticmethod
    def build_id(source_id: str, content_hash: str, first_resolvable_at: datetime) -> str:
        """Deterministic identifier: same article, same source, same id."""
        return stable_id("art", source_id, content_hash, first_resolvable_at)


def build_content_hash(payload: Mapping[str, object]) -> str:
    """Hash of everything that makes a record *this* record.

    Callers exclude the fields assigned after the fact -- syndication group,
    lineage, snapshot -- so that grouping or snapshotting a record never
    changes its identity.
    """
    return hash_object(dict(payload))


class GroupingReason(StrEnum):
    """Why two records were placed in one syndication group."""

    #: Identical normalised content. Not a guess.
    IDENTICAL_CONTENT = "identical_content"
    #: The same declared wire service, on near-identical content.
    DECLARED_WIRE = "declared_wire"
    #: Token-shingle similarity above threshold. A candidate signal only.
    HIGH_SIMILARITY = "high_similarity"
    #: A group of one.
    SINGLETON = "singleton"


class SyndicationGroup(VersionedModel):
    """One story, however many mastheads carried it."""

    group_id: str
    lineage_id: str
    member_observation_ids: tuple[str, ...]
    wire_service: str | None = None
    reasons: tuple[GroupingReason, ...]

    @property
    def size(self) -> int:
        return len(self.member_observation_ids)


class SyndicationReport(VersionedModel):
    """The outcome of grouping a set of records, and why."""

    groups: tuple[SyndicationGroup, ...]
    similarity_threshold: float

    @property
    def independent_lineage_count(self) -> int:
        """Distinct information lineages -- the only honest independence count.

        Not ``len(groups)``: two outlets both running the same agency copy under
        slightly different edits land in two content groups but one lineage, and
        it is the lineage that says how many times the world independently
        reported something.
        """
        return len({group.lineage_id for group in self.groups})

    def group_for(self, observation_id: str) -> SyndicationGroup:
        for group in self.groups:
            if observation_id in group.member_observation_ids:
                return group
        raise KeyError(f"{observation_id!r} is not in this syndication report")

    def assigned(self, records: Iterable[ArticleRecord]) -> tuple[ArticleRecord, ...]:
        """Copies of ``records`` carrying their group and lineage.

        The originals are returned untouched; grouping annotates, it never
        rewrites. Preserving the ungrouped record is what lets a later run
        re-group under a different threshold and show what changed.
        """
        assigned: list[ArticleRecord] = []
        for record in records:
            group = self.group_for(record.observation_id)
            assigned.append(
                record.model_copy(
                    update={
                        "syndication_group_id": group.group_id,
                        "source_lineage_id": group.lineage_id,
                    }
                )
            )
        return tuple(assigned)


def _shingles(text: str) -> frozenset[str]:
    tokens = normalise_for_comparison(text).split()
    if not tokens:
        return frozenset()
    if len(tokens) < _SHINGLE_SIZE:
        return frozenset({" ".join(tokens)})
    return frozenset(
        " ".join(tokens[index : index + _SHINGLE_SIZE])
        for index in range(len(tokens) - _SHINGLE_SIZE + 1)
    )


def _jaccard(left: frozenset[str], right: frozenset[str]) -> float:
    if not left or not right:
        return 0.0
    union = len(left | right)
    return len(left & right) / union if union else 0.0


class _Union:
    """Small deterministic union-find over sorted observation ids."""

    def __init__(self, members: Sequence[str]) -> None:
        self._parent = {member: member for member in members}

    def find(self, member: str) -> str:
        root = member
        while self._parent[root] != root:
            root = self._parent[root]
        while self._parent[member] != root:
            self._parent[member], member = root, self._parent[member]
        return root

    def union(self, left: str, right: str) -> None:
        left_root, right_root = self.find(left), self.find(right)
        if left_root == right_root:
            return
        # Lexicographic order, not tree size: the outcome must not depend on
        # the order the caller happened to supply members in.
        low, high = sorted((left_root, right_root))
        self._parent[high] = low


def group_syndication(
    records: Iterable[ArticleRecord],
    *,
    similarity_threshold: float = 0.9,
) -> SyndicationReport:
    """Assign every record to exactly one syndication group and lineage.

    Grouping runs in two passes, weaker evidence last:

    1. identical normalised content -- a fact, not an inference;
    2. token-shingle similarity above ``similarity_threshold``, recorded as
       :attr:`GroupingReason.DECLARED_WIRE` when both records name the same wire
       service and :attr:`GroupingReason.HIGH_SIMILARITY` when they do not.

    Similarity never merges records from the *same* outlet, because a publisher
    running two related stories is not syndicating to itself, and merging them
    would understate that outlet's own output.

    Output is a pure function of the record set: members are sorted, group ids
    derive from the sorted content hashes they contain, and the union-find
    resolves ties lexicographically. Shuffling the input cannot change a single
    byte of the result.
    """
    if not 0.0 < similarity_threshold <= 1.0:
        raise ValueError(f"similarity_threshold must be in (0, 1], got {similarity_threshold}")

    ordered = sorted(records, key=lambda record: record.observation_id)
    if not ordered:
        return SyndicationReport(groups=(), similarity_threshold=similarity_threshold)

    ids = [record.observation_id for record in ordered]
    by_id = {record.observation_id: record for record in ordered}
    if len(by_id) != len(ids):
        duplicates = sorted({identifier for identifier in ids if ids.count(identifier) > 1})
        raise ValueError(f"duplicate observation ids in syndication input: {duplicates}")

    union = _Union(ids)
    reasons: dict[str, set[GroupingReason]] = {identifier: set() for identifier in ids}

    exact: dict[str, list[str]] = {}
    for record in ordered:
        exact.setdefault(record.content_group_hash, []).append(record.observation_id)
    for members in exact.values():
        for other in members[1:]:
            union.union(members[0], other)
            reasons[members[0]].add(GroupingReason.IDENTICAL_CONTENT)
            reasons[other].add(GroupingReason.IDENTICAL_CONTENT)

    shingles = {
        record.observation_id: _shingles(f"{record.headline or ''} {record.body_text or ''}")
        for record in ordered
    }
    for index, left_id in enumerate(ids):
        for right_id in ids[index + 1 :]:
            if union.find(left_id) == union.find(right_id):
                continue
            left, right = by_id[left_id], by_id[right_id]
            if left.source_id == right.source_id:
                continue
            if _jaccard(shingles[left_id], shingles[right_id]) < similarity_threshold:
                continue
            shared_wire = left.wire_service is not None and left.wire_service == right.wire_service
            reason = GroupingReason.DECLARED_WIRE if shared_wire else GroupingReason.HIGH_SIMILARITY
            union.union(left_id, right_id)
            reasons[left_id].add(reason)
            reasons[right_id].add(reason)

    clustered: dict[str, list[str]] = {}
    for identifier in ids:
        clustered.setdefault(union.find(identifier), []).append(identifier)

    groups: list[SyndicationGroup] = []
    for members in clustered.values():
        member_ids = tuple(sorted(members))
        declared: set[str] = set()
        for member in member_ids:
            wire_service = by_id[member].wire_service
            if wire_service is not None:
                declared.add(wire_service)
        wires = sorted(declared)
        wire = wires[0] if len(wires) == 1 else None
        group_id = stable_id(
            "syn", sorted({by_id[member].content_group_hash for member in member_ids})
        )
        # A declared wire service is the lineage. Without one, the story text
        # itself is: two outlets that filed the same words did not file twice.
        lineage_id = stable_id("lin", wire) if wire else stable_id("lin", group_id)
        collected = sorted({reason for member in member_ids for reason in reasons[member]})
        groups.append(
            SyndicationGroup(
                group_id=group_id,
                lineage_id=lineage_id,
                member_observation_ids=member_ids,
                wire_service=wire,
                reasons=tuple(collected) or (GroupingReason.SINGLETON,),
            )
        )

    groups.sort(key=lambda group: group.group_id)
    return SyndicationReport(groups=tuple(groups), similarity_threshold=similarity_threshold)


class SnapshotManifest(VersionedModel):
    """What a materialisation did, in a form that can be checked later.

    Carries both an input and an output hash. The input hash pins the record
    set that was asked for; the output hash pins the bytes that were written.
    A rebuild that produces the same input hash and a different output hash has
    found a non-determinism bug, which is precisely the finding a manifest with
    only one of the two would hide.
    """

    kind: str = "news_articles"
    cutoff: UtcDatetime
    parser_version: str = PARSER_VERSION
    record_count: int = Field(ge=0)
    input_hash: str
    output_hash: str
    dry_run: bool
    path: str | None = None
    #: Distinct information lineages in the snapshot. Recorded next to the
    #: record count so that no reader has to divide one by the other to find
    #: out how much of the corpus is wire copy.
    independent_lineages: int | None = Field(default=None, ge=0)


class SnapshotWriteError(RuntimeError):
    """A materialisation would have overwritten committed evidence."""


def snapshot_payload(records: Sequence[ArticleRecord]) -> str:
    """The canonical serialisation of a snapshot: sorted, one record per line.

    Sorting by ``observation_id`` rather than by arrival makes the bytes a
    function of the record *set*. Two runs that acquire the same articles in a
    different order produce identical files, which is what lets a leakage test
    assert byte-identity instead of set-equality.
    """
    ordered = sorted(records, key=lambda record: record.observation_id)
    return "\n".join(record.model_dump_json() for record in ordered) + ("\n" if ordered else "")


def write_snapshot(
    records: Iterable[ArticleRecord],
    *,
    path: Path,
    cutoff: datetime,
    dry_run: bool = False,
    lineages: int | None = None,
) -> SnapshotManifest:
    """Materialise records immutably, or describe what that would do.

    Refuses to overwrite. A snapshot is evidence somebody may already have
    forecast against, and silently replacing it would make every manifest that
    cites it wrong without changing a single hash those manifests recorded. The
    caller that genuinely wants a new snapshot names a new path.

    ``dry_run`` computes every hash and writes nothing, so a plan can be
    inspected -- and diffed against the eventual result -- without committing
    anything to disk.
    """
    if cutoff.tzinfo is None:
        raise ValueError("write_snapshot requires a timezone-aware cutoff")
    ordered = sorted(records, key=lambda record: record.observation_id)
    for record in ordered:
        if not record.usable_at(cutoff):
            raise SnapshotWriteError(
                f"{record.observation_id} first became resolvable at "
                f"{record.first_resolvable_at.isoformat()}, after the snapshot cutoff "
                f"{cutoff.isoformat()}. A snapshot that contains evidence from after its "
                "own cutoff is not a snapshot."
            )
    payload = snapshot_payload(ordered)
    input_hash = hash_object([record.article_content_hash for record in ordered])
    output_hash = hash_text(payload)

    target = Path(path)
    if not dry_run:
        if target.exists():
            raise SnapshotWriteError(
                f"{target} already exists. Snapshots are immutable: write a new path rather "
                "than replacing evidence that earlier forecasts may already cite."
            )
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_text(payload, encoding="utf-8")

    return SnapshotManifest(
        cutoff=cutoff,
        record_count=len(ordered),
        input_hash=input_hash,
        output_hash=output_hash,
        dry_run=dry_run,
        path=target.as_posix(),
        independent_lineages=lineages,
    )


def latest_as_of(records: Iterable[ArticleRecord], cutoff: datetime) -> tuple[ArticleRecord, ...]:
    """The newest revision of each article that was resolvable at ``cutoff``.

    This is the whole revision guarantee in one function. A body edited after
    the cutoff arrives as a *later* record with a later ``first_resolvable_at``;
    it is filtered out here, and the earlier version is returned unchanged. The
    caller therefore sees what it would have seen at the time, not what the
    publisher has since decided the story says.

    Revisions are collapsed **within a source**, keyed on
    ``(source_id, canonical_url_hash)``. Two different sources surfacing the
    same URL -- a URL index and a publisher API both carrying one article -- are
    two acquisitions, not two revisions, and collapsing them here would silently
    discard one source's record of having seen it. Deciding that two records are
    the same story is :func:`group_syndication`'s job, and it says so with a
    lineage rather than by deletion.
    """
    if cutoff.tzinfo is None:
        raise ValueError("latest_as_of requires a timezone-aware cutoff")
    newest: dict[tuple[str, str], ArticleRecord] = {}
    for record in sorted(records, key=lambda item: item.observation_id):
        if not record.usable_at(cutoff):
            continue
        key = (record.source_id, record.canonical_url_hash)
        current = newest.get(key)
        candidate = (record.revision_index, record.first_resolvable_at, record.observation_id)
        if current is None or candidate > (
            current.revision_index,
            current.first_resolvable_at,
            current.observation_id,
        ):
            newest[key] = record
    return tuple(sorted(newest.values(), key=lambda record: record.observation_id))
