from __future__ import annotations

import re
from collections import defaultdict
from dataclasses import dataclass
from difflib import SequenceMatcher
from pathlib import Path
from typing import Any

import numpy as np
from sklearn.cluster import KMeans

from backend.config import BackendConfig
from backend.services.datalake import DataLakeService
from backend.services.join_paths import (
    JOIN_PATH_EMBEDDING_LABELS_ARTIFACT,
    JOIN_PATH_EMBEDDINGS_ARTIFACT,
    JOIN_PATHS_ARTIFACT,
    TABLE_INDEX_MAP_ARTIFACT,
    TABLE_TO_PATH_INDEX_ARTIFACT,
)
from backend.services.json_io import read_json
from backend.services.preprocessing import TABLES_ARTIFACT
from backend.services.semantic_types import SEMANTIC_TYPES_ARTIFACT
from backend.services.table_descriptions import TABLE_DESCRIPTIONS_ARTIFACT


DEFAULT_DEDUP_THRESHOLD = 0.8
DEFAULT_TOP_K = 5


@dataclass
class JoinSearchService:
    config: BackendConfig
    datalake_service: DataLakeService

    def search(
        self,
        *,
        datalake: str,
        confirmed_rows: list[dict[str, Any]],
        natural_language_query: str = "",
        top_k: int = DEFAULT_TOP_K,
        dedup_threshold: float = DEFAULT_DEDUP_THRESHOLD,
    ) -> dict[str, Any]:
        if not confirmed_rows:
            raise ValueError("confirmed query table rows must not be empty")

        top_k = max(1, int(top_k))
        dedup_threshold = min(1.0, max(-1.0, float(dedup_threshold)))
        self.datalake_service.resolve_lake(datalake)

        evidence = self._candidate_column_evidence(datalake, natural_language_query, confirmed_rows)
        required_tables = _required_tables_from_evidence(evidence)
        path_bundle = self._candidate_paths(datalake, required_tables)
        ranked = self._rank_paths(path_bundle["paths"], required_tables, evidence, path_bundle["coverage_mode"])
        deduped = self._dedupe_paths(datalake, ranked, dedup_threshold)
        diversified = self._diversify_paths(datalake, deduped, top_k)

        join_paths = [
            _path_response(path, required_tables=required_tables, evidence=evidence, coverage_mode=path_bundle["coverage_mode"])
            for path in diversified[:top_k]
        ]

        return {
            "datalake": datalake,
            "query_table_columns": _columns_from_rows(confirmed_rows),
            "required_tables": required_tables,
            "candidate_column_evidence": evidence,
            "coverage_mode": path_bundle["coverage_mode"],
            "fallback": path_bundle["coverage_mode"] != "strict",
            "candidate_path_count": len(path_bundle["paths"]),
            "ranked_path_count": len(ranked),
            "deduplicated_path_count": len(deduped),
            "dedup_threshold": dedup_threshold,
            "top_k": top_k,
            "join_paths": join_paths,
            "paths": join_paths,
            "top_paths": join_paths,
        }

    def _candidate_paths(self, datalake: str, required_tables: list[str]) -> dict[str, Any]:
        join_paths_artifact = _read_object(self._artifact_path(datalake, JOIN_PATHS_ARTIFACT))
        table_index_map = _read_object(self._artifact_path(datalake, TABLE_INDEX_MAP_ARTIFACT))
        table_to_path_path = self._artifact_path(datalake, TABLE_TO_PATH_INDEX_ARTIFACT)
        if not table_to_path_path.exists():
            raise FileNotFoundError(f"Missing preprocessing artifact: {table_to_path_path}")

        table_to_path_index = np.load(table_to_path_path)
        paths = [path for path in join_paths_artifact.get("paths", []) if "query" not in path.get("tables_list", [])]
        path_ids = list(table_index_map.get("path_ids", []))
        table_to_index = dict(table_index_map.get("table_to_index", {}))
        path_by_id = {path["path_id"]: path for path in paths}

        required_indices = [table_to_index[table] for table in required_tables if table in table_to_index]
        strict_indices: list[int] = []
        if required_indices:
            strict_indices = [
                int(idx)
                for idx in np.where(np.all(table_to_path_index[required_indices] == 1, axis=0))[0].tolist()
                if idx < len(path_ids) and path_ids[idx] in path_by_id
            ]

        if strict_indices:
            return {
                "coverage_mode": "strict",
                "paths": [path_by_id[path_ids[idx]] for idx in strict_indices],
            }

        required_set = set(required_tables)
        fallback_paths = [
            path
            for path in paths
            if required_set & set(path.get("tables_list", []))
        ]
        if not fallback_paths and paths:
            fallback_paths = paths
        return {
            "coverage_mode": "fallback_largest_subset",
            "paths": fallback_paths,
        }

    def _rank_paths(
        self,
        paths: list[dict[str, Any]],
        required_tables: list[str],
        evidence: list[dict[str, Any]],
        coverage_mode: str,
    ) -> list[dict[str, Any]]:
        table_scores = _table_match_scores(evidence)
        required_set = set(required_tables)
        ranked: list[dict[str, Any]] = []
        for path in paths:
            tables = set(path.get("tables_list", []))
            covered = sorted(required_set & tables)
            coverage_ratio = len(covered) / len(required_set) if required_set else 0.0
            matched_table_score = sum(table_scores.get(table, 0.0) for table in covered)
            path_score = float(path.get("score", 0.0))
            hop_count = int(path.get("hop_count", max(0, len(path.get("tables_list", [])) - 1)))
            combined_score = (2.0 * coverage_ratio) + path_score + (0.15 * matched_table_score) - (0.01 * hop_count)
            ranked.append(
                {
                    **path,
                    "join_search_score": round(combined_score, 6),
                    "coverage": {
                        "mode": coverage_mode,
                        "required_tables": required_tables,
                        "covered_required_tables": covered,
                        "missing_required_tables": sorted(required_set - tables),
                        "coverage_ratio": round(coverage_ratio, 6),
                    },
                }
            )

        ranked.sort(
            key=lambda path: (
                path["join_search_score"],
                path["coverage"]["coverage_ratio"],
                float(path.get("score", 0.0)),
                -int(path.get("hop_count", 0)),
                path.get("path_id", ""),
            ),
            reverse=True,
        )
        return ranked

    def _dedupe_paths(
        self,
        datalake: str,
        ranked_paths: list[dict[str, Any]],
        dedup_threshold: float,
    ) -> list[dict[str, Any]]:
        embeddings = _load_embeddings(self._artifact_path(datalake, JOIN_PATH_EMBEDDINGS_ARTIFACT))
        if embeddings.size == 0:
            return ranked_paths

        vector_by_path = _path_vector_map(datalake, embeddings, self.config.preprocessed_dir)
        kept: list[dict[str, Any]] = []
        kept_vectors: list[np.ndarray] = []
        for path in ranked_paths:
            vector = vector_by_path.get(path.get("path_id"))
            if vector is None or vector.size == 0:
                kept.append(path)
                continue
            if any(_cosine_similarity(vector, kept_vector) >= dedup_threshold for kept_vector in kept_vectors):
                continue
            kept.append(path)
            kept_vectors.append(vector)
        return kept

    def _diversify_paths(
        self,
        datalake: str,
        deduped_paths: list[dict[str, Any]],
        top_k: int,
    ) -> list[dict[str, Any]]:
        if len(deduped_paths) <= top_k:
            return deduped_paths

        embeddings = _load_embeddings(self._artifact_path(datalake, JOIN_PATH_EMBEDDINGS_ARTIFACT))
        vector_by_path = _path_vector_map(datalake, embeddings, self.config.preprocessed_dir)
        vectors: list[np.ndarray] = []
        vector_paths: list[dict[str, Any]] = []
        for path in deduped_paths:
            vector = vector_by_path.get(path.get("path_id"))
            if vector is None or vector.size == 0:
                continue
            vectors.append(vector)
            vector_paths.append(path)

        if len(vectors) <= top_k:
            return deduped_paths[:top_k]

        matrix = np.vstack(vectors)
        unique_vectors = np.unique(matrix.round(decimals=6), axis=0)
        cluster_count = min(top_k, len(unique_vectors))
        if cluster_count <= 1:
            return deduped_paths[:top_k]

        kmeans = KMeans(n_clusters=cluster_count, random_state=0, n_init=10)
        labels = kmeans.fit_predict(matrix)
        selected: list[dict[str, Any]] = []
        selected_ids: set[str] = set()
        for cluster_idx in range(cluster_count):
            member_indices = np.where(labels == cluster_idx)[0]
            if len(member_indices) == 0:
                continue
            centroid = kmeans.cluster_centers_[cluster_idx]
            best_member = min(
                member_indices,
                key=lambda idx: (
                    float(np.linalg.norm(matrix[idx] - centroid)),
                    -float(vector_paths[idx].get("join_search_score", 0.0)),
                    vector_paths[idx].get("path_id", ""),
                ),
            )
            path = vector_paths[int(best_member)]
            selected.append({**path, "diversification_cluster": int(cluster_idx)})
            selected_ids.add(path["path_id"])

        for path in deduped_paths:
            if len(selected) >= top_k:
                break
            if path["path_id"] in selected_ids:
                continue
            selected.append(path)
            selected_ids.add(path["path_id"])

        selected.sort(key=lambda path: path.get("join_search_score", 0.0), reverse=True)
        return selected[:top_k]

    def _candidate_column_evidence(
        self,
        datalake: str,
        natural_language_query: str,
        confirmed_rows: list[dict[str, Any]],
    ) -> list[dict[str, Any]]:
        tables_artifact = _read_object(self._artifact_path(datalake, TABLES_ARTIFACT))
        semantic_types = _read_object(self._artifact_path(datalake, SEMANTIC_TYPES_ARTIFACT))
        table_descriptions = _read_object(self._artifact_path(datalake, TABLE_DESCRIPTIONS_ARTIFACT))

        query_columns = _columns_from_rows(confirmed_rows)
        query_values = {column: _values_for_column(confirmed_rows, column) for column in query_columns}
        query_context = " ".join([natural_language_query, *query_columns])
        evidence: list[dict[str, Any]] = []

        for query_column in query_columns:
            matches: list[dict[str, Any]] = []
            for table in tables_artifact.get("tables", []):
                table_name = table["name"]
                if table_name == "query":
                    continue
                table_description = table_descriptions.get("tables", {}).get(table_name, {}).get("description", "")
                table_relevance = max(
                    _text_similarity(query_context, table_description),
                    _text_similarity(query_column, table_description),
                )
                table_name_score = _text_similarity(query_column, table_name)
                semantic_columns = semantic_types.get("tables", {}).get(table_name, {}).get("columns", {})
                for lake_column in table.get("columns", []):
                    semantic_type = semantic_columns.get(lake_column, {}).get("semantic_type", lake_column)
                    name_score = max(
                        _text_similarity(query_column, lake_column),
                        _text_similarity(query_column, f"{table_name} {lake_column}"),
                    )
                    semantic_score = max(
                        _text_similarity(query_column, semantic_type),
                        _text_similarity(query_context, semantic_type),
                    )
                    value_score = _value_overlap(query_values[query_column], table.get("top_values", {}).get(lake_column, []))
                    score = (
                        (0.28 * semantic_score)
                        + (0.24 * name_score)
                        + (0.32 * value_score)
                        + (0.1 * table_relevance)
                        + (0.06 * table_name_score)
                    )
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
                                "table_name_similarity": round(table_name_score, 6),
                                "confirmed_values": query_values[query_column][:8],
                                "sample_values": table.get("top_values", {}).get(lake_column, [])[:8],
                            },
                        }
                    )
            matches.sort(
                key=lambda item: (
                    item["score"],
                    item["evidence"]["value_overlap"],
                    item["evidence"]["column_name_similarity"],
                    item["evidence"]["table_name_similarity"],
                ),
                reverse=True,
            )
            evidence.append({"query_column": query_column, "matches": matches[:6]})

        return evidence

    def _artifact_path(self, datalake: str, artifact: str) -> Path:
        return self.config.preprocessed_dir / datalake / artifact


