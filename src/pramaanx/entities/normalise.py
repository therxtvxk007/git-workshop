"""Deterministic surface-form normalisation.

Entity resolution begins by deciding when two strings *could* denote the same
thing. That decision has to be reproducible: the same corpus must produce the
same blocks and the same clusters on every machine and every run, or a
reproducibility test cannot distinguish a modelling change from a hash-order
accident.

Everything here is therefore pure, total and locale-independent. There is no
learned component, no network lookup and no gazetteer download. A gazetteer is
a legitimate later addition, but it is a *source* with its own licence and its
own availability date, so it enters through the connector path and not through
a helper that quietly reaches for the filesystem.
"""

from __future__ import annotations

import re
import unicodedata
from collections.abc import Iterable

#: Honorifics and role prefixes that carry no identity. Stripped only when they
#: lead the string: "President Mandela" and "Mandela" are the same person, but
#: "The President Hotel" is not "Hotel".
LEADING_TITLES: frozenset[str] = frozenset(
    {
        "adm",
        "admiral",
        "brig",
        "brigadier",
        "capt",
        "captain",
        "cmdr",
        "col",
        "colonel",
        "dr",
        "gen",
        "general",
        "gov",
        "governor",
        "hon",
        "lieutenant",
        "lt",
        "maj",
        "major",
        "minister",
        "mr",
        "mrs",
        "ms",
        "pres",
        "president",
        "prof",
        "sen",
        "senator",
        "sgt",
        "shri",
        "sir",
        "smt",
    }
)

#: Organisational suffixes that survive translation and abbreviation badly.
#: Stripped only in trailing position, for the same reason as above.
TRAILING_SUFFIXES: frozenset[str] = frozenset(
    {
        "co",
        "corp",
        "corporation",
        "gmbh",
        "inc",
        "limited",
        "llc",
        "ltd",
        "nv",
        "plc",
        "pvt",
        "sa",
    }
)

#: Tokens that are pure connective tissue. Dropped from the token set used for
#: similarity, but never from the canonical display name.
NOISE_TOKENS: frozenset[str] = frozenset({"and", "de", "der", "of", "the", "van", "von"})

_PUNCTUATION = re.compile(r"[^\w\s]+", flags=re.UNICODE)
_WHITESPACE = re.compile(r"\s+")


def strip_accents(text: str) -> str:
    """Fold diacritics onto their base characters.

    NFKD then a combining-mark filter, so that "Seleka" with and without its
    accents lands in the same block. This is deliberately aggressive:
    over-merging at the blocking stage is recoverable because the similarity
    test still has to agree, whereas under-merging is invisible -- the two
    records simply never get compared.
    """
    decomposed = unicodedata.normalize("NFKD", text)
    return "".join(char for char in decomposed if not unicodedata.combining(char))


def normalise_name(raw: str | None) -> str:
    """Reduce a surface form to its comparison key.

    Returns the empty string for input that carries no identity at all, which
    callers treat as "not resolvable" rather than as an entity named "".
    """
    if not raw:
        return ""
    folded = strip_accents(str(raw)).casefold()
    folded = _PUNCTUATION.sub(" ", folded)
    tokens = [token for token in _WHITESPACE.split(folded) if token]
    while tokens and tokens[0] in LEADING_TITLES:
        tokens.pop(0)
    while tokens and tokens[-1] in TRAILING_SUFFIXES:
        tokens.pop()
    return " ".join(tokens)


#: Endings that look plural but are not. Stripping the trailing "s" from any of
#: these mangles the word: "Congress" is not "Congres", "Belarus" is not
#: "Belaru", "analysis" is not "analysi".
_NON_PLURAL_ENDINGS: tuple[str, ...] = ("ss", "us", "is", "as", "os")

#: Endings where the plural marker is "es" rather than "s".
_ES_PLURAL_ENDINGS: tuple[str, ...] = ("ches", "shes", "xes", "zes", "ses")

#: Below this length a trailing "s" is more likely part of the word than a
#: plural marker, and the cost of being wrong is a false merge.
_MIN_STEM_LENGTH = 4


def stem_token(token: str) -> str:
    """Strip inflectional endings, conservatively.

    Blocking is character-based (a four-character prefix) but scoring was
    purely token-set based, so "Maoists" and "Maoist" landed in the same block
    and then scored 0.0 against each other -- compared, and found to have no
    tokens in common. Stemming closes that gap at the only place it was open.

    Deliberately *not* a Porter stemmer and deliberately not edit distance. A
    general character-similarity fallback scores "Iran" against "Iraq" at 0.75,
    which clears the merge threshold and silently fuses two countries. Handling
    only the plural and agentive endings costs recall on irregular forms and
    cannot make that class of mistake.
    """
    if len(token) < _MIN_STEM_LENGTH:
        return token
    if token.endswith(_NON_PLURAL_ENDINGS):
        return token
    if token.endswith("ies") and len(token) > _MIN_STEM_LENGTH:
        return f"{token[:-3]}y"
    if token.endswith(_ES_PLURAL_ENDINGS):
        return token[:-2]
    if token.endswith("s"):
        return token[:-1]
    return token


