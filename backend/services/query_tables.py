from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Any

from pydantic import BaseModel, Field

from backend.config import BackendConfig
from backend.services.datalake import DataLakeService
from backend.services.embeddings import TableDescriptionEmbeddingService, TextEmbedder
from backend.services.json_io import read_json
from backend.services.llm import OpenAIResponsesLLM
from backend.services.openai_cache import OpenAICache
from backend.services.preprocessing import SEMANTIC_TYPES_ARTIFACT, TABLES_ARTIFACT, TABLE_DESCRIPTIONS_ARTIFACT


QUERY_TABLE_INSTRUCTIONS = """Generate candidate query tables for a natural language data integration request.
Use only the provided data lake context. Return the requested number of suggestions.
Each suggestion should have a clear table name and exactly three example rows.
Rows should be keyed by human-readable column names. Include semantic types for columns.
"""


class QueryTableColumn(BaseModel):
    name: str
    semantic_type: str = ""


class QueryTableSuggestion(BaseModel):
    name: str
    columns: list[QueryTableColumn] = Field(default_factory=list)
    rows: list[dict[str, Any]] = Field(default_factory=list)


class QueryTableSuggestionsResponse(BaseModel):
    suggestions: list[QueryTableSuggestion]


@dataclass
class QueryTableService:
    config: BackendConfig
    datalake_service: DataLakeService
    llm: OpenAIResponsesLLM
    retrieval_embedder: TextEmbedder | None = None

    def generate(
        self,
        *,
        datalake: str,
        natural_language_query: str,
        suggestion_count: int = 4,
        ann_topk: int = 25,
    ) -> dict[str, Any]:
        if not natural_language_query.strip():
            raise ValueError("natural_language_query must not be empty")
        suggestion_count = max(1, int(suggestion_count))
        ann_topk = max(1, int(ann_topk))

        self.datalake_service.resolve_lake(datalake)
        context_tables = self._retrieve_context_tables(datalake, natural_language_query, ann_topk)
        context = self._context_payload(datalake, context_tables)
        result = self.llm.parse_structured(
            datalake=datalake,
            task_type="initial_query_table_suggestions",
            instructions=QUERY_TABLE_INSTRUCTIONS,
            input_payload={
                "natural_language_query": natural_language_query,
                "suggestion_count": suggestion_count,
                "context_tables": context,
            },
            response_model=QueryTableSuggestionsResponse,
            temperature=0.0,
            parameters={"suggestion_count": suggestion_count, "ann_topk": ann_topk},
        )
        query_tables = [_normalize_suggestion(suggestion) for suggestion in result.parsed.suggestions[:suggestion_count]]

        return {
            "datalake": datalake,
            "natural_language_query": natural_language_query,
            "query_tables": query_tables,
            "queryTables": query_tables,
            "candidate_context_tables": context_tables,
            "cache_key": result.cache_key,
            "cache_hit": result.cache_hit,
        }

    def _retrieve_context_tables(self, datalake: str, query: str, ann_topk: int) -> list[dict[str, Any]]:
        retrieval = TableDescriptionEmbeddingService(
            self.config.preprocessed_dir,
            model_name=self.config.embedding_model,
            embedder=self.retrieval_embedder,
        )
        return retrieval.retrieve(datalake, query, top_k=ann_topk)

    def _context_payload(self, datalake: str, context_tables: list[dict[str, Any]]) -> list[dict[str, Any]]:
        tables_artifact = _read_object(self._artifact_path(datalake, TABLES_ARTIFACT))
        semantic_types = _read_object(self._artifact_path(datalake, SEMANTIC_TYPES_ARTIFACT))
        table_descriptions = _read_object(self._artifact_path(datalake, TABLE_DESCRIPTIONS_ARTIFACT))
        tables_by_name = {table["name"]: table for table in tables_artifact.get("tables", [])}

        context: list[dict[str, Any]] = []
        for match in context_tables:
            table_name = match["table_name"]
            table = tables_by_name.get(table_name)
            if table is None:
                continue
            semantic_columns = semantic_types.get("tables", {}).get(table_name, {}).get("columns", {})
            description = table_descriptions.get("tables", {}).get(table_name, {}).get("description", match.get("description", ""))
            context.append(
                {
                    "table_name": table_name,
                    "description": description,
                    "retrieval_score": match["score"],
                    "columns": [
                        {
                            "name": column,
                            "semantic_type": semantic_columns.get(column, {}).get("semantic_type", column),
                            "sample_values": table.get("top_values", {}).get(column, [])[:5],
                        }
                        for column in table.get("columns", [])
                    ],
                    "sample_rows": table.get("sample_rows", [])[:3],
                }
            )
        return context

    def _artifact_path(self, datalake: str, artifact: str) -> Path:
        return self.config.preprocessed_dir / datalake / artifact


def build_query_table_service(
    config: BackendConfig,
    datalake_service: DataLakeService,
    *,
    requester=None,
    retrieval_embedder: TextEmbedder | None = None,
) -> QueryTableService:
    llm = OpenAIResponsesLLM(
        OpenAICache(config.preprocessed_dir),
        config.openai_model,
        temperature=config.llm_temperature,
        requester=requester,
        schema_version=config.metadata_schema_version,
    )
    return QueryTableService(config, datalake_service, llm, retrieval_embedder=retrieval_embedder)


def _normalize_suggestion(suggestion: QueryTableSuggestion) -> dict[str, Any]:
    rows = [dict(row) for row in suggestion.rows]
    column_names = [column.name for column in suggestion.columns]
    if not column_names:
        seen: list[str] = []
        for row in rows:
            for column in row:
                if column not in seen:
                    seen.append(column)
        column_names = seen
    semantic_types = {column.name: column.semantic_type for column in suggestion.columns}
    return {
        "name": suggestion.name,
        "columns": column_names,
        "semantic_types": semantic_types,
        "rows": rows,
    }


def _read_object(path: Path) -> dict[str, Any]:
    payload = read_json(path)
    if not isinstance(payload, dict):
        raise ValueError(f"Expected JSON object at {path}")
    return payload

