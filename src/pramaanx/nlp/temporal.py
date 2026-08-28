"""Time expressions, anchored to publication and left ambiguous where they are.

Two distinctions carry this module.

**The anchor is not the cutoff.** "Yesterday" is interpreted against the
article's own publication time, because that is what the journalist meant.
Whether the article may be *used* is a separate question, decided by
``first_resolvable_at`` against the forecast cutoff, and decided in
:mod:`pramaanx.nlp.pipeline`. Conflating them produces a subtle and expensive
bug: interpreting relative dates against the cutoff would make the same article
mean different things in different backtest folds.

**An article describing the future is normal.** "Forces will be deployed ahead
of polls next week" is a legitimate, useful, non-leaking statement made at
publication time. A pipeline that treats future-tense content as suspicious
would discard exactly the anticipatory reporting a forecasting system wants.
What must never happen is the reverse -- an article that only became readable
*after* the cutoff being admitted -- and that is enforced on the record, not on
its sentences.

Where a date genuinely has two readings, both survive. ``01/03/2026`` is
1 March under Indian convention and 3 January under American, and this module
refuses to choose: it returns ``AMBIGUOUS`` with both interpretations recorded.
Choosing the local convention would be right most of the time, which is what
makes it dangerous -- the errors would be rare, silent and unattributable.
"""

from __future__ import annotations

import re
from datetime import UTC, datetime, timedelta

from pramaanx.nlp.schemas import (
    ResolutionStatus,
    TemporalKind,
    TemporalMention,
    TextSpan,
)

TEMPORAL_VERSION = "nlp-temporal/1.0.0"

_MONTHS: dict[str, int] = {
    "january": 1,
    "jan": 1,
    "february": 2,
    "feb": 2,
    "march": 3,
    "mar": 3,
    "april": 4,
    "apr": 4,
    "may": 5,
    "june": 6,
    "jun": 6,
    "july": 7,
    "jul": 7,
    "august": 8,
    "aug": 8,
    "september": 9,
    "sep": 9,
    "sept": 9,
    "october": 10,
    "oct": 10,
    "november": 11,
    "nov": 11,
    "december": 12,
    "dec": 12,
}

_WEEKDAYS: dict[str, int] = {
    "monday": 0,
    "tuesday": 1,
    "wednesday": 2,
    "thursday": 3,
    "friday": 4,
    "saturday": 5,
    "sunday": 6,
}

_NUMBER_WORDS: dict[str, int] = {
    "one": 1,
    "two": 2,
    "three": 3,
    "four": 4,
    "five": 5,
    "six": 6,
    "seven": 7,
    "eight": 8,
    "nine": 9,
    "ten": 10,
    "eleven": 11,
    "twelve": 12,
    "a": 1,
    "an": 1,
    "couple of": 2,
    "few": 3,
}

#: Phrases that mark an article as recalling rather than reporting. Detected
#: here because they are time expressions; acted on nowhere, because
#: retrospective language is a feature, not a rejection.
_VAGUE_PAST = (
    "last year",
    "years ago",
    "decades ago",
    "in the past",
    "previously",
    "back then",
    "at the time",
    "historically",
    "in those days",
)

_MONTH_ALT = "|".join(sorted(_MONTHS, key=len, reverse=True))
_WEEKDAY_ALT = "|".join(sorted(_WEEKDAYS, key=len, reverse=True))
_NUMBER_ALT = "|".join(sorted(_NUMBER_WORDS, key=len, reverse=True))

