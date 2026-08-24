"""Adapters normalising heterogeneous sources into ``Document`` streams.

Gap G8 is that the surveyed systems each consume a single source, which is what
makes them brittle in deployment. The fix is not clever: it is a common document
type plus one adapter per source, so fusion is a list concatenation and
``source_diversity`` becomes a feature the model can use.

    documents = load_csv("news.csv") + load_gdelt_gkg("gkg.csv") + load_jsonl("blogs.jsonl")

Three sources are covered here:

``load_csv`` / ``load_jsonl``
    Generic tabular/line-delimited text with configurable column names. This is
    the path most users will actually take.

``load_gdelt_gkg``
    GDELT 2.0 Global Knowledge Graph export. Column indices follow the published
    GKG 2.1 layout.

``load_acled``
    ACLED conflict event export, used for **labels** rather than documents --
    ACLED is the realised-outcome catalogue that ``build_labels`` turns into the
    ground truth the backtester scores against (gap G6).

None of these were runnable in the environment this repo was developed in, which
had no outbound network. They are written against the published schemas and are
unit-tested against small fixtures, not against live downloads. Treat them as a
starting point and check the column layout against your export before trusting
a large run.
"""

from __future__ import annotations

import csv
import datetime as _dt
import json
from collections import defaultdict
from pathlib import Path
from typing import Iterable, Iterator, Sequence

from .schema import Date, Document


def _parse_date(value: str) -> Date | None:
    value = (value or "").strip()
    if not value:
        return None
    for fmt in ("%Y-%m-%d", "%Y%m%d", "%d/%m/%Y", "%m/%d/%Y", "%Y-%m-%dT%H:%M:%S"):
        try:
            return _dt.datetime.strptime(value[: len(fmt) + 2].strip(), fmt).date()
        except ValueError:
            continue
    try:  # GDELT-style YYYYMMDDHHMMSS
        return _dt.datetime.strptime(value[:8], "%Y%m%d").date()
    except ValueError:
        return None


def load_csv(
    path: str | Path,
    *,
    text_col: str = "text",
    date_col: str = "date",
    region_col: str = "region",
    id_col: str | None = None,
    source: str = "csv",
    encoding: str = "utf-8",
) -> list[Document]:
    """Load documents from a delimited file with named columns."""
    docs: list[Document] = []
    with open(path, "r", encoding=encoding, newline="") as fh:
        for i, row in enumerate(csv.DictReader(fh)):
            date = _parse_date(row.get(date_col, ""))
            text = (row.get(text_col) or "").strip()
            if date is None or not text:
                continue
            docs.append(
                Document(
                    doc_id=str(row.get(id_col) if id_col else f"{source}:{i}"),
                    text=text,
                    date=date,
                    region=(row.get(region_col) or "unknown").strip(),
                    source=source,
                    meta={k: v for k, v in row.items()
                          if k not in {text_col, date_col, region_col}},
                )
            )
    return docs


def load_jsonl(
    path: str | Path,
    *,
    text_key: str = "text",
    date_key: str = "date",
    region_key: str = "region",
    id_key: str | None = None,
    source: str = "jsonl",
) -> list[Document]:
    """Load documents from a line-delimited JSON file."""
    docs: list[Document] = []
    with open(path, "r", encoding="utf-8") as fh:
        for i, line in enumerate(fh):
            line = line.strip()
            if not line:
                continue
            try:
                row = json.loads(line)
            except json.JSONDecodeError:
                continue
            date = _parse_date(str(row.get(date_key, "")))
            text = str(row.get(text_key, "")).strip()
            if date is None or not text:
                continue
            docs.append(
                Document(
                    doc_id=str(row.get(id_key) if id_key else f"{source}:{i}"),
                    text=text,
                    date=date,
                    region=str(row.get(region_key, "unknown")),
                    source=source,
                    meta={k: v for k, v in row.items()
                          if k not in {text_key, date_key, region_key}},
                )
            )
    return docs


# GDELT GKG 2.1 column positions (tab-separated, no header).
_GKG_DATE, _GKG_ID, _GKG_SOURCE = 1, 0, 3
_GKG_LOCATIONS, _GKG_THEMES, _GKG_EXTRAS = 9, 7, 26


