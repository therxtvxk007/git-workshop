"""Shared fixtures.

The corpus fixture is session-scoped and small: every test that needs documents
gets the same 120-day corpus, so a failure is reproducible and the suite does
not spend its life regenerating data.
"""

from __future__ import annotations

import os

import pytest

from pramaan_x.data.synth import SynthConfig, SyntheticCorpus

LOOPBACK = ("localhost", "127.0.0.1", "::1")


@pytest.fixture
def loopback_direct(monkeypatch):
    """Make loopback HTTP bypass an inherited proxy, without weakening it.

    CI runners and corporate images export `HTTP_PROXY`/`HTTPS_PROXY`. A test
    that connects to 127.0.0.1 then gets its request forwarded to the proxy,
    which either hangs or answers with a proxy error -- so a test written to
    assert "connection refused in milliseconds" instead waits out a timeout or
    asserts against the wrong failure.

    The fix is additive: prepend the loopback hosts to the existing `no_proxy`
    lists rather than unsetting the proxy variables. Nothing outside loopback
    changes, so the proxy keeps doing its job for every other destination and
    no TLS verification is disabled anywhere.
    """
    for var in ("NO_PROXY", "no_proxy"):
        existing = [p.strip() for p in os.environ.get(var, "").split(",") if p.strip()]
        merged = list(dict.fromkeys([*LOOPBACK, *existing]))
        monkeypatch.setenv(var, ",".join(merged))
    # Yield the hosts rather than nothing, so a test can assert on them without
    # importing from this module. `tests/` is not an installable package, and
    # `from tests.conftest import ...` only resolves under an editable install
    # -- it breaks the moment the suite is run against a wheel, which is
    # exactly what the clean-install job does.
    yield LOOPBACK


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
