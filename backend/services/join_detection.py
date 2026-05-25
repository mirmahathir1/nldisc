from __future__ import annotations

import itertools
import math
import re
from dataclasses import dataclass
from pathlib import Path
from typing import Any

import numpy as np
import pandas as pd
from datasketch import MinHash

from backend.services.datalake import DataLakeService
from backend.services.embeddings import TextEmbedder
from backend.services.json_io import write_json


MINHASH_JACCARD_ARTIFACT = "minhash_jaccard.json"
EXACT_JOINABILITY_ARTIFACT = "exact_joinability.json"
SEMANTIC_JOINABILITY_ARTIFACT = "semantic_joinability.json"
JOIN_GRAPH_ARTIFACT = "join_graph.json"
JOIN_DETECTION_SCHEMA_VERSION = "join-detection-v1"

# Seed keeps the random hyperplanes (and therefore simhash codes) reproducible
# across runs so cached artifacts stay stable for an unchanged data lake.
_SIMHASH_SEED = 1
_SIMHASH_NUM_HYPERPLANES = 128


@dataclass(frozen=True)
class JoinDetectionParams:
    equi_joinability_threshold: float = 0.9
    semantic_joinability_threshold: float = 0.75
    # Minimum cosine similarity between the two columns' semantic-type embeddings
    # for a join to be allowed. Applied as a second gate on top of the value
    # similarity (exact overlap for equi, simhash MinHash jaccard for semantic).
    # Kept low by default so it only blocks clearly-unrelated semantic types.
    semantic_type_similarity_threshold: float = 0.3
    # Minimum distinct/total value ratio a column must have to participate in a
    # join. If either joining column's uniqueness ratio falls below this, the
    # join is discarded (filters out low-cardinality columns like flags/booleans).
    unique_value_ratio_threshold: float = 0.1
    minhash_num_perm: int = 128
    simhash_num_hyperplanes: int = _SIMHASH_NUM_HYPERPLANES
    # Fraction of non-empty values that must parse as numbers for a column to be
    # treated as numeric (equi-join) rather than non-numeric (semantic-join).
    numeric_value_threshold: float = 0.8
    min_support: int = 1


