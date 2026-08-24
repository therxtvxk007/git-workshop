"""Shared fixtures.

The corpus fixture is session-scoped and small: every test that needs documents
gets the same 120-day corpus, so a failure is reproducible and the suite does
not spend its life regenerating data.
"""

from __future__ import annotations

import pytest

from pramaan_x.data.synth import SynthConfig, SyntheticCorpus


@pytest.fixture(scope="session")
def corpus():
    docs, gt = SyntheticCorpus(SynthConfig(days=120, n_locations=6, n_event_types=4)).generate()
    return docs, gt


@pytest.fixture(scope="session")
def documents(corpus):
    return corpus[0]


@pytest.fixture(scope="session")
def ground_truth(corpus):
    return corpus[1]


@pytest.fixture
def tmp_cache(tmp_path):
    from pramaan_x.util.cache import ContentCache

    return ContentCache(tmp_path / "cache")
