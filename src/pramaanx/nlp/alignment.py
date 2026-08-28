"""Building transformed text that never loses its way back to the original.

Every transformation in this package is written through :class:`AlignmentBuilder`
rather than as a string operation. The difference matters more than it looks.

``text.replace("\\u200b", "")`` is one line and silently shifts every offset
after the first zero-width space. Nothing fails. The pipeline still returns
spans, the spans still validate against the *transformed* text, and the error
only surfaces much later as an LLM quoting a phrase that starts one character
early. Offsets that are wrong by one are worse than offsets that are missing,
because they still look like citations.

So a transformation here cannot drop a character without saying where it was,
and cannot emit one without saying where it came from. The builder makes the
bookkeeping the only way to write the code, rather than a discipline someone
has to remember.
"""

from __future__ import annotations

from collections.abc import Iterator

from pramaanx.nlp.schemas import AlignedTextView, TextSpan


class AlignmentError(ValueError):
    """A transformation produced an alignment that cannot be trusted."""


class AlignmentBuilder:
    """Accumulates transformed text alongside its map back to the original.

    Three ways to add output, and they are exhaustive on purpose:

    * :meth:`emit` -- these characters came from that range of the original;
    * :meth:`emit_unmapped` -- these characters were inserted and have no origin;
    * :meth:`drop` -- that range of the original produced no output.

    There is no fourth way, and in particular no way to append a string without
    saying which of the three it is.
    """

    def __init__(self, original: str, *, transformation: str, version: str) -> None:
        self._original = original
        self._transformation = transformation
        self._version = version
        self._chunks: list[str] = []
        self._starts: list[int | None] = []
        self._ends: list[int | None] = []
        self._dropped: list[TextSpan] = []
        self._consumed = 0

    @property
    def original(self) -> str:
        return self._original

    def emit(self, text: str, source_start: int, source_end: int) -> None:
        """Record that ``text`` derives from ``original[source_start:source_end]``.

        Every emitted character maps to the *whole* source range, not to a
        character within it. That is what makes composition and decomposition
        safe: when two original characters compose into one, mapping the result
        back yields both, and a span quoting it quotes a complete grapheme
        rather than half of one.
        """
        if not text:
            return
        if not 0 <= source_start < source_end <= len(self._original):
            raise AlignmentError(
                f"source range [{source_start}, {source_end}) does not fit an original of "
                f"length {len(self._original)}"
            )
        self._chunks.append(text)
        self._starts.extend([source_start] * len(text))
        self._ends.extend([source_end] * len(text))
        self._consumed = max(self._consumed, source_end)

    def emit_unmapped(self, text: str) -> None:
        """Record inserted characters with no counterpart in the original.

        Rare and deliberately awkward to reach. Inserted characters cannot
        appear in an evidence span, because there is nothing in the source to
        quote, and :meth:`AlignedTextView.to_original_span` will refuse a range
        made only of them.
        """
        if not text:
            return
        self._chunks.append(text)
        self._starts.extend([None] * len(text))
        self._ends.extend([None] * len(text))

    def drop(self, source_start: int, source_end: int) -> None:
        """Record that a range of the original produced no output.

        The dropped range is kept. A reviewer asking "why is there a gap in the
        offsets here?" gets an answer, and a test can assert that removing a
        zero-width character removed exactly that character.
        """
        if source_end <= source_start:
            return
        if not 0 <= source_start < source_end <= len(self._original):
            raise AlignmentError(
                f"dropped range [{source_start}, {source_end}) does not fit an original of "
                f"length {len(self._original)}"
            )
        self._dropped.append(TextSpan.over(self._original, source_start, source_end))
        self._consumed = max(self._consumed, source_end)

    def build(self) -> AlignedTextView:
        """Freeze the accumulated output into a validated view."""
        transformed = "".join(self._chunks)
        if len(self._starts) != len(transformed):
            raise AlignmentError(
                f"builder accumulated {len(self._starts)} alignment entries for "
                f"{len(transformed)} characters; a chunk was appended without one"
            )
        return AlignedTextView(
            original_text=self._original,
            transformed_text=transformed,
            transformed_to_original=tuple(self._starts),
            transformed_to_original_end=tuple(self._ends),
            transformation=self._transformation,
            transformation_version=self._version,
            removed_spans=tuple(self._dropped),
        )


def identity_view(text: str, *, transformation: str, version: str) -> AlignedTextView:
    """A view that changes nothing, aligned one-to-one.

    Used where a transformation does not apply -- Latin text needing no
    transliteration, for instance -- so that downstream code always has a view
    to work with and never special-cases ``None`` into a bare string.
    """
    builder = AlignmentBuilder(text, transformation=transformation, version=version)
    for index, char in enumerate(text):
        builder.emit(char, index, index + 1)
    return builder.build()


#: Unicode general categories that continue a cluster rather than starting one:
#: non-spacing, spacing-combining and enclosing marks.
_MARK_CATEGORIES = frozenset({"Mn", "Mc", "Me"})


def combining_clusters(text: str) -> Iterator[tuple[int, int, str]]:
    """Split ``text`` into ``(start, end, cluster)`` at mark boundaries.

    A cluster is a base character plus every mark that follows it. Unicode
    normalisation is closed over such clusters -- normalising one never reaches
    outside it -- which is what lets normalisation run cluster by cluster with
    exact alignment instead of over the whole string with none.

    Membership is decided by *category* as well as by combining class, and the
    difference is not academic. Indic spacing vowel signs have canonical
    combining class 0 while being marks: Malayalam ``\\u0d4b`` decomposes to
    ``\\u0d47`` + ``\\u0d3e``, and both pieces report ``combining() == 0``. A
    boundary rule based on combining class alone therefore splits them into
    separate clusters, NFC cannot recompose across the split, and decomposed
    Malayalam, Tamil, Kannada, Bengali and Assamese silently fail to reach their
    canonical form -- so the same sentence delivered by two feeds would hash
    differently and count as two stories.

    Uses ``unicodedata`` rather than a grapheme library, so the package has no
    dependency to install and no data file to download.
    """
    import unicodedata

    if not text:
        return
    start = 0
    for index in range(1, len(text)):
        char = text[index]
        if unicodedata.combining(char) == 0 and unicodedata.category(char) not in _MARK_CATEGORIES:
            yield start, index, text[start:index]
            start = index
    yield start, len(text), text[start:]


def map_span(view: AlignedTextView, start: int, end: int) -> TextSpan | None:
    """Map a transformed-text range back to an original span, or ``None``."""
    return view.to_original_span(start, end)


def require_span(view: AlignedTextView, start: int, end: int) -> TextSpan:
    """Map a range back, failing loudly when it cannot be grounded.

    The pipeline uses this wherever an ungrounded span would be a bug rather
    than a possibility, so that the failure is an exception at the point of
    origin instead of a missing mention three stages later.
    """
    span = view.to_original_span(start, end)
    if span is None:
        raise AlignmentError(
            f"transformed range [{start}, {end}) maps to no original characters. A span "
            "that cannot be grounded in the source must not become evidence."
        )
    return span