_ISO = re.compile(r"\b(\d{4})-(\d{2})-(\d{2})\b")
_NUMERIC = re.compile(r"\b(\d{1,2})[/.-](\d{1,2})[/.-](\d{2,4})\b")
_DAY_MONTH_YEAR = re.compile(
    rf"\b(\d{{1,2}})(?:st|nd|rd|th)?\s+({_MONTH_ALT})\.?\s*,?\s*(\d{{4}})?\b",
    re.IGNORECASE,
)
_MONTH_DAY_YEAR = re.compile(
    rf"\b({_MONTH_ALT})\.?\s+(\d{{1,2}})(?:st|nd|rd|th)?\s*,?\s*(\d{{4}})?\b",
    re.IGNORECASE,
)
_DAY_RANGE = re.compile(
    rf"\b(\d{{1,2}})\s*(?:-|to|and)\s*(\d{{1,2}})\s+({_MONTH_ALT})\.?\s*,?\s*(\d{{4}})?\b",
    re.IGNORECASE,
)
_RELATIVE_DAY = re.compile(r"\b(yesterday|today|tonight|tomorrow)\b", re.IGNORECASE)
_RELATIVE_WEEK = re.compile(
    r"\b(last|next|this|coming|past)\s+(week|month|fortnight)\b", re.IGNORECASE
)
_WEEKDAY = re.compile(rf"\b(last|next|this|coming|on)?\s*({_WEEKDAY_ALT})\b", re.IGNORECASE)
_AGO = re.compile(rf"\b({_NUMBER_ALT}|\d+)\s+(day|week|month|year)s?\s+ago\b", re.IGNORECASE)
_AHEAD = re.compile(
    rf"\bin\s+({_NUMBER_ALT}|\d+)\s+(day|week|month|year)s?(?:'\s*time)?\b", re.IGNORECASE
)
_YEAR = re.compile(r"\bin\s+((?:19|20)\d{2})\b", re.IGNORECASE)
_VAGUE = re.compile("|".join(re.escape(phrase) for phrase in _VAGUE_PAST), re.IGNORECASE)

_UNIT_DAYS = {"day": 1, "week": 7, "fortnight": 14, "month": 30, "year": 365}

#: A mention resolving to more than this far before the anchor is treated as
#: retrospective. Twelve months, so that an anniversary piece is flagged and a
#: reference to last month's incident is not.
_RETROSPECTIVE_DAYS = 365


def _midnight(moment: datetime) -> datetime:
    return datetime(moment.year, moment.month, moment.day, tzinfo=UTC)


def _day_interval(day: datetime) -> tuple[datetime, datetime]:
    start = _midnight(day)
    return start, start + timedelta(days=1)


def _safe_date(year: int, month: int, day: int) -> datetime | None:
    try:
        return datetime(year, month, day, tzinfo=UTC)
    except ValueError:
        return None


def _count(raw: str) -> int | None:
    lowered = raw.strip().casefold()
    if lowered in _NUMBER_WORDS:
        return _NUMBER_WORDS[lowered]
    try:
        return int(lowered)
    except ValueError:
        return None


def _build(
    text: str,
    match: re.Match[str],
    *,
    kind: TemporalKind,
    anchor: datetime,
    start: datetime | None = None,
    end: datetime | None = None,
    status: ResolutionStatus = ResolutionStatus.RESOLVED,
    interpretations: tuple[str, ...] = (),
    retrospective: bool = False,
) -> TemporalMention:
    span = TextSpan.over(text, match.start(), match.end())
    future = bool(start is not None and start > anchor)
    past_enough = bool(end is not None and end < anchor - timedelta(days=_RETROSPECTIVE_DAYS))
    return TemporalMention(
        span=span,
        kind=kind,
        normalized_start=start,
        normalized_end=end,
        resolution_status=status,
        anchor_time=anchor,
        is_future_claim=future,
        is_retrospective=retrospective or past_enough,
        candidate_interpretations=interpretations,
    )


def _iso_interval(start: datetime, end: datetime) -> str:
    return f"{start.date().isoformat()}/{end.date().isoformat()}"


