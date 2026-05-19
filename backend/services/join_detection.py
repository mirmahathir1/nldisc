from __future__ import annotations

import itertools
import math
import re
from dataclasses import dataclass
from pathlib import Path
from typing import Any

import pandas as pd
from datasketch import MinHash

from backend.services.datalake import DataLakeService
from backend.services.json_io import write_json


MINHASH_JACCARD_ARTIFACT = "minhash_jaccard.json"
EXACT_JOINABILITY_ARTIFACT = "exact_joinability.json"
JOIN_GRAPH_ARTIFACT = "join_graph.json"
JOIN_DETECTION_SCHEMA_VERSION = "join-detection-v1"


@dataclass(frozen=True)
class JoinDetectionParams:
    equi_joinability_threshold: float = 0.9
    minhash_num_perm: int = 128
    min_support: int = 1


@dataclass
class JoinDetectionService:
    datalake_service: DataLakeService
    preprocessed_dir: Path

    def load_tables(self, datalake: str) -> dict[str, pd.DataFrame]:
        lake_path = self.datalake_service.resolve_lake(datalake)
        tables: dict[str, pd.DataFrame] = {}
        for csv_path in sorted(lake_path.glob("*.csv")):
            tables[csv_path.stem] = pd.read_csv(csv_path, dtype=str, keep_default_na=False)
        return tables

    def discover(self, datalake: str, params: JoinDetectionParams | None = None) -> dict[str, Any]:
        params = params or JoinDetectionParams()
        tables = self.load_tables(datalake)
        table_value_sets = _table_value_sets(tables)
        minhashes = _table_minhashes(table_value_sets, params.minhash_num_perm)

        minhash_pairs: list[dict[str, Any]] = []
        exact_pairs: list[dict[str, Any]] = []
        edges: list[dict[str, Any]] = []
        edge_counter = 0

        for left_table, right_table in itertools.combinations(sorted(tables), 2):
            for left_col in tables[left_table].columns:
                for right_col in tables[right_table].columns:
                    left_values = table_value_sets[left_table][left_col]
                    right_values = table_value_sets[right_table][right_col]
                    if not left_values or not right_values:
                        continue

                    approx_jaccard = float(minhashes[left_table][left_col].jaccard(minhashes[right_table][right_col]))
                    exact = _exact_overlap(left_values, right_values)
                    comparable = _domains_comparable(left_col, right_col, left_values, right_values)

                    minhash_pairs.append(
                        _pair_record(left_table, left_col, right_table, right_col, approx_jaccard, comparable=comparable)
                    )
                    exact_pairs.append(
                        {
                            **_pair_record(
                                left_table,
                                left_col,
                                right_table,
                                right_col,
                                exact["jaccard"],
                                comparable=comparable,
                            ),
                            "overlap_score": exact["overlap_score"],
                            "left_containment": exact["left_containment"],
                            "right_containment": exact["right_containment"],
                            "intersection_size": exact["intersection_size"],
                            "left_distinct": len(left_values),
                            "right_distinct": len(right_values),
                        }
                    )

                    if (
                        comparable
                        and exact["overlap_score"] >= params.equi_joinability_threshold
                        and exact["intersection_size"] >= params.min_support
                    ):
                        edge_counter += 1
                        edges.append(
                            _edge_record(
                                edge_counter,
                                left_table,
                                left_col,
                                right_table,
                                right_col,
                                approx_jaccard,
                                exact,
                                tables,
                            )
                        )

        edges.sort(key=_edge_sort_key, reverse=True)
        for idx, edge in enumerate(edges, start=1):
            edge["edge_id"] = f"e{idx:05d}"

        nodes = [{"table": table, "row_count": int(len(df)), "columns": list(df.columns)} for table, df in sorted(tables.items())]
        graph = {
            "schema_version": JOIN_DETECTION_SCHEMA_VERSION,
            "datalake": datalake,
            "params": {
                "equi_joinability_threshold": params.equi_joinability_threshold,
                "minhash_num_perm": params.minhash_num_perm,
                "min_support": params.min_support,
            },
            "nodes": nodes,
            "edges": edges,
        }
        minhash_artifact = {
            "schema_version": JOIN_DETECTION_SCHEMA_VERSION,
            "datalake": datalake,
            "metric": "minhash_jaccard",
            "pairs": minhash_pairs,
        }
        exact_artifact = {
            "schema_version": JOIN_DETECTION_SCHEMA_VERSION,
            "datalake": datalake,
            "metric": "exact_overlap",
            "pairs": exact_pairs,
        }

        lake_dir = self.preprocessed_dir / datalake
        write_json(lake_dir / MINHASH_JACCARD_ARTIFACT, minhash_artifact)
        write_json(lake_dir / EXACT_JOINABILITY_ARTIFACT, exact_artifact)
        write_json(lake_dir / JOIN_GRAPH_ARTIFACT, graph)

        return {
            "join_graph": graph,
            "minhash_jaccard": minhash_artifact,
            "exact_joinability": exact_artifact,
            "tables": tables,
        }


def _table_value_sets(tables: dict[str, pd.DataFrame]) -> dict[str, dict[str, set[str]]]:
    return {
        table: {column: {_normalize_value(value) for value in df[column].tolist() if _normalize_value(value)} for column in df.columns}
        for table, df in tables.items()
    }


