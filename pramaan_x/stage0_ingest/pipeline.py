"""Stage 0: remove wasted work before any semantic model runs."""

from __future__ import annotations

import time
from dataclasses import dataclass, field
from typing import Any

from ..config import Stage0Config
from ..data.synth import SOURCE_TO_FAMILY
from ..types import Document
from .clean import CleanReport, clean_documents
from .dedup import Deduplicator, DedupReport, apply_dedup
from .validate import ValidationReport, validate_timestamps


@dataclass
class Stage0Result:
    documents: list[Document]
    validation: ValidationReport
    cleaning: CleanReport
    dedup: DedupReport
    elapsed_s: float = 0.0
    all_documents: list[Document] = field(default_factory=list)

    def summary(self) -> dict[str, Any]:
        return {
            "elapsed_s": round(self.elapsed_s, 2),
            "validation": self.validation.summary(),
            "cleaning": self.cleaning.summary(),
            "dedup": self.dedup.summary(),
            "surviving": len(self.documents),
            "work_avoided": round(
                1 - len(self.documents) / max(self.validation.n_input, 1), 4
            ),
        }


def run_stage0(docs: list[Document], cfg: Stage0Config | None = None,
               *, family_map: dict[str, str] | None = None) -> Stage0Result:
    cfg = cfg or Stage0Config()
    t0 = time.perf_counter()

    docs, validation = validate_timestamps(
        docs,
        require_timestamp=cfg.require_timestamp,
        max_future_skew_hours=cfg.max_future_skew_hours,
    )
    docs, cleaning = clean_documents(
        docs,
        strip=cfg.strip_boilerplate,
        min_tokens=cfg.min_tokens,
        family_map=family_map if family_map is not None else SOURCE_TO_FAMILY,
    )
    dedup = Deduplicator(
        permutations=cfg.minhash_permutations,
        bands=cfg.minhash_bands,
        threshold=cfg.minhash_threshold,
        simhash_bits=cfg.simhash_bits,
        simhash_threshold=cfg.simhash_hamming_threshold,
    ).run(docs) if cfg.exact_dedup else DedupReport(n_input=len(docs))

    canonical = apply_dedup(docs, dedup) if cfg.exact_dedup else docs
    return Stage0Result(
        documents=canonical, validation=validation, cleaning=cleaning,
        dedup=dedup, elapsed_s=time.perf_counter() - t0, all_documents=docs,
    )
