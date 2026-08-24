"""Content-addressed cache: synthetic tests."""

from __future__ import annotations

from pramaan_x.util.cache import ContentCache


def test_roundtrip(tmp_cache):
    tmp_cache.put("emb", "key-a", [1, 2, 3])
    assert tmp_cache.get("emb", "key-a") == [1, 2, 3]


def test_miss_returns_none(tmp_cache):
    assert tmp_cache.get("emb", "absent") is None
    assert tmp_cache.misses == 1


def test_model_identity_is_part_of_the_key(tmp_cache):
    """The failure this guards: a cached embedding from a superseded model is
    returned for the new one, and every downstream comparison is silently
    wrong."""
    tmp_cache.put("emb", "doc-1", [0.1], model="jina-v5")
    assert tmp_cache.get("emb", "doc-1", model="jina-v5") == [0.1]
    assert tmp_cache.get("emb", "doc-1", model="qwen3-vl") is None


def test_namespaces_are_isolated(tmp_cache):
    tmp_cache.put("emb", "k", "embedding")
    tmp_cache.put("llm", "k", "generation")
    assert tmp_cache.get("emb", "k") == "embedding"
    assert tmp_cache.get("llm", "k") == "generation"


def test_memoise_calls_once(tmp_cache):
    calls = []

    def work():
        calls.append(1)
        return 42

    assert tmp_cache.memoise("ns", "k", work) == 42
    assert tmp_cache.memoise("ns", "k", work) == 42
    assert len(calls) == 1


def test_hit_rate_accounting(tmp_cache):
    tmp_cache.put("ns", "a", 1)
    tmp_cache.get("ns", "a")
    tmp_cache.get("ns", "b")
    assert tmp_cache.hits == 1 and tmp_cache.misses == 1
    assert tmp_cache.hit_rate == 0.5


def test_disabled_cache_is_transparent(tmp_path):
    c = ContentCache(tmp_path / "c", enabled=False)
    c.put("ns", "k", 1)
    assert c.get("ns", "k") is None


def test_corrupt_entry_is_evicted_not_raised(tmp_cache):
    """A truncated cache file must degrade to a miss. Raising here would take
    down a forecast run over a disk hiccup."""
    tmp_cache.put("ns", "k", {"a": 1})
    path = tmp_cache._path("ns", "k", "-")
    path.write_bytes(b"not a pickle")
    assert tmp_cache.get("ns", "k") is None
    assert not path.exists()