def load_gdelt_gkg(
    path: str | Path,
    *,
    region_from: str = "country",
    max_rows: int | None = None,
) -> list[Document]:
    """Load a GDELT 2.0 GKG export.

    GKG rows carry themes and locations rather than article bodies, so the
    "text" assembled here is a themes-and-locations pseudo-document. That is
    weaker input than real article text -- the extractor sees keywords, not
    sentences -- and is why ``load_csv`` over a corpus with bodies is preferred
    where one is available.
    """
    docs: list[Document] = []
    with open(path, "r", encoding="utf-8", errors="replace", newline="") as fh:
        for i, row in enumerate(csv.reader(fh, delimiter="\t", quoting=csv.QUOTE_NONE)):
            if max_rows is not None and i >= max_rows:
                break
            if len(row) <= _GKG_LOCATIONS:
                continue
            date = _parse_date(row[_GKG_DATE])
            if date is None:
                continue
            themes = [t.split(",")[0] for t in row[_GKG_THEMES].split(";") if t][:40]
            locations = [seg.split("#") for seg in row[_GKG_LOCATIONS].split(";") if seg]
            region = "unknown"
            for parts in locations:
                if region_from == "country" and len(parts) > 2 and parts[2]:
                    region = parts[2]
                    break
                if region_from == "name" and len(parts) > 1 and parts[1]:
                    region = parts[1]
                    break
            text = ". ".join(t.replace("_", " ").lower() for t in themes)
            if not text:
                continue
            docs.append(
                Document(
                    doc_id=row[_GKG_ID] or f"gkg:{i}",
                    text=text,
                    date=date,
                    region=region,
                    source=f"gdelt:{row[_GKG_SOURCE] if len(row) > _GKG_SOURCE else 'na'}",
                    meta={"n_themes": len(themes)},
                )
            )
    return docs


def load_acled_events(
    path: str | Path,
    *,
    date_col: str = "event_date",
    region_col: str = "admin1",
    type_col: str = "event_type",
    keep_types: Sequence[str] | None = ("Protests", "Riots"),
) -> dict[tuple[str, Date], int]:
    """Load realised events from an ACLED export as ``{(region, date): 1}``.

    This is the ground truth, not a feature. Keeping it strictly separate from
    the document stream is what makes the backtest an honest test against events
    that actually occurred (gap G6).
    """
    events: dict[tuple[str, Date], int] = {}
    with open(path, "r", encoding="utf-8", newline="") as fh:
        for row in csv.DictReader(fh):
            date = _parse_date(row.get(date_col, ""))
            region = (row.get(region_col) or "").strip()
            if date is None or not region:
                continue
            if keep_types and (row.get(type_col) or "").strip() not in keep_types:
                continue
            events[(region, date)] = 1
    return events


def build_labels(
    events: dict[tuple[str, Date], int],
    regions: Iterable[str],
    origins: Iterable[Date],
    horizon_days: int,
) -> dict[tuple[str, Date], int]:
    """Turn a realised-event catalogue into forecasting labels.

    ``label[(r, origin)] = 1`` iff any event occurred in ``[origin, origin + h)``.
    """
    by_region: dict[str, set[Date]] = defaultdict(set)
    for (region, date) in events:
        by_region[region].add(date)
    labels: dict[tuple[str, Date], int] = {}
    for region in regions:
        dates = by_region.get(region, set())
        for origin in origins:
            labels[(region, origin)] = int(
                any(origin + _dt.timedelta(days=k) in dates for k in range(horizon_days))
            )
    return labels


def deduplicate(documents: Sequence[Document], shingle: int = 12) -> list[Document]:
    """Drop near-identical documents that differ only by source.

    Wire copy is republished verbatim across outlets, which inflates every
    volume feature and lets one story masquerade as corroboration. This is a
    crude first pass -- exact match on a normalised word shingle -- and is *not*
    the entity-level cross-source resolution that gap G8 really calls for. See
    ``docs/01-survey-gap-analysis.md`` section 4.
    """
    seen: set[tuple[str, Date, str]] = set()
    out: list[Document] = []
    for doc in documents:
        words = doc.text.lower().split()
        key = (doc.region, doc.date, " ".join(words[:shingle]))
        if key in seen:
            continue
        seen.add(key)
        out.append(doc)
    return out


def iter_batches(documents: Sequence[Document], size: int = 512) -> Iterator[list[Document]]:
    """Chunk documents for shard-parallel extraction and embedding (gap G1)."""
    for i in range(0, len(documents), size):
        yield list(documents[i : i + size])
