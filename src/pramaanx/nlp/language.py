"""Which language a document is probably in, said with the right hedging.

Script is observable; language is inferred. This module never pretends
otherwise. Devanagari carries Hindi *and* Marathi; Bengali script carries
Bengali *and* Assamese. A detector that resolves those to the larger language
by default will label Marathi articles Hindi, and every per-language coverage
number computed afterwards will be confidently wrong in a way nobody notices --
because the wrong answer is the plausible one.

So the script-based fallback here returns ``ambiguous=True`` with both
candidates whenever the script does not determine the language, and a caller
that needs a single answer has to supply a real detector through
:class:`LanguageDetector`.

Nothing in this module downloads anything, at import or at call time. A
statistical backend is injected by the caller, which is what keeps the offline
test suite offline and keeps ``import pramaanx.nlp`` free of side effects.
"""

from __future__ import annotations

import re
from typing import Protocol, runtime_checkable

from pramaanx.nlp.schemas import LanguageAssessment
from pramaanx.nlp.script import SCRIPT_UNKNOWN, detect_scripts, dominant_script

LANGUAGE_VERSION = "nlp-language/1.0.0"

#: The languages WP2 undertakes to *represent*. Representing a language means
#: detecting its script, normalising it without damage, segmenting it and
#: carrying its text through the pipeline intact.
#:
#: It does NOT mean equal extraction accuracy. Temporal, actor and location
#: extraction are built on English and Devanagari cues and have been measured on
#: neither; see ``docs/integration/wp02_multilingual_nlp.md``. Claiming parity
#: across thirteen languages on the strength of a passing test suite would be
#: exactly the kind of unmeasured claim this project exists to avoid.
SUPPORTED_LANGUAGES: tuple[str, ...] = (
    "as",  # Assamese
    "bn",  # Bengali
    "en",  # English
    "gu",  # Gujarati
    "hi",  # Hindi
    "kn",  # Kannada
    "ml",  # Malayalam
    "mr",  # Marathi
    "or",  # Odia
    "pa",  # Punjabi
    "ta",  # Tamil
    "te",  # Telugu
    "ur",  # Urdu
)

#: Which languages each script can carry, within this project's scope.
#: A script mapping to more than one language yields an ambiguous assessment,
#: always, regardless of which language is more common.
SCRIPT_TO_LANGUAGES: dict[str, tuple[str, ...]] = {
    "Deva": ("hi", "mr"),
    "Beng": ("bn", "as"),
    "Taml": ("ta",),
    "Telu": ("te",),
    "Knda": ("kn",),
    "Mlym": ("ml",),
    "Gujr": ("gu",),
    "Guru": ("pa",),
    "Orya": ("or",),
    "Arab": ("ur",),
    "Latn": ("en",),
}

#: A small closed set of high-frequency English function words. Used only to
#: separate English from romanised Indian-language text, both of which are
#: Latin script. Deliberately tiny and deliberately not a language model.
_ENGLISH_MARKERS = frozenset(
    {
        "a",
        "an",
        "and",
        "are",
        "as",
        "at",
        "been",
        "but",
        "by",
        "for",
        "from",
        "had",
        "has",
        "have",
        "in",
        "is",
        "it",
        "of",
        "on",
        "said",
        "that",
        "the",
        "to",
        "was",
        "were",
        "which",
        "with",
    }
)

_WORD = re.compile(r"[A-Za-z]+")

#: Below this share of recognised English function words, Latin-script text is
#: reported as ambiguous rather than as English. Romanised Hindi ("police ne
#: bataya ki") is Latin script and is not English, and calling it English would
#: send it to an English-only extractor that finds nothing.
_ENGLISH_MARKER_SHARE = 0.12


@runtime_checkable
class LanguageDetector(Protocol):
    """A source of language assessments.

    Deliberately narrow. Anything that can look at text and answer with a
    :class:`LanguageAssessment` qualifies, including a statistical model the
    caller loads itself. This package never constructs one, so no import of
    :mod:`pramaanx.nlp` can trigger a download.
    """

    name: str
    version: str

    def detect(self, text: str) -> LanguageAssessment: ...


