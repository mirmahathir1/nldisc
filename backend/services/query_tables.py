from __future__ import annotations

import re
from collections import defaultdict
from dataclasses import dataclass
from pathlib import Path
from difflib import SequenceMatcher
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
Each row is a list of cells; each cell has the human-readable column name and the
example value as strings. Use the same column set across the three rows of one
suggestion. Include semantic types for columns.
Every column must be populated with a real, non-empty example value in every row,
drawn from the provided data lake context. Never emit blank, null, "N/A", or
placeholder values. If you cannot supply a genuine value for a column from the
context, omit that column entirely rather than leaving it empty.
"""

QUERY_TABLE_RESUBMIT_INSTRUCTIONS = """Generate revised candidate query tables for a natural language data integration request.
Use the user's edited query table as feedback about desired columns and example values.
Use only the provided matched data lake evidence and context tables. Return revised suggestions
that reflect the edits, especially renamed or newly added columns. Each row must be a list of
cells with `column` and `value` fields (both strings); rows in one suggestion share the same
column set.
Every column must be populated with a real, non-empty example value in every row, drawn from
the matched evidence and context tables. Never emit blank, null, "N/A", or placeholder values.
If the user added a column but left it empty, fill it with genuine values found in the data
lake evidence; if no such values exist, omit that column rather than returning it empty.
Suggest better column names that align with the matching data lake table columns and their
semantic types from the evidence, rather than reusing the user's ad-hoc column labels. For
example, prefer the lake column's clear, conventional name over a vague or abbreviated edit.
"""


class QueryTableColumn(BaseModel):
    name: str
    semantic_type: str = ""


# Structured Outputs strict mode requires `additionalProperties: false` everywhere in
# the JSON schema, which forbids freeform `dict[str, Any]` fields. Rows are therefore
# represented on the wire as ordered (column, value) pairs and then re-keyed into a
# dictionary inside `_normalize_suggestion`.
class QueryTableCell(BaseModel):
    column: str
    value: str = ""


class QueryTableRow(BaseModel):
    cells: list[QueryTableCell] = Field(default_factory=list)


class QueryTableSuggestion(BaseModel):
    name: str
    columns: list[QueryTableColumn] = Field(default_factory=list)
    rows: list[QueryTableRow] = Field(default_factory=list)


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

    def resubmit(
        self,
        *,
        datalake: str,
        natural_language_query: str,
        edited_rows: list[dict[str, Any]],
        prior_selected_table_name: str | None = None,
        suggestion_count: int = 4,
        ann_topk: int = 25,
    ) -> dict[str, Any]:
        if not natural_language_query.strip():
            raise ValueError("natural_language_query must not be empty")
        if not edited_rows:
            raise ValueError("edited query table rows must not be empty")

        suggestion_count = max(1, int(suggestion_count))
        ann_topk = max(1, int(ann_topk))
        self.datalake_service.resolve_lake(datalake)

        edited_table = _edited_table(prior_selected_table_name, edited_rows)
        evidence = self._candidate_column_evidence(datalake, natural_language_query, edited_rows)
        context_table_names = _rank_context_tables_from_evidence(evidence, limit=ann_topk)
        context_tables = self._context_payload_for_names(datalake, context_table_names, natural_language_query)

        result = self.llm.parse_structured(
            datalake=datalake,
            task_type="corrected_query_table_resubmission",
            instructions=QUERY_TABLE_RESUBMIT_INSTRUCTIONS,
            input_payload={
                "natural_language_query": natural_language_query,
                "prior_selected_table_name": prior_selected_table_name,
                "edited_query_table": edited_table,
                "suggestion_count": suggestion_count,
                "candidate_column_evidence": evidence,
                "context_tables": context_tables,
            },
            response_model=QueryTableSuggestionsResponse,
            temperature=0.0,
            parameters={"suggestion_count": suggestion_count, "ann_topk": ann_topk},
        )
        generated = [_normalize_suggestion(suggestion) for suggestion in result.parsed.suggestions]
        query_tables = _dedupe_suggestions(generated)[:suggestion_count]

        return {
            "datalake": datalake,
            "natural_language_query": natural_language_query,
            "query_tables": query_tables,
            "queryTables": query_tables,
            "candidate_column_evidence": evidence,
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

    def _context_payload_for_names(
        self,
        datalake: str,
        table_names: list[str],
        natural_language_query: str,
    ) -> list[dict[str, Any]]:
        table_descriptions = _read_object(self._artifact_path(datalake, TABLE_DESCRIPTIONS_ARTIFACT))
        context_matches = [
            {
                "table_name": table_name,
                "description": table_descriptions.get("tables", {}).get(table_name, {}).get("description", ""),
                "score": _text_similarity(
                    natural_language_query,
                    table_descriptions.get("tables", {}).get(table_name, {}).get("description", ""),
                ),
            }
            for table_name in table_names
        ]
        return self._context_payload(datalake, context_matches)

    def _candidate_column_evidence(
        self,
        datalake: str,
        natural_language_query: str,
        edited_rows: list[dict[str, Any]],
    ) -> list[dict[str, Any]]:
        tables_artifact = _read_object(self._artifact_path(datalake, TABLES_ARTIFACT))
        semantic_types = _read_object(self._artifact_path(datalake, SEMANTIC_TYPES_ARTIFACT))
        table_descriptions = _read_object(self._artifact_path(datalake, TABLE_DESCRIPTIONS_ARTIFACT))

        query_columns = _columns_from_rows(edited_rows)
        query_values = {column: _values_for_column(edited_rows, column) for column in query_columns}
        evidence: list[dict[str, Any]] = []

        for query_column in query_columns:
            matches: list[dict[str, Any]] = []
            for table in tables_artifact.get("tables", []):
                table_name = table["name"]
                table_description = table_descriptions.get("tables", {}).get(table_name, {}).get("description", "")
                table_relevance = _text_similarity(natural_language_query, table_description)
                semantic_columns = semantic_types.get("tables", {}).get(table_name, {}).get("columns", {})
                for lake_column in table.get("columns", []):
                    semantic_type = semantic_columns.get(lake_column, {}).get("semantic_type", lake_column)
                    name_score = _text_similarity(query_column, lake_column)
                    semantic_score = max(_text_similarity(query_column, semantic_type), _text_similarity(natural_language_query, semantic_type))
                    value_score = _value_overlap(query_values[query_column], table.get("top_values", {}).get(lake_column, []))
                    score = (0.3 * semantic_score) + (0.25 * name_score) + (0.35 * value_score) + (0.1 * table_relevance)
                    if score <= 0:
                        continue
                    matches.append(
                        {
                            "query_column": query_column,
                            "table_name": table_name,
                            "column": lake_column,
                            "semantic_type": semantic_type,
                            "score": round(score, 6),
                            "evidence": {
                                "semantic_type_similarity": round(semantic_score, 6),
                                "column_name_similarity": round(name_score, 6),
                                "value_overlap": round(value_score, 6),
                                "table_description_relevance": round(table_relevance, 6),
                                "edited_values": query_values[query_column][:8],
                                "sample_values": table.get("top_values", {}).get(lake_column, [])[:8],
                            },
                        }
                    )
            matches.sort(key=lambda item: (item["score"], item["evidence"]["value_overlap"], item["evidence"]["column_name_similarity"]), reverse=True)
            evidence.append({"query_column": query_column, "matches": matches[:5]})

        return evidence

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
    rows: list[dict[str, Any]] = []
    for row in suggestion.rows:
        row_dict: dict[str, Any] = {}
        for cell in row.cells:
            # Last value wins on duplicate column names within a row — matches dict semantics.
            row_dict[cell.column] = cell.value
        rows.append(row_dict)
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


def _edited_table(prior_selected_table_name: str | None, edited_rows: list[dict[str, Any]]) -> dict[str, Any]:
    columns = _columns_from_rows(edited_rows)
    return {
        "name": prior_selected_table_name or "Edited Query Table",
        "columns": columns,
        "semantic_types": {},
        "rows": [dict(row) for row in edited_rows],
        "source": "user_edit",
    }


def _dedupe_suggestions(suggestions: list[dict[str, Any]]) -> list[dict[str, Any]]:
    out: list[dict[str, Any]] = []
    seen: set[str] = set()
    for suggestion in suggestions:
        key = suggestion.get("name", "")
        if key in seen:
            continue
        seen.add(key)
        out.append(suggestion)
    return out


def _rank_context_tables_from_evidence(evidence: list[dict[str, Any]], *, limit: int) -> list[str]:
    scores: dict[str, float] = defaultdict(float)
    for column_evidence in evidence:
        for match in column_evidence.get("matches", []):
            scores[match["table_name"]] += float(match["score"])
    return [table for table, _score in sorted(scores.items(), key=lambda item: item[1], reverse=True)[:limit]]


def _columns_from_rows(rows: list[dict[str, Any]]) -> list[str]:
    columns: list[str] = []
    for row in rows:
        for column in row:
            if column not in columns:
                columns.append(column)
    return columns


def _values_for_column(rows: list[dict[str, Any]], column: str) -> list[str]:
    values: list[str] = []
    seen: set[str] = set()
    for row in rows:
        value = _normalize_value(row.get(column))
        if not value or value in seen:
            continue
        seen.add(value)
        values.append(value)
    return values


def _value_overlap(query_values: list[str], lake_values: list[Any]) -> float:
    query_set = {_normalize_value(value) for value in query_values if _normalize_value(value)}
    lake_set = {_normalize_value(value) for value in lake_values if _normalize_value(value)}
    if not query_set or not lake_set:
        return 0.0
    return len(query_set & lake_set) / min(len(query_set), len(lake_set))


def _text_similarity(left: str, right: str) -> float:
    left_norm = _normalize_text(left)
    right_norm = _normalize_text(right)
    if not left_norm or not right_norm:
        return 0.0
    left_tokens = set(left_norm.split())
    right_tokens = set(right_norm.split())
    token_score = len(left_tokens & right_tokens) / len(left_tokens | right_tokens) if left_tokens and right_tokens else 0.0
    sequence_score = SequenceMatcher(None, left_norm, right_norm).ratio()
    substring_bonus = 1.0 if left_norm in right_norm or right_norm in left_norm else 0.0
    return max(token_score, sequence_score, substring_bonus)


def _normalize_text(value: str) -> str:
    text = re.sub(r"[^a-z0-9]+", " ", str(value).lower())
    return " ".join(text.split())


def _normalize_value(value: Any) -> str:
    if value is None:
        return ""
    return " ".join(str(value).strip().lower().split())


def _read_object(path: Path) -> dict[str, Any]:
    payload = read_json(path)
    if not isinstance(payload, dict):
        raise ValueError(f"Expected JSON object at {path}")
    return payload
