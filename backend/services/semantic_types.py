from __future__ import annotations

import re
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from pydantic import BaseModel, Field

from backend.services.datalake import DataLakeService
from backend.services.json_io import read_json, write_json
from backend.services.llm import OpenAIResponsesLLM


SEMANTIC_TYPES_ARTIFACT = "semantic_types.json"
SEMANTIC_TYPES_SCHEMA_VERSION = "semantic-types-v1"


class ColumnSemanticType(BaseModel):
    column: str = Field(description="Exact source column name when possible.")
    semantic_type: str = Field(description="Concise semantic type or human-readable column meaning.")
    examples: list[str] = Field(default_factory=list, description="Representative values supporting the type.")


class TableSemanticTypesResponse(BaseModel):
    table_name: str
    columns: list[ColumnSemanticType]


SEMANTIC_TYPE_INSTRUCTIONS = """Extract semantic types for CSV columns.
Return one entry per column. Use concise semantic types such as order identifier,
customer country code, product family, quantity, carrier name, or date.
Use only the columns provided in the input and include representative examples.
"""


@dataclass
class SemanticTypeService:
    datalake_service: DataLakeService
    preprocessed_dir: Path
    llm: OpenAIResponsesLLM

    def extract(self, datalake: str, *, force: bool = False) -> dict[str, Any]:
        artifact_path = self._artifact_path(datalake)
        if artifact_path.exists() and not force:
            artifact = read_json(artifact_path)
            if isinstance(artifact, dict):
                return artifact

        profiles = self.datalake_service.table_profiles(datalake)
        tables: dict[str, Any] = {}
        for profile in profiles:
            result = self.llm.parse_structured(
                datalake=datalake,
                task_type="semantic_type_extraction",
                instructions=SEMANTIC_TYPE_INSTRUCTIONS,
                input_payload=self._llm_input(profile),
                response_model=TableSemanticTypesResponse,
                temperature=0.0,
                parameters={"artifact": SEMANTIC_TYPES_ARTIFACT},
            )
            tables[profile["name"]] = self._normalize_table(profile, result.parsed, result.cache_key, result.cache_hit)

        artifact = {
            "schema_version": SEMANTIC_TYPES_SCHEMA_VERSION,
            "datalake": datalake,
            "tables": tables,
        }
        write_json(artifact_path, artifact)
        return artifact

    def _artifact_path(self, datalake: str) -> Path:
        return self.preprocessed_dir / datalake / SEMANTIC_TYPES_ARTIFACT

    def _llm_input(self, profile: dict[str, Any]) -> dict[str, Any]:
        return {
            "table_name": profile["name"],
            "columns": profile["columns"],
            "top_values": profile.get("top_values", {}),
            "sample_rows": profile.get("sample_rows", []),
        }

    def _normalize_table(
        self,
        profile: dict[str, Any],
        response: TableSemanticTypesResponse,
        cache_key: str,
        cache_hit: bool,
    ) -> dict[str, Any]:
        columns = list(profile["columns"])
        actual_by_norm = {_normalize_name(column): column for column in columns}
        normalized: dict[str, Any] = {}

        for item in response.columns:
            norm = _normalize_name(item.column)
            actual = item.column if item.column in columns else actual_by_norm.get(norm)
            if actual is None:
                raise ValueError(f"LLM returned unknown column {item.column!r} for table {profile['name']}")
            normalized[actual] = {
                "semantic_type": _clean_text(item.semantic_type) or actual.replace("_", " "),
                "examples": _clean_examples(item.examples, profile.get("top_values", {}).get(actual, [])),
                "source": "openai",
                "returned_column": item.column,
            }

        for column in columns:
            if column not in normalized:
                normalized[column] = {
                    "semantic_type": column.replace("_", " "),
                    "examples": _clean_examples([], profile.get("top_values", {}).get(column, [])),
                    "source": "fallback_missing_column",
                    "returned_column": None,
                }

        return {
            "table_name": profile["name"],
            "file_name": profile["file_name"],
            "columns": normalized,
            "cache_key": cache_key,
            "cache_hit": cache_hit,
        }


def _normalize_name(value: str) -> str:
    return re.sub(r"[^a-z0-9]+", "", str(value).lower())


def _clean_text(value: str) -> str:
    return " ".join(str(value).split())


def _clean_examples(examples: list[str], fallback: list[str]) -> list[str]:
    out: list[str] = []
    for value in list(examples or []) + list(fallback or []):
        text = _clean_text(value)
        if text and text not in out:
            out.append(text)
        if len(out) >= 5:
            break
    return out

