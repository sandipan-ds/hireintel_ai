"""Unit tests for ``src.services.subquery_retrieval.make_cache_key``.

Locks in the theta-in-key behavior added in M0.5a Step 5: changing
``theta`` must always change the cache key, even when the other inputs
(candidate, REQ, chunk-ids, model) are identical. This is the invariant
that lets an Optuna sweep across ``theta ∈ [0.10, 0.50]`` never reuse an
LLM sub-score computed under a different theta.
"""

from __future__ import annotations

import pytest

from src.services.subquery_retrieval import make_cache_key


# ---------------------------------------------------------------------------
# Stability: same inputs -> same key
# ---------------------------------------------------------------------------


def test_same_inputs_produce_same_key():
    """Determinism: calling ``make_cache_key`` twice with identical args
    returns the same hash. The cache depends on this property."""
    a = make_cache_key("c1", "REQ-001", ("ck1", "ck2"), llm_model="gpt-4o", theta=0.30)
    b = make_cache_key("c1", "REQ-001", ("ck1", "ck2"), llm_model="gpt-4o", theta=0.30)
    assert a == b


def test_chunk_id_order_does_not_matter():
    """The chunk-id set is sorted before hashing so different input orders
    do not produce different keys."""
    a = make_cache_key("c1", "REQ-001", ("ck1", "ck2"), theta=0.30)
    b = make_cache_key("c1", "REQ-001", ("ck2", "ck1"), theta=0.30)
    assert a == b


# ---------------------------------------------------------------------------
# Theta-in-key behavior (M0.5a Step 5)
# ---------------------------------------------------------------------------


def test_theta_change_invalidates_cache():
    """A change in ``theta`` MUST change the cache key, even when the
    retrieved chunk-id set is identical. This is the core invariant for
    the Optuna sweep: theta is the one hyperparameter whose change can
    leave chunk-ids identical (every retrieved chunk clears both
    candidate thresholds), so without theta in the key the cache would
    silently return sub-scores from a different trial.
    """
    a = make_cache_key("c1", "REQ-001", ("ck1", "ck2", "ck3"), theta=0.30)
    b = make_cache_key("c1", "REQ-001", ("ck1", "ck2", "ck3"), theta=0.40)
    assert a != b, "theta change must invalidate cache key"


def test_theta_none_vs_explicit_differ():
    """Omitting theta (None) is treated as a distinct configuration from
    any explicit theta value. This prevents stumbles where legacy callers
    that did not pass theta collide with Optuna callers that did."""
    none_key = make_cache_key("c1", "REQ-001", ("ck1", "ck2"), theta=None)
    explicit_key = make_cache_key("c1", "REQ-001", ("ck1", "ck2"), theta=0.30)
    assert none_key != explicit_key


def test_theta_is_quantized_to_six_decimals():
    """Thetas that differ only beyond 6 decimals hash the same. This
    prevents floating-point noise (e.g. 0.3000000001 vs 0.30) from
    defeating the cache during a sweep."""
    a = make_cache_key("c1", "REQ-001", ("ck1",), theta=0.300000)
    b = make_cache_key("c1", "REQ-001", ("ck1",), theta=0.300000001)
    assert a == b


# ---------------------------------------------------------------------------
# Other key components still invalidate the cache
# ---------------------------------------------------------------------------


def test_candidate_change_invalidates_cache():
    a = make_cache_key("c1", "REQ-001", ("ck1",), theta=0.30)
    b = make_cache_key("c2", "REQ-001", ("ck1",), theta=0.30)
    assert a != b


def test_req_change_invalidates_cache():
    a = make_cache_key("c1", "REQ-001", ("ck1",), theta=0.30)
    b = make_cache_key("c1", "REQ-002", ("ck1",), theta=0.30)
    assert a != b


def test_chunk_set_change_invalidates_cache():
    """The chunk-id set is part of the key: if retrieval under a new
    chunker/different indexes returns different chunks, the cache must
    not return stale scores."""
    a = make_cache_key("c1", "REQ-001", ("ck1", "ck2"), theta=0.30)
    b = make_cache_key("c1", "REQ-001", ("ck1", "ck2", "ck3"), theta=0.30)
    assert a != b


def test_model_change_invalidates_cache():
    """Model upgrade must bust the cache — old sub-scores from a
    different LLM must not be reused."""
    a = make_cache_key("c1", "REQ-001", ("ck1",), llm_model="gpt-4o", theta=0.30)
    b = make_cache_key("c1", "REQ-001", ("ck1",), llm_model="gpt-4o-mini", theta=0.30)
    assert a != b


# ---------------------------------------------------------------------------
# Backward compatibility: omitting theta still works
# ---------------------------------------------------------------------------


def test_make_cache_key_works_without_theta():
    """Legacy callers that don't supply theta must still get a valid key.
    The default is ``None`` which is rendered as the empty string in the
    hash, so old call sites continue to work after this change."""
    key = make_cache_key("c1", "REQ-001", ("ck1",))
    assert isinstance(key, str)
    assert len(key) == 64  # sha256 hexdigest


def test_make_cache_key_default_model_works():
    """The default ``llm_model='stub'`` must produce a valid key."""
    key = make_cache_key("c1", "REQ-001", ("ck1",), theta=0.30)
    assert isinstance(key, str)
    assert len(key) == 64