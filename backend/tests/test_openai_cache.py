from __future__ import annotations

from backend.services.openai_cache import payload_hash


def test_payload_hash_is_stable_for_equivalent_json():
    assert payload_hash({"b": 2, "a": [1, 2]}) == payload_hash({"a": [1, 2], "b": 2})