class ScriptHeuristicDetector:
    """The deterministic fallback: script first, hedging where script is silent.

    This is not a language identifier competing with a trained model. It is the
    floor: it will not be wrong about the script, it will not invent a language
    the script cannot carry, and where the script carries several it says so
    rather than choosing.
    """

    name = "script_heuristic"
    version = LANGUAGE_VERSION

    def __init__(self, *, minimum_share: float = 0.05) -> None:
        self._minimum_share = minimum_share

    def detect(self, text: str) -> LanguageAssessment:
        scripts = detect_scripts(text, minimum_share=self._minimum_share)
        if not scripts:
            return LanguageAssessment(
                language_code=None,
                script_codes=(),
                confidence=None,
                ambiguous=False,
                backend=self.name,
                backend_version=self.version,
            )

        primary = dominant_script(text)
        if primary == SCRIPT_UNKNOWN:
            return LanguageAssessment(
                language_code=None,
                script_codes=scripts,
                confidence=None,
                ambiguous=False,
                backend=self.name,
                backend_version=self.version,
            )

        candidates = SCRIPT_TO_LANGUAGES.get(primary, ())
        if not candidates:
            # A script outside the project's scope. Reported as unknown with the
            # script preserved, never squeezed into the nearest supported
            # language.
            return LanguageAssessment(
                language_code=None,
                script_codes=scripts,
                confidence=None,
                ambiguous=False,
                backend=self.name,
                backend_version=self.version,
            )

        if primary == "Latn":
            return self._assess_latin(text, scripts)

        if len(candidates) == 1:
            # The script determines the language within this project's scope.
            # Confidence is capped below 1.0: the scope is an assumption, and a
            # Nepali article in Devanagari would still be outside it.
            return LanguageAssessment(
                language_code=candidates[0],
                script_codes=scripts,
                confidence=0.9,
                ambiguous=False,
                candidate_language_codes=(candidates[0],),
                backend=self.name,
                backend_version=self.version,
            )

        return LanguageAssessment(
            language_code=None,
            script_codes=scripts,
            confidence=None,
            ambiguous=True,
            candidate_language_codes=tuple(sorted(candidates)),
            backend=self.name,
            backend_version=self.version,
        )

    def _assess_latin(self, text: str, scripts: tuple[str, ...]) -> LanguageAssessment:
        words = [word.lower() for word in _WORD.findall(text)]
        if not words:
            return LanguageAssessment(
                language_code=None,
                script_codes=scripts,
                confidence=None,
                ambiguous=False,
                backend=self.name,
                backend_version=self.version,
            )
        share = sum(1 for word in words if word in _ENGLISH_MARKERS) / len(words)
        if share >= _ENGLISH_MARKER_SHARE:
            return LanguageAssessment(
                language_code="en",
                script_codes=scripts,
                confidence=min(0.95, 0.5 + share),
                ambiguous=False,
                candidate_language_codes=("en",),
                backend=self.name,
                backend_version=self.version,
            )
        # Latin script without English function words: most often romanised
        # Indian-language text. Which language it romanises is not knowable
        # from the script, so it stays open.
        return LanguageAssessment(
            language_code=None,
            script_codes=scripts,
            confidence=None,
            ambiguous=True,
            candidate_language_codes=("en", "hi", "mr"),
            backend=self.name,
            backend_version=self.version,
        )


def assess_language(
    text: str,
    *,
    detector: LanguageDetector | None = None,
    declared_language: str | None = None,
) -> LanguageAssessment:
    """Assess ``text``, optionally through an injected backend.

    ``declared_language`` is what the source said the article was, from WP1's
    registry or feed metadata. It is used only to *disambiguate* -- to pick
    among candidates the script already admits -- and never to override an
    assessment or to introduce a language the script cannot carry. A feed that
    mislabels its own Marathi section as Hindi should not be able to relabel
    Tamil.
    """
    backend = detector or ScriptHeuristicDetector()
    assessment = backend.detect(text)
    if declared_language is None or not assessment.ambiguous:
        return assessment
    if declared_language not in assessment.candidate_language_codes:
        return assessment
    return assessment.model_copy(
        update={
            "language_code": declared_language,
            "ambiguous": False,
            "candidate_language_codes": (declared_language,),
            "confidence": 0.7,
            "backend": f"{assessment.backend}+declared",
        }
    )