@dataclass
class JoinDetectionService:
    datalake_service: DataLakeService
    preprocessed_dir: Path
    embedder: TextEmbedder | None = None

    def load_tables(self, datalake: str) -> dict[str, pd.DataFrame]:
        lake_path = self.datalake_service.resolve_lake(datalake)
        tables: dict[str, pd.DataFrame] = {}
        for csv_path in sorted(lake_path.glob("*.csv")):
            tables[csv_path.stem] = pd.read_csv(csv_path, dtype=str, keep_default_na=False)
        return tables

    def discover(
        self,
        datalake: str,
        params: JoinDetectionParams | None = None,
        semantic_types: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        params = params or JoinDetectionParams()
        tables = self.load_tables(datalake)
        table_value_sets = _table_value_sets(tables)
        # distinct / total non-empty value ratio per column, used as a cardinality gate.
        unique_value_ratios = _unique_value_ratios(tables)
        minhashes = _table_minhashes(table_value_sets, params.minhash_num_perm)

        numeric_columns = _numeric_columns(tables, params.numeric_value_threshold)
        # Non-numeric columns get a simhash code per value (via random hyperplanes
        # over embeddings) and a MinHash over those codes; semantic joinability is
        # the Jaccard of the two columns' simhash MinHashes.
        semantic_minhashes = self._semantic_minhashes(
            tables, numeric_columns, params.simhash_num_hyperplanes, params.minhash_num_perm
        )
        # Embed each column's semantic type once so candidate pairs can be gated
        # on the cosine similarity of their semantic-type embeddings.
        semantic_type_embeddings = self._semantic_type_embeddings(tables, semantic_types or {})

        minhash_pairs: list[dict[str, Any]] = []
        exact_pairs: list[dict[str, Any]] = []
        semantic_pairs: list[dict[str, Any]] = []
        edges: list[dict[str, Any]] = []
        edge_counter = 0

        for left_table, right_table in itertools.combinations(sorted(tables), 2):
            for left_col in tables[left_table].columns:
                for right_col in tables[right_table].columns:
                    left_values = table_value_sets[left_table][left_col]
                    right_values = table_value_sets[right_table][right_col]
                    if not left_values or not right_values:
                        continue

                    left_numeric = left_col in numeric_columns[left_table]
                    right_numeric = right_col in numeric_columns[right_table]

                    type_similarity = _semantic_type_similarity(
                        semantic_type_embeddings.get((left_table, left_col)),
                        semantic_type_embeddings.get((right_table, right_col)),
                    )
                    type_ok = type_similarity >= params.semantic_type_similarity_threshold

                    left_ratio = unique_value_ratios[left_table][left_col]
                    right_ratio = unique_value_ratios[right_table][right_col]
                    ratio_ok = (
                        left_ratio >= params.unique_value_ratio_threshold
                        and right_ratio >= params.unique_value_ratio_threshold
                    )

                    if left_numeric and right_numeric:
                        # Numeric columns join by exact value overlap (equi-join).
                        approx_jaccard = float(
                            minhashes[left_table][left_col].jaccard(minhashes[right_table][right_col])
                        )
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
                            and type_ok
                            and ratio_ok
                        ):
                            edge_counter += 1
                            edges.append(
                                _equi_edge_record(
                                    edge_counter,
                                    left_table,
                                    left_col,
                                    right_table,
                                    right_col,
                                    approx_jaccard,
                                    exact,
                                    tables,
                                    type_similarity,
                                )
                            )
                    elif not left_numeric and not right_numeric:
                        # Non-numeric columns join by semantic similarity (simhash + minhash).
                        semantic_jaccard = float(
                            semantic_minhashes[left_table][left_col].jaccard(
                                semantic_minhashes[right_table][right_col]
                            )
                        )
                        semantic_pairs.append(
                            _pair_record(
                                left_table, left_col, right_table, right_col, semantic_jaccard, comparable=True
                            )
                        )

                        if semantic_jaccard >= params.semantic_joinability_threshold and type_ok and ratio_ok:
                            edge_counter += 1
                            edges.append(
                                _semantic_edge_record(
                                    edge_counter,
                                    left_table,
                                    left_col,
                                    right_table,
                                    right_col,
                                    semantic_jaccard,
                                    tables,
                                    type_similarity,
                                )
                            )
                    # Mixed numeric/non-numeric pairs are not joinable.

        edges.sort(key=_edge_sort_key, reverse=True)
        for idx, edge in enumerate(edges, start=1):
            edge["edge_id"] = f"e{idx:05d}"

        nodes = [{"table": table, "row_count": int(len(df)), "columns": list(df.columns)} for table, df in sorted(tables.items())]
        graph = {
            "schema_version": JOIN_DETECTION_SCHEMA_VERSION,
            "datalake": datalake,
            "params": {
                "equi_joinability_threshold": params.equi_joinability_threshold,
                "semantic_joinability_threshold": params.semantic_joinability_threshold,
                "semantic_type_similarity_threshold": params.semantic_type_similarity_threshold,
                "unique_value_ratio_threshold": params.unique_value_ratio_threshold,
                "minhash_num_perm": params.minhash_num_perm,
                "simhash_num_hyperplanes": params.simhash_num_hyperplanes,
                "numeric_value_threshold": params.numeric_value_threshold,
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
        semantic_artifact = {
            "schema_version": JOIN_DETECTION_SCHEMA_VERSION,
            "datalake": datalake,
            "metric": "simhash_minhash_jaccard",
            "pairs": semantic_pairs,
        }

        lake_dir = self.preprocessed_dir / datalake
        write_json(lake_dir / MINHASH_JACCARD_ARTIFACT, minhash_artifact)
        write_json(lake_dir / EXACT_JOINABILITY_ARTIFACT, exact_artifact)
        write_json(lake_dir / SEMANTIC_JOINABILITY_ARTIFACT, semantic_artifact)
        write_json(lake_dir / JOIN_GRAPH_ARTIFACT, graph)

        return {
            "join_graph": graph,
            "minhash_jaccard": minhash_artifact,
            "exact_joinability": exact_artifact,
            "semantic_joinability": semantic_artifact,
            "tables": tables,
        }

    def _semantic_minhashes(
        self,
        tables: dict[str, pd.DataFrame],
        numeric_columns: dict[str, set[str]],
        num_hyperplanes: int,
        minhash_num_perm: int,
    ) -> dict[str, dict[str, MinHash]]:
        """Build a simhash-over-values MinHash for every non-numeric column.

        Each distinct value is embedded, projected onto a fixed set of random
        hyperplanes to yield a binary simhash code, and the column's codes are
        folded into a MinHash. Columns with no non-numeric work or no values get
        an empty MinHash so jaccard against them is well-defined (0.0).
        """
        text_columns = [
            (table, column)
            for table in sorted(tables)
            for column in tables[table].columns
            if column not in numeric_columns[table]
        ]
        out: dict[str, dict[str, MinHash]] = {table: {} for table in tables}
        if not text_columns:
            return out

        # Gather the distinct values to embed once across all text columns.
        column_values: dict[tuple[str, str], list[str]] = {}
        for table, column in text_columns:
            values = sorted(
                {_normalize_value(value) for value in tables[table][column].tolist() if _normalize_value(value)}
            )
            column_values[(table, column)] = values

        vocabulary = sorted({value for values in column_values.values() for value in values})
        simhash_by_value: dict[str, str] = {}
        if vocabulary:
            embedder = self._get_embedder()
            embeddings = np.asarray(embedder.encode(vocabulary), dtype=np.float32)
            if embeddings.ndim != 2 or embeddings.shape[0] != len(vocabulary):
                raise ValueError("Embedder returned an invalid embedding matrix for column values")
            hyperplanes = _simhash_hyperplanes(num_hyperplanes, embeddings.shape[1])
            codes = _extract_simhash(embeddings, hyperplanes)
            simhash_by_value = dict(zip(vocabulary, codes))

        for (table, column), values in column_values.items():
            minhash = MinHash(num_perm=minhash_num_perm, seed=_SIMHASH_SEED)
            for value in values:
                code = simhash_by_value.get(value)
                if code is not None:
                    minhash.update(code.encode("utf-8"))
            out[table][column] = minhash
        return out

    def _semantic_type_embeddings(
        self,
        tables: dict[str, pd.DataFrame],
        semantic_types: dict[str, Any],
    ) -> dict[tuple[str, str], np.ndarray]:
        """Embed the semantic type of every column, keyed by (table, column).

        The semantic type for each column comes from the semantic_types artifact;
        when missing it falls back to the column name (matching the fallback used
        during semantic-type extraction). Identical type strings are embedded once
        and the resulting vectors are L2-normalized so a plain dot product yields
        cosine similarity.
        """
        type_tables = semantic_types.get("tables", {}) if isinstance(semantic_types, dict) else {}
        column_type: dict[tuple[str, str], str] = {}
        for table in sorted(tables):
            columns = type_tables.get(table, {}).get("columns", {})
            for column in tables[table].columns:
                semantic_type = columns.get(column, {}).get("semantic_type")
                column_type[(table, column)] = str(semantic_type or column.replace("_", " "))

        vocabulary = sorted({text for text in column_type.values() if text})
        if not vocabulary:
            return {}

        embedder = self._get_embedder()
        embeddings = np.asarray(embedder.encode(vocabulary), dtype=np.float32)
        if embeddings.ndim != 2 or embeddings.shape[0] != len(vocabulary):
            raise ValueError("Embedder returned an invalid embedding matrix for semantic types")
        norms = np.linalg.norm(embeddings, axis=1, keepdims=True)
        norms[norms == 0] = 1.0
        embeddings = embeddings / norms
        embedding_by_type = dict(zip(vocabulary, embeddings))

        return {key: embedding_by_type[text] for key, text in column_type.items() if text in embedding_by_type}

    def _get_embedder(self) -> TextEmbedder:
        if self.embedder is None:
            from backend.services.embeddings import SentenceTransformerEmbedder

            self.embedder = SentenceTransformerEmbedder()
        return self.embedder


def _semantic_type_similarity(left: np.ndarray | None, right: np.ndarray | None) -> float:
    """Cosine similarity of two (already L2-normalized) semantic-type embeddings.

    Missing embeddings yield 0.0 so a column without a semantic type can never
    satisfy the gate on its own.
    """
    if left is None or right is None:
        return 0.0
    return float(np.clip(np.dot(left, right), -1.0, 1.0))


def _table_value_sets(tables: dict[str, pd.DataFrame]) -> dict[str, dict[str, set[str]]]:
    return {
        table: {column: {_normalize_value(value) for value in df[column].tolist() if _normalize_value(value)} for column in df.columns}
        for table, df in tables.items()
    }


def _unique_value_ratios(tables: dict[str, pd.DataFrame]) -> dict[str, dict[str, float]]:
    """distinct / total non-empty value count per column (0.0 when a column is empty)."""
    out: dict[str, dict[str, float]] = {}
    for table, df in tables.items():
        ratios: dict[str, float] = {}
        for column in df.columns:
            values = [value for value in (_normalize_value(v) for v in df[column].tolist()) if value]
            ratios[column] = len(set(values)) / len(values) if values else 0.0
        out[table] = ratios
    return out


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


def _numeric_columns(tables: dict[str, pd.DataFrame], numeric_value_threshold: float) -> dict[str, set[str]]:
    """Classify each column as numeric when most of its non-empty values parse as numbers."""
    out: dict[str, set[str]] = {}
    for table, df in tables.items():
        numeric: set[str] = set()
        for column in df.columns:
            values = [_normalize_value(value) for value in df[column].tolist()]
            values = [value for value in values if value]
            if not values:
                continue
            numeric_count = sum(1 for value in values if _is_numeric(value))
            if numeric_count / len(values) >= numeric_value_threshold:
                numeric.add(column)
        out[table] = numeric
    return out


def _is_numeric(value: str) -> bool:
    try:
        float(value.replace(",", ""))
        return True
    except ValueError:
        return False


def _simhash_hyperplanes(num_hyperplanes: int, embedding_dim: int) -> np.ndarray:
    rng = np.random.default_rng(_SIMHASH_SEED)
    return rng.standard_normal((num_hyperplanes, embedding_dim)).astype(np.float32)


def _extract_simhash(embeddings: np.ndarray, hyperplanes: np.ndarray) -> list[str]:
    """Project embeddings onto hyperplanes and turn the sign pattern into a bitstring."""
    dot_products = np.dot(embeddings, hyperplanes.T)
    bits = (dot_products > 0).astype(int)
    return ["".join(map(str, row)) for row in bits]


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


def _equi_edge_record(
    edge_number: int,
    left_table: str,
    left_col: str,
    right_table: str,
    right_col: str,
    approx_jaccard: float,
    exact: dict[str, float | int],
    tables: dict[str, pd.DataFrame],
    type_similarity: float,
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
            "semantic_type_similarity": float(type_similarity),
        },
    }


def _semantic_edge_record(
    edge_number: int,
    left_table: str,
    left_col: str,
    right_table: str,
    right_col: str,
    semantic_jaccard: float,
    tables: dict[str, pd.DataFrame],
    type_similarity: float,
) -> dict[str, Any]:
    score = float(semantic_jaccard)
    return {
        "edge_id": f"e{edge_number:05d}",
        "left_table": left_table,
        "left_col": left_col,
        "right_table": right_table,
        "right_col": right_col,
        "edge_type": "semantic",
        "kind": "semantic",
        "score": score,
        "confidence": score,
        "simhash_minhash_jaccard": score,
        "support": {
            "left_total_rows": int(len(tables[left_table])),
            "right_total_rows": int(len(tables[right_table])),
        },
        "metadata": {
            "left_column_priority": _column_priority(left_col),
            "right_column_priority": _column_priority(right_col),
            "name_similarity": _token_jaccard(left_col, right_col),
            "semantic_type_similarity": float(type_similarity),
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
        int(edge.get("intersection_size", 0)),
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