def extract_temporal_mentions(text: str, *, anchor: datetime) -> tuple[TemporalMention, ...]:
    """Every time expression in ``text``, resolved against ``anchor``.

    Overlapping matches are resolved by preferring the longest span, so
    "1 March 2026" is one dated mention rather than a date plus a bare year.
    Output is sorted by position, which makes it deterministic regardless of
    the order the patterns happen to be tried in.
    """
    if anchor.tzinfo is None:
        raise ValueError("temporal extraction requires a timezone-aware anchor")
    anchor = anchor.astimezone(UTC)
    found: list[TemporalMention] = []

    for match in _ISO.finditer(text):
        moment = _safe_date(int(match[1]), int(match[2]), int(match[3]))
        if moment is None:
            continue
        start, end = _day_interval(moment)
        found.append(
            _build(text, match, kind=TemporalKind.ISO_DATE, anchor=anchor, start=start, end=end)
        )

    for match in _NUMERIC.finditer(text):
        found.append(_numeric_mention(text, match, anchor))

    for match in _DAY_RANGE.finditer(text):
        month = _MONTHS[match[3].casefold().rstrip(".")]
        year = int(match[4]) if match[4] else anchor.year
        first = _safe_date(year, month, int(match[1]))
        last = _safe_date(year, month, int(match[2]))
        if first is None or last is None or last < first:
            continue
        found.append(
            _build(
                text,
                match,
                kind=TemporalKind.DATE_RANGE,
                anchor=anchor,
                start=first,
                end=last + timedelta(days=1),
            )
        )

    for pattern, day_group, month_group, year_group in (
        (_DAY_MONTH_YEAR, 1, 2, 3),
        (_MONTH_DAY_YEAR, 2, 1, 3),
    ):
        for match in pattern.finditer(text):
            month = _MONTHS[match[month_group].casefold().rstrip(".")]
            year = int(match[year_group]) if match[year_group] else anchor.year
            moment = _safe_date(year, month, int(match[day_group]))
            if moment is None:
                continue
            start, end = _day_interval(moment)
            found.append(
                _build(
                    text,
                    match,
                    kind=TemporalKind.MONTH_NAME_DATE,
                    anchor=anchor,
                    start=start,
                    end=end,
                )
            )

    for match in _RELATIVE_DAY.finditer(text):
        word = match[1].casefold()
        offset = {"yesterday": -1, "today": 0, "tonight": 0, "tomorrow": 1}[word]
        start, end = _day_interval(anchor + timedelta(days=offset))
        found.append(
            _build(text, match, kind=TemporalKind.RELATIVE_DAY, anchor=anchor, start=start, end=end)
        )

    for match in _RELATIVE_WEEK.finditer(text):
        found.append(_relative_week_mention(text, match, anchor))

    for match in _WEEKDAY.finditer(text):
        mention = _weekday_mention(text, match, anchor)
        if mention is not None:
            found.append(mention)

    for match in _AGO.finditer(text):
        count = _count(match[1])
        if count is None:
            continue
        days = count * _UNIT_DAYS[match[2].casefold()]
        moment = anchor - timedelta(days=days)
        start, end = _day_interval(moment)
        found.append(
            _build(text, match, kind=TemporalKind.OFFSET_AGO, anchor=anchor, start=start, end=end)
        )

    for match in _AHEAD.finditer(text):
        count = _count(match[1])
        if count is None:
            continue
        days = count * _UNIT_DAYS[match[2].casefold()]
        moment = anchor + timedelta(days=days)
        start, end = _day_interval(moment)
        found.append(
            _build(text, match, kind=TemporalKind.OFFSET_AHEAD, anchor=anchor, start=start, end=end)
        )

    for match in _YEAR.finditer(text):
        year = int(match[1])
        start = datetime(year, 1, 1, tzinfo=UTC)
        end = datetime(year + 1, 1, 1, tzinfo=UTC)
        found.append(
            _build(text, match, kind=TemporalKind.YEAR, anchor=anchor, start=start, end=end)
        )

    for match in _VAGUE.finditer(text):
        found.append(
            _build(
                text,
                match,
                kind=TemporalKind.VAGUE_PAST,
                anchor=anchor,
                status=ResolutionStatus.UNRESOLVED,
                retrospective=True,
            )
        )

    return _deduplicate(found)


