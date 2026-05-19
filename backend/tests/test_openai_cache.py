from __future__ import annotations

from pydantic import BaseModel

from backend.services.llm import OpenAIResponsesLLM
from backend.services.openai_cache import OpenAICache, payload_hash


class ToyResponse(BaseModel):
    value: str


def test_payload_hash_is_stable_for_equivalent_json():
    assert payload_hash({"b": 2, "a": [1, 2]}) == payload_hash({"a": [1, 2], "b": 2})


def test_llm_cache_prevents_duplicate_requests(tmp_path):
    calls = []

    def requester(**kwargs):
        calls.append(kwargs["input_payload"])
        return {"value": "cached result"}

    llm = OpenAIResponsesLLM(OpenAICache(tmp_path), "test-model", requester=requester)

    first = llm.parse_structured(
        datalake="orders",
        task_type="unit_test",
        instructions="Return a toy value.",
        input_payload={"x": 1},
        response_model=ToyResponse,
    )
    second = llm.parse_structured(
        datalake="orders",
        task_type="unit_test",
        instructions="Return a toy value.",
        input_payload={"x": 1},
        response_model=ToyResponse,
    )

    assert first.parsed.value == "cached result"
    assert first.cache_hit is False
    assert second.parsed.value == "cached result"
    assert second.cache_hit is True
    assert first.cache_key == second.cache_key
    assert len(calls) == 1
    assert (tmp_path / "orders" / "openai_cache" / f"{first.cache_key}.json").exists()