def build_join_search_service(config: BackendConfig, datalake_service: DataLakeService) -> JoinSearchService:
    return JoinSearchService(config=config, datalake_service=datalake_service)


def _path_response(
    path: dict[str, Any],
    *,
    required_tables: list[str],
    evidence: list[dict[str, Any]],
    coverage_mode: str,
) -> dict[str, Any]:
    path_tables = list(path.get("tables_list", []))
    path_table_set = set(path_tables)
    matched_query_columns = [
        {
            "query_column": column_evidence["query_column"],
            "table_name": match["table_name"],
            "column": match["column"],
            "score": match["score"],
        }
        for column_evidence in evidence
        for match in column_evidence.get("matches", [])
        if match["table_name"] in path_table_set
    ]
    highlighted_tables = sorted({match["table_name"] for match in matched_query_columns})
    required_set = set(required_tables)
    coverage = path.get("coverage") or {
        "mode": coverage_mode,
        "required_tables": required_tables,
        "covered_required_tables": sorted(required_set & path_table_set),
        "missing_required_tables": sorted(required_set - path_table_set),
        "coverage_ratio": len(required_set & path_table_set) / len(required_set) if required_set else 0.0,
    }
    return {
        "path_id": path["path_id"],
        "tables": path.get("tables") or " -> ".join(path_tables),
        "tables_list": path_tables,
        "ordered_tables": path_tables,
        "join_edges": path.get("join_edges", []),
        "join_order": path.get("join_order", []),
        "row_count_estimate": int(path.get("row_count_estimate", path.get("cardinality_estimate", 0))),
        "cardinality_estimate": int(path.get("cardinality_estimate", path.get("row_count_estimate", 0))),
        "attributes": path.get("attributes", []),
        "hop_count": int(path.get("hop_count", max(0, len(path_tables) - 1))),
        "length": int(path.get("length", len(path_tables))),
        "score": float(path.get("join_search_score", path.get("score", 0.0))),
        "path_score": float(path.get("score", 0.0)),
        "coverage": coverage,
        "matched_query_columns": matched_query_columns,
        "highlighted_tables": highlighted_tables,
        "fallback": coverage.get("mode") != "strict",
        "diversification_cluster": path.get("diversification_cluster"),
    }