def name_tokens(raw: str | None) -> tuple[str, ...]:
    """Content tokens of a name, stemmed and sorted, with connectives removed.

    Sorted because word order is not identity: "Ministry of Home Affairs" and
    "Home Affairs Ministry" are the same body. Deduplicated because a repeated
    token should not inflate the overlap score. Stemmed because inflection is
    not identity either, and every caller here compares token *sets*.
    """
    normalised = normalise_name(raw)
    if not normalised:
        return ()
    tokens = {
        stem_token(token) for token in normalised.split(" ") if token and token not in NOISE_TOKENS
    }
    return tuple(sorted(tokens))


def blocking_keys(raw: str | None) -> tuple[str, ...]:
    """Candidate blocking keys for a name.

    Two records are only ever compared if they share a key, so the keys decide
    what resolution is *able* to find. Three complementary keys are emitted:

    * the first four characters of each content token -- catches inflection and
      transliteration drift ("Maoist" against "Maoists");
    * the sorted token initials -- catches abbreviation ("CPI" against
      "Communist Party of India");
    * the full normalised string -- catches what the other two miss when a name
      is a single short token.

    Emitting several keys per record means a pair can be proposed more than
    once. The caller deduplicates pairs, so this costs comparisons rather than
    correctness.
    """
    tokens = name_tokens(raw)
    if not tokens:
        return ()
    keys = {token[:4] for token in tokens if len(token) >= 2}
    initials = "".join(sorted(token[0] for token in tokens))
    if len(initials) >= 2:
        keys.add(initials)
    keys.add(normalise_name(raw))
    return tuple(sorted(key for key in keys if key))


def jaccard(left: Iterable[str], right: Iterable[str]) -> float:
    """Set overlap, with the empty case defined as 0.0.

    Defining the empty case as 0.0 rather than 1.0 matters: two records that
    both normalise to nothing are not evidence of the same entity, they are two
    failures to parse, and they must not be merged into one confident cluster.
    """
    left_set, right_set = set(left), set(right)
    if not left_set or not right_set:
        return 0.0
    intersection = len(left_set & right_set)
    if not intersection:
        return 0.0
    return intersection / len(left_set | right_set)


def containment(left: Iterable[str], right: Iterable[str]) -> float:
    """Fraction of the smaller token set contained in the larger.

    Jaccard punishes the abbreviation case exactly where it should not:
    {"cpi"} against {"communist", "party", "india"} scores 0, yet one is
    plainly a short form of the other once the initials key has proposed the
    pair. Containment recovers that without loosening Jaccard generally.
    """
    left_set, right_set = set(left), set(right)
    if not left_set or not right_set:
        return 0.0
    smaller, larger = sorted((left_set, right_set), key=len)
    return len(smaller & larger) / len(smaller)


def initials_match(left: str | None, right: str | None) -> bool:
    """Does one name reduce to the other name's token initials?

    Kept separate from the numeric scores because it is a categorical fact, not
    a degree of similarity, and because it is the one rule that can fire on a
    pair with zero token overlap.
    """
    left_tokens, right_tokens = name_tokens(left), name_tokens(right)
    if not left_tokens or not right_tokens:
        return False
    for single, multi in ((left_tokens, right_tokens), (right_tokens, left_tokens)):
        # Initials are compared as a sorted set because name_tokens() has
        # already discarded word order.
        if (
            len(single) == 1
            and len(multi) >= 2
            and single[0] == "".join(sorted(token[0] for token in multi))
        ):
            return True
    return False


def similarity(left: str | None, right: str | None) -> float:
    """Composite name similarity in [0, 1].

    The maximum of three views rather than a weighted sum: each view is a
    sufficient reason to propose a merge on its own, and averaging them would
    let a strong signal be diluted by two irrelevant ones.
    """
    left_tokens, right_tokens = name_tokens(left), name_tokens(right)
    if not left_tokens or not right_tokens:
        return 0.0
    if left_tokens == right_tokens:
        return 1.0
    scores = [jaccard(left_tokens, right_tokens), containment(left_tokens, right_tokens)]
    if initials_match(left, right):
        scores.append(0.9)
    return max(scores)


def shingles(text: str, width: int = 5) -> frozenset[str]:
    """Token shingles, used to detect one wire story reprinted many times.

    Word-level rather than character-level: a syndicated rewrite keeps whole
    phrases and changes the headline, so word runs survive where character
    n-grams would drift on the first edit.

    Texts shorter than ``width`` tokens degrade to the single full-token tuple
    rather than to the empty set, so that two identical short spans still match
    instead of silently scoring 0.0 against each other.
    """
    if width < 1:
        raise ValueError(f"shingle width must be positive, got {width}")
    tokens = [token for token in _WHITESPACE.split(normalise_name(text)) if token]
    if not tokens:
        return frozenset()
    if len(tokens) <= width:
        return frozenset({" ".join(tokens)})
    return frozenset(
        " ".join(tokens[index : index + width]) for index in range(len(tokens) - width + 1)
    )
