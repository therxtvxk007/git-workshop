"""Tests for the source adapters and label construction."""

import datetime as dt
import json

import pytest

from evpred.adapters import (
    _parse_date,
    build_labels,
    deduplicate,
    iter_batches,
    load_acled_events,
    load_csv,
    load_gdelt_gkg,
    load_jsonl,
)
from evpred.schema import Document


@pytest.fixture
def csv_file(tmp_path):
    path = tmp_path / "news.csv"
    path.write_text(
        "date,region,text,outlet\n"
        "2024-01-05,north,The union threatened a strike.,wire\n"
        "2024-01-06,south,Police detained demonstrators.,daily\n"
        "not-a-date,north,Should be skipped.,wire\n"
        "2024-01-07,north,,wire\n",
        encoding="utf-8",
    )
    return path


def test_load_csv_reads_rows_and_skips_bad_ones(csv_file):
    docs = load_csv(csv_file)
    assert len(docs) == 2                     # bad date and empty text dropped
    assert docs[0].date == dt.date(2024, 1, 5)
    assert docs[0].region == "north"
    assert docs[0].meta["outlet"] == "wire"
    assert docs[0].source == "csv"


def test_load_jsonl_reads_rows_and_skips_bad_ones(tmp_path):
    path = tmp_path / "blogs.jsonl"
    path.write_text(
        json.dumps({"date": "2024-02-01", "region": "east", "text": "Riots erupted."}) + "\n"
        + "{not valid json}\n"
        + json.dumps({"date": "2024-02-02", "region": "east", "text": ""}) + "\n",
        encoding="utf-8",
    )
    docs = load_jsonl(path)
    assert len(docs) == 1
    assert docs[0].region == "east"


def test_date_parsing_accepts_the_documented_formats():
    assert _parse_date("2024-03-05") == dt.date(2024, 3, 5)
    assert _parse_date("20240305") == dt.date(2024, 3, 5)
    assert _parse_date("20240305123000") == dt.date(2024, 3, 5)     # GDELT
    assert _parse_date("2024-03-05T11:22:33") == dt.date(2024, 3, 5)
    assert _parse_date("") is None
    assert _parse_date("garbage") is None


def test_load_gdelt_gkg_builds_pseudo_documents(tmp_path):
    path = tmp_path / "gkg.csv"
    row = [""] * 27
    row[0], row[1], row[3] = "rec-1", "20240115120000", "reuters.com"
    row[7] = "PROTEST,10;ARREST,42"
    row[9] = "4#Capital City#AR#AR01#-34#-58#12345"
    path.write_text("\t".join(row) + "\n", encoding="utf-8")
    docs = load_gdelt_gkg(path)
    assert len(docs) == 1
    assert docs[0].date == dt.date(2024, 1, 15)
    assert docs[0].region == "AR"
    assert "protest" in docs[0].text
    assert docs[0].source.startswith("gdelt:")


def test_load_acled_events_filters_by_type(tmp_path):
    path = tmp_path / "acled.csv"
    path.write_text(
        "event_date,admin1,event_type\n"
        "2024-01-10,North,Protests\n"
        "2024-01-11,North,Battles\n"
        "2024-01-12,South,Riots\n",
        encoding="utf-8",
    )
    events = load_acled_events(path)
    assert ("North", dt.date(2024, 1, 10)) in events
    assert ("North", dt.date(2024, 1, 11)) not in events   # Battles filtered out
    assert ("South", dt.date(2024, 1, 12)) in events
    assert len(load_acled_events(path, keep_types=None)) == 3


def test_build_labels_marks_the_horizon_window():
    events = {("north", dt.date(2024, 1, 10)): 1}
    origins = [dt.date(2024, 1, d) for d in (3, 4, 10, 11)]
    labels = build_labels(events, ["north"], origins, horizon_days=7)
    assert labels[("north", dt.date(2024, 1, 3))] == 0    # [3, 10) stops short
    assert labels[("north", dt.date(2024, 1, 4))] == 1    # [4, 11) reaches it
    assert labels[("north", dt.date(2024, 1, 10))] == 1   # the day itself
    assert labels[("north", dt.date(2024, 1, 11))] == 0   # already past


def test_build_labels_covers_regions_without_events():
    labels = build_labels({}, ["quiet"], [dt.date(2024, 1, 1)], horizon_days=7)
    assert labels[("quiet", dt.date(2024, 1, 1))] == 0


def test_deduplicate_drops_republished_wire_copy():
    text = "The teachers union threatened a general strike across the capital tomorrow."
    docs = [
        Document(doc_id="a", text=text, date=dt.date(2024, 1, 1), region="r", source="wire"),
        Document(doc_id="b", text=text, date=dt.date(2024, 1, 1), region="r", source="daily"),
        Document(doc_id="c", text=text, date=dt.date(2024, 1, 2), region="r", source="wire"),
        Document(doc_id="d", text="Something else entirely happened downtown today.",
                 date=dt.date(2024, 1, 1), region="r", source="wire"),
    ]
    kept = deduplicate(docs)
    assert [d.doc_id for d in kept] == ["a", "c", "d"]  # same day+text collapses


def test_iter_batches_covers_every_document_once():
    docs = [Document(doc_id=str(i), text="x", date=dt.date(2024, 1, 1), region="r")
            for i in range(10)]
    batches = list(iter_batches(docs, size=4))
    assert [len(b) for b in batches] == [4, 4, 2]
    assert [d.doc_id for b in batches for d in b] == [str(i) for i in range(10)]