def _required_tables_from_evidence(evidence: list[dict[str, Any]]) -> list[str]:
    selected: dict[str, float] = {}
    first_seen: dict[str, int] = {}
    for idx, column_evidence in enumerate(evidence):
        matches = column_evidence.get("matches", [])
        if not matches:
            continue
        best = matches[0]
        if float(best["score"]) < 0.12:
            continue
        table_name = best["table_name"]
        selected[table_name] = max(selected.get(table_name, 0.0), float(best["score"]))
        first_seen.setdefault(table_name, idx)
        if _looks_like_identifier(column_evidence["query_column"]):
            best_score = float(best["score"])
            for match in matches[1:3]:
                evidence_scores = match.get("evidence", {})
                if (
                    float(match["score"]) >= best_score * 0.97
                    and float(evidence_scores.get("value_overlap", 0.0)) >= 0.8
                    and float(evidence_scores.get("column_name_similarity", 0.0)) >= 0.95
                ):
                    table_name = match["table_name"]
                    selected[table_name] = max(selected.get(table_name, 0.0), float(match["score"]))
                    first_seen.setdefault(table_name, idx)
    return [
        table
        for table, _score in sorted(
            selected.items(),
            key=lambda item: (first_seen[item[0]], -item[1], item[0]),
        )
    ]


