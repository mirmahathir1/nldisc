from __future__ import annotations

import hashlib
import json
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from backend.services.json_io import read_json, write_json


def canonical_json(payload: Any) -> str:
    return json.dumps(payload, sort_keys=True, separators=(",", ":"), ensure_ascii=False)


def payload_hash(payload: Any) -> str:
    return hashlib.sha256(canonical_json(payload).encode("utf-8")).hexdigest()


@dataclass(frozen=True)
class OpenAICache:
    preprocessed_dir: Path

    def cache_key(self, payload: Any) -> str:
        return payload_hash(payload)

    def cache_dir(self, datalake: str) -> Path:
        return self.preprocessed_dir / datalake / "openai_cache"

    def path_for_key(self, datalake: str, cache_key: str) -> Path:
        return self.cache_dir(datalake) / f"{cache_key}.json"

    def path_for_payload(self, datalake: str, payload: Any) -> Path:
        return self.path_for_key(datalake, self.cache_key(payload))

    def read(self, datalake: str, payload: Any) -> dict[str, Any] | None:
        path = self.path_for_payload(datalake, payload)
        if not path.exists():
            return None
        cached = read_json(path)
        if not isinstance(cached, dict):
            raise ValueError(f"Cache file is not a JSON object: {path}")
        return cached

    def write(self, datalake: str, payload: Any, parsed: dict[str, Any], metadata: dict[str, Any] | None = None) -> str:
        cache_key = self.cache_key(payload)
        cache_payload = {
            "cache_key": cache_key,
            "payload": payload,
            "parsed": parsed,
            "metadata": metadata or {},
        }
        write_json(self.path_for_key(datalake, cache_key), cache_payload)
        return cache_key

