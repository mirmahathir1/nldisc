from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Any

from pydantic import BaseModel, Field

from backend.services.datalake import DataLakeService
from backend.services.json_io import read_json, write_json
from backend.services.llm import OpenAIResponsesLLM


TABLE_DESCRIPTIONS_ARTIFACT = "table_descriptions.json"
TABLE_DESCRIPTIONS_SCHEMA_VERSION = "table-descriptions-v1"


class TableDescriptionResponse(BaseModel):
    table_name: str
    description: str = Field(description="Exactly one concise sentence describing what the table contains.")


TABLE_DESCRIPTION_INSTRUCTIONS = """Write one concise human-readable sentence describing a CSV table.
Use the table name, column names, semantic types, and sample values. Return exactly
one sentence and do not invent facts beyond the provided metadata.
"""


@dataclass
class TableDescriptionService:
    datalake_service: DataLakeService
    preprocessed_dir: Path
    llm: OpenAIResponsesLLM

    def extract(self, datalake: str, semantic_types: dict[str, Any], *, force: bool = False) -> dict[str, Any]:
        artifact_path = self._artifact_path(datalake)
        if artifact_path.exists() and not force:
            artifact = read_json(artifact_path)
            if isinstance(artifact, dict):
                return artifact

        profiles = {profile["name"]: profile for profile in self.datalake_service.table_profiles(datalake)}
        tables: dict[str, Any] = {}
        for table_name, semantic_table in semantic_types.get("tables", {}).items():
            profile = profiles[table_name]
            result = self.llm.parse_structured(
                datalake=datalake,
                task_type="table_description_extraction",
                instructions=TABLE_DESCRIPTION_INSTRUCTIONS,
                input_payload=self._llm_input(profile, semantic_table),
                response_model=TableDescriptionResponse,
                temperature=0.0,
                parameters={"artifact": TABLE_DESCRIPTIONS_ARTIFACT},
            )
            tables[table_name] = {
                "table_name": table_name,
                "description": _one_sentence(result.parsed.description),
                "cache_key": result.cache_key,
                "cache_hit": result.cache_hit,
                "source": "openai",
            }

        artifact = {
            "schema_version": TABLE_DESCRIPTIONS_SCHEMA_VERSION,
            "datalake": datalake,
            "tables": tables,
        }
        write_json(artifact_path, artifact)
        return artifact

    def _artifact_path(self, datalake: str) -> Path:
        return self.preprocessed_dir / datalake / TABLE_DESCRIPTIONS_ARTIFACT

    def _llm_input(self, profile: dict[str, Any], semantic_table: dict[str, Any]) -> dict[str, Any]:
        return {
            "table_name": profile["name"],
            "columns": [
                {
                    "column": column,
                    "semantic_type": metadata.get("semantic_type", column),
                    "sample_values": profile.get("top_values", {}).get(column, []),
                }
                for column, metadata in semantic_table.get("columns", {}).items()
            ],
            "sample_rows": profile.get("sample_rows", []),
        }


def _one_sentence(value: str) -> str:
    text = " ".join(str(value).split())
    if not text:
        return ""
    first_terminal = min([idx for idx in [text.find("."), text.find("!"), text.find("?")] if idx >= 0] or [-1])
    if first_terminal >= 0:
        text = text[: first_terminal + 1]
    elif text[-1] not in ".!?":
        text = f"{text}."
    return text