def _looks_like_identifier(column: str) -> bool:
    normalized = _normalize_text(column)
    tokens = normalized.split()
    return "id" in tokens or normalized.endswith(" identifier")


def _table_match_scores(evidence: list[dict[str, Any]]) -> dict[str, float]:
    scores: dict[str, float] = defaultdict(float)
    for column_evidence in evidence:
        for match in column_evidence.get("matches", []):
            scores[match["table_name"]] = max(scores[match["table_name"]], float(match["score"]))
    return scores


def _path_vector_map(datalake: str, embeddings: np.ndarray, preprocessed_dir: Path) -> dict[str, np.ndarray]:
    labels_path = preprocessed_dir / datalake / JOIN_PATH_EMBEDDING_LABELS_ARTIFACT
    if not labels_path.exists():
        return {}
    labels = _read_object(labels_path)
    out: dict[str, np.ndarray] = {}
    for label in labels.get("labels", []):
        vector_id = int(label.get("vector_id", -1))
        if 0 <= vector_id < len(embeddings):
            out[str(label["path_id"])] = embeddings[vector_id]
    return out


def _load_embeddings(path: Path) -> np.ndarray:
    if not path.exists():
        raise FileNotFoundError(f"Missing preprocessing artifact: {path}")
    embeddings = np.load(path)
    if embeddings.ndim != 2 or embeddings.size == 0:
        return np.zeros((0, 0), dtype=np.float32)
    return embeddings.astype(np.float32, copy=False)


def _cosine_similarity(left: np.ndarray, right: np.ndarray) -> float:
    left_norm = float(np.linalg.norm(left))
    right_norm = float(np.linalg.norm(right))
    if left_norm == 0.0 or right_norm == 0.0:
        return 0.0
    return float(np.dot(left, right) / (left_norm * right_norm))


def _columns_from_rows(rows: list[dict[str, Any]]) -> list[str]:
    columns: list[str] = []
    for row in rows:
        if not isinstance(row, dict):
            raise ValueError("confirmed query table rows must be JSON objects")
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
    if not path.exists():
        raise FileNotFoundError(f"Missing preprocessing artifact: {path}")
    payload = read_json(path)
    if not isinstance(payload, dict):
        raise ValueError(f"Expected JSON object at {path}")
    return payload