def _table_minhashes(value_sets: dict[str, dict[str, set[str]]], num_perm: int) -> dict[str, dict[str, MinHash]]:
    out: dict[str, dict[str, MinHash]] = {}
    for table, columns in value_sets.items():
        out[table] = {}
        for column, values in columns.items():
            minhash = MinHash(num_perm=num_perm)
            for value in sorted(values):
                minhash.update(value.encode("utf-8"))
            out[table][column] = minhash
    return out


def _exact_overlap(left_values: set[str], right_values: set[str]) -> dict[str, float | int]:
    intersection = left_values & right_values
    union = left_values | right_values
    left_containment = len(intersection) / len(left_values) if left_values else 0.0
    right_containment = len(intersection) / len(right_values) if right_values else 0.0
    overlap_score = len(intersection) / min(len(left_values), len(right_values)) if left_values and right_values else 0.0
    return {
        "jaccard": len(intersection) / len(union) if union else 0.0,
        "overlap_score": overlap_score,
        "left_containment": left_containment,
        "right_containment": right_containment,
        "intersection_size": len(intersection),
    }


def _domains_comparable(left_col: str, right_col: str, left_values: set[str], right_values: set[str]) -> bool:
    left_norm = _normalize_column(left_col)
    right_norm = _normalize_column(right_col)
    if left_norm == right_norm:
        return True
    if left_norm.endswith("id") and right_norm.endswith("id") and left_norm[:-2] == right_norm[:-2]:
        return True
    if _token_jaccard(left_col, right_col) >= 0.5:
        return True
    return False


def _pair_record(
    left_table: str,
    left_col: str,
    right_table: str,
    right_col: str,
    score: float,
    *,
    comparable: bool,
) -> dict[str, Any]:
    return {
        "left_table": left_table,
        "left_col": left_col,
        "right_table": right_table,
        "right_col": right_col,
        "score": float(score),
        "comparable": comparable,
    }


def _edge_record(
    edge_number: int,
    left_table: str,
    left_col: str,
    right_table: str,
    right_col: str,
    approx_jaccard: float,
    exact: dict[str, float | int],
    tables: dict[str, pd.DataFrame],
) -> dict[str, Any]:
    left_support = int(tables[left_table][left_col].map(_normalize_value).isin(_intersection_values(tables, left_table, left_col, right_table, right_col)).sum())
    right_support = int(tables[right_table][right_col].map(_normalize_value).isin(_intersection_values(tables, left_table, left_col, right_table, right_col)).sum())
    score = float(exact["overlap_score"])
    return {
        "edge_id": f"e{edge_number:05d}",
        "left_table": left_table,
        "left_col": left_col,
        "right_table": right_table,
        "right_col": right_col,
        "edge_type": "equi",
        "kind": "equi",
        "score": score,
        "confidence": score,
        "minhash_jaccard": float(approx_jaccard),
        "exact_jaccard": float(exact["jaccard"]),
        "overlap_score": score,
        "left_containment": float(exact["left_containment"]),
        "right_containment": float(exact["right_containment"]),
        "intersection_size": int(exact["intersection_size"]),
        "support": {
            "left_rows": left_support,
            "right_rows": right_support,
            "left_total_rows": int(len(tables[left_table])),
            "right_total_rows": int(len(tables[right_table])),
        },
        "metadata": {
            "left_column_priority": _column_priority(left_col),
            "right_column_priority": _column_priority(right_col),
            "name_similarity": _token_jaccard(left_col, right_col),
        },
    }


def _intersection_values(
    tables: dict[str, pd.DataFrame],
    left_table: str,
    left_col: str,
    right_table: str,
    right_col: str,
) -> set[str]:
    left = {_normalize_value(value) for value in tables[left_table][left_col].tolist() if _normalize_value(value)}
    right = {_normalize_value(value) for value in tables[right_table][right_col].tolist() if _normalize_value(value)}
    return left & right


def _edge_sort_key(edge: dict[str, Any]) -> tuple[float, float, int, int, int]:
    return (
        float(edge["score"]),
        float(edge["metadata"]["name_similarity"]),
        int(edge["metadata"]["left_column_priority"]) + int(edge["metadata"]["right_column_priority"]),
        int(edge["intersection_size"]),
        -len(edge["left_col"]) - len(edge["right_col"]),
    )


def _column_priority(column: str) -> int:
    norm = _normalize_column(column)
    if norm.endswith("id"):
        return 3
    if norm.endswith("no") or norm.endswith("number"):
        return 1
    return 2


def _normalize_value(value: Any) -> str:
    if value is None:
        return ""
    if isinstance(value, float) and math.isnan(value):
        return ""
    return str(value).strip().lower()


def _normalize_column(column: str) -> str:
    return re.sub(r"[^a-z0-9]+", "", column.lower())


def _tokens(column: str) -> set[str]:
    return {token for token in re.split(r"[^a-z0-9]+", column.lower()) if token}


def _token_jaccard(left_col: str, right_col: str) -> float:
    left = _tokens(left_col)
    right = _tokens(right_col)
    if not left or not right:
        return 0.0
    return len(left & right) / len(left | right)