def _numeric_mention(text: str, match: re.Match[str], anchor: datetime) -> TemporalMention:
    """A slash- or dot-separated date, ambiguous whenever both readings work."""
    first, second = int(match[1]), int(match[2])
    raw_year = int(match[3])
    year = raw_year if raw_year > 99 else 2000 + raw_year

    day_first = _safe_date(year, second, first)
    month_first = _safe_date(year, first, second)

    if day_first is not None and month_first is not None and day_first != month_first:
        # Both conventions produce a valid, different date. Neither is chosen.
        return _build(
            text,
            match,
            kind=TemporalKind.NUMERIC_DATE,
            anchor=anchor,
            status=ResolutionStatus.AMBIGUOUS,
            interpretations=tuple(
                sorted(
                    {
                        _iso_interval(day_first, day_first + timedelta(days=1)),
                        _iso_interval(month_first, month_first + timedelta(days=1)),
                    }
                )
            ),
        )

    resolved = day_first or month_first
    if resolved is None:
        return _build(
            text,
            match,
            kind=TemporalKind.NUMERIC_DATE,
            anchor=anchor,
            status=ResolutionStatus.UNRESOLVED,
        )
    start, end = _day_interval(resolved)
    return _build(text, match, kind=TemporalKind.NUMERIC_DATE, anchor=anchor, start=start, end=end)


def _relative_week_mention(text: str, match: re.Match[str], anchor: datetime) -> TemporalMention:
    qualifier = match[1].casefold()
    span_days = _UNIT_DAYS[match[2].casefold()]
    today = _midnight(anchor)
    if qualifier in {"last", "past"}:
        start, end = today - timedelta(days=span_days), today
    elif qualifier in {"next", "coming"}:
        start, end = today + timedelta(days=1), today + timedelta(days=span_days + 1)
    else:
        start, end = today, today + timedelta(days=span_days)
    return _build(text, match, kind=TemporalKind.RELATIVE_WEEK, anchor=anchor, start=start, end=end)


def _weekday_mention(text: str, match: re.Match[str], anchor: datetime) -> TemporalMention | None:
    """A named weekday, ambiguous unless the text says which one.

    "On Sunday" in a Tuesday article usually means the Sunday just gone -- but
    "usually" is not a basis for asserting a date. Unqualified weekdays are
    returned as ambiguous with both the preceding and the following occurrence,
    so a consumer that has discourse context can choose and one that does not
    cannot be misled.
    """
    qualifier = (match[1] or "").casefold().strip()
    weekday = _WEEKDAYS[match[2].casefold()]
    today = _midnight(anchor)
    back = (today.weekday() - weekday) % 7 or 7
    forward = (weekday - today.weekday()) % 7 or 7
    previous = today - timedelta(days=back)
    following = today + timedelta(days=forward)

    if qualifier in {"last", "past"}:
        return _build(
            text,
            match,
            kind=TemporalKind.WEEKDAY,
            anchor=anchor,
            start=previous,
            end=previous + timedelta(days=1),
        )
    if qualifier in {"next", "coming"}:
        return _build(
            text,
            match,
            kind=TemporalKind.WEEKDAY,
            anchor=anchor,
            start=following,
            end=following + timedelta(days=1),
        )

    return _build(
        text,
        match,
        kind=TemporalKind.WEEKDAY,
        anchor=anchor,
        status=ResolutionStatus.AMBIGUOUS,
        interpretations=(
            _iso_interval(previous, previous + timedelta(days=1)),
            _iso_interval(following, following + timedelta(days=1)),
        ),
    )


def _deduplicate(mentions: list[TemporalMention]) -> tuple[TemporalMention, ...]:
    """Keep the longest mention at each position, then sort by position.

    Longest-wins rather than first-wins so that the result does not depend on
    the order the patterns are applied in -- which is the difference between a
    deterministic extractor and one that happens to be stable today.
    """
    ordered = sorted(
        mentions,
        key=lambda mention: (
            mention.span.start,
            -(mention.span.end - mention.span.start),
            mention.kind.value,
        ),
    )
    kept: list[TemporalMention] = []
    for mention in ordered:
        if any(
            mention.span.start < existing.span.end and existing.span.start < mention.span.end
            for existing in kept
        ):
            continue
        kept.append(mention)
    return tuple(kept)


def anchor_for(published_at: datetime | None, first_resolvable_at: datetime) -> datetime:
    """The linguistic anchor for relative expressions.

    Publication time when the publisher supplied one, because that is what the
    journalist wrote "yesterday" against. Otherwise the first-resolvable time --
    the moment the project could have read it -- which is later and therefore
    conservative: it can only pull a relative date forward, never invent an
    earlier one.
    """
    return (published_at or first_resolvable_at).astimezone(UTC)
