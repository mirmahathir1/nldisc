from __future__ import annotations

import itertools
from dataclasses import dataclass
from pathlib import Path
from typing import Any

import networkx as nx
import numpy as np
import pandas as pd

from backend.services.embeddings import SentenceTransformerEmbedder, TextEmbedder, _normalize_embeddings
from backend.services.json_io import write_json


JOIN_PATHS_ARTIFACT = "join_paths.json"
TABLE_TO_PATH_INDEX_ARTIFACT = "table_to_path_index.npy"
TABLE_INDEX_MAP_ARTIFACT = "table_index_map.json"
JOIN_PATH_EMBEDDINGS_ARTIFACT = "join_path_embeddings.npy"
JOIN_PATH_EMBEDDING_LABELS_ARTIFACT = "join_path_embedding_labels.json"
JOIN_PATH_SCHEMA_VERSION = "join-paths-v1"


@dataclass(frozen=True)
class JoinPathParams:
    max_join_path_length: int = 4
    embedding_model: str = "sentence-transformers/all-mpnet-base-v2"


@dataclass
class JoinPathService:
    preprocessed_dir: Path
    embedder: TextEmbedder | None = None

    def build(
        self,
        datalake: str,
        join_graph: dict[str, Any],
        tables: dict[str, pd.DataFrame],
        semantic_types: dict[str, Any] | None = None,
        params: JoinPathParams | None = None,
    ) -> dict[str, Any]:
        params = params or JoinPathParams()
        graph = self._networkx_graph(join_graph)
        paths = self._enumerate_paths(graph, params.max_join_path_length)
        edge_lookup = self._edge_lookup(join_graph)

        path_records: list[dict[str, Any]] = []
        for path_number, path_tables in enumerate(paths, start=1):
            join_edges = [self._best_edge(edge_lookup, left, right) for left, right in zip(path_tables, path_tables[1:])]
            if any(edge is None for edge in join_edges):
                continue
            typed_edges = [edge for edge in join_edges if edge is not None]
            path_records.append(
                self._path_record(
                    path_number=path_number,
                    tables_list=path_tables,
                    join_edges=typed_edges,
                    tables=tables,
                )
            )

        path_records.sort(key=lambda path: (-path["score"], -path["row_count_estimate"], path["hop_count"], path["path_id"]))
        for idx, path in enumerate(path_records, start=1):
            path["path_id"] = f"jp_{idx:05d}"

        table_names = sorted(tables)
        table_to_path_index = self._table_to_path_index(table_names, path_records)
        lake_dir = self.preprocessed_dir / datalake
        lake_dir.mkdir(parents=True, exist_ok=True)
        np.save(lake_dir / TABLE_TO_PATH_INDEX_ARTIFACT, table_to_path_index)

        table_index_map = {
            "schema_version": JOIN_PATH_SCHEMA_VERSION,
            "datalake": datalake,
            "tables": table_names,
            "table_to_index": {table: idx for idx, table in enumerate(table_names)},
            "path_ids": [path["path_id"] for path in path_records],
        }
        join_paths_artifact = {
            "schema_version": JOIN_PATH_SCHEMA_VERSION,
            "datalake": datalake,
            "params": {"max_join_path_length": params.max_join_path_length},
            "paths": path_records,
        }

        write_json(lake_dir / JOIN_PATHS_ARTIFACT, join_paths_artifact)
        write_json(lake_dir / TABLE_INDEX_MAP_ARTIFACT, table_index_map)
        embedding_artifact = self._write_path_embeddings(datalake, path_records, semantic_types or {}, params.embedding_model)

        return {
            "join_paths": join_paths_artifact,
            "table_index_map": table_index_map,
            "table_to_path_index": table_to_path_index,
            "join_path_embedding_labels": embedding_artifact,
        }

    def _networkx_graph(self, join_graph: dict[str, Any]) -> nx.Graph:
        graph = nx.Graph()
        for node in join_graph.get("nodes", []):
            graph.add_node(node["table"])
        edge_lookup = self._edge_lookup(join_graph)
        for (left, right), edges in edge_lookup.items():
            best = self._best_edge(edge_lookup, left, right)
            if best is None:
                continue
            graph.add_edge(left, right, weight=max(0.000001, 1.0 - float(best["score"])))
        return graph

    def _enumerate_paths(self, graph: nx.Graph, max_join_path_length: int) -> list[list[str]]:
        paths: list[list[str]] = []
        seen: set[str] = set()
        for left, right in itertools.combinations(sorted(graph.nodes), 2):
            if not nx.has_path(graph, left, right):
                continue
            for path in nx.all_simple_paths(graph, left, right, cutoff=max_join_path_length - 1):
                key = _canonical_path_key(path)
                if key in seen:
                    continue
                seen.add(key)
                paths.append(path)
        return paths

    def _edge_lookup(self, join_graph: dict[str, Any]) -> dict[tuple[str, str], list[dict[str, Any]]]:
        lookup: dict[tuple[str, str], list[dict[str, Any]]] = {}
        for edge in join_graph.get("edges", []):
            key = tuple(sorted([edge["left_table"], edge["right_table"]]))
            lookup.setdefault(key, []).append(edge)
        for edges in lookup.values():
            edges.sort(key=lambda edge: (edge["score"], edge["metadata"]["name_similarity"], edge["metadata"]["left_column_priority"] + edge["metadata"]["right_column_priority"]), reverse=True)
        return lookup

    def _best_edge(self, edge_lookup: dict[tuple[str, str], list[dict[str, Any]]], left: str, right: str) -> dict[str, Any] | None:
        edges = edge_lookup.get(tuple(sorted([left, right])), [])
        if not edges:
            return None
        edge = edges[0]
        if edge["left_table"] == left and edge["right_table"] == right:
            return edge
        return {
            **edge,
            "left_table": edge["right_table"],
            "left_col": edge["right_col"],
            "right_table": edge["left_table"],
            "right_col": edge["left_col"],
        }

    def _path_record(
        self,
        *,
        path_number: int,
        tables_list: list[str],
        join_edges: list[dict[str, Any]],
        tables: dict[str, pd.DataFrame],
    ) -> dict[str, Any]:
        score = float(np.mean([edge["score"] for edge in join_edges])) if join_edges else 0.0
        cardinality = _true_join_cardinality(tables, tables_list, join_edges)
        return {
            "path_id": f"jp_{path_number:05d}",
            "tables": " -> ".join(tables_list),
            "tables_list": tables_list,
            "join_edges": join_edges,
            "join_order": [
                {
                    "parent": edge["left_table"],
                    "child": edge["right_table"],
                    "parent_column": edge["left_col"],
                    "child_column": edge["right_col"],
                    "join_type": "equi",
                }
                for edge in join_edges
            ],
            "attributes": [f"{table}.{column}" for table in tables_list for column in tables[table].columns],
            "hop_count": max(0, len(tables_list) - 1),
            "length": len(tables_list),
            "score": score,
            "row_count_estimate": cardinality,
            "cardinality_estimate": cardinality,
        }

    def _table_to_path_index(self, table_names: list[str], paths: list[dict[str, Any]]) -> np.ndarray:
        matrix = np.zeros((len(table_names), len(paths)), dtype=np.uint8)
        table_to_idx = {table: idx for idx, table in enumerate(table_names)}
        for path_idx, path in enumerate(paths):
            for table in path["tables_list"]:
                matrix[table_to_idx[table], path_idx] = 1
        return matrix

    def _write_path_embeddings(
        self,
        datalake: str,
        paths: list[dict[str, Any]],
        semantic_types: dict[str, Any],
        embedding_model: str,
    ) -> dict[str, Any]:
        semantic_terms_by_path = [_semantic_terms_for_path(path, semantic_types) for path in paths]
        semantic_texts = [" ".join(terms) for terms in semantic_terms_by_path]
        if semantic_terms_by_path:
            embedder = self.embedder or SentenceTransformerEmbedder(embedding_model)
            path_vectors: list[np.ndarray] = []
            for terms in semantic_terms_by_path:
                term_embeddings = _normalize_embeddings(embedder.encode(terms))
                path_vectors.append(np.mean(term_embeddings, axis=0))
            embeddings = _normalize_embeddings(np.vstack(path_vectors))
        else:
            embeddings = np.zeros((0, 0), dtype=np.float32)

        lake_dir = self.preprocessed_dir / datalake
        np.save(lake_dir / JOIN_PATH_EMBEDDINGS_ARTIFACT, embeddings)
        labels = {
            "schema_version": JOIN_PATH_SCHEMA_VERSION,
            "datalake": datalake,
            "embedding_model": embedding_model,
            "dimensions": int(embeddings.shape[1]) if embeddings.ndim == 2 and embeddings.size else 0,
            "labels": [
                {"vector_id": idx, "path_id": path["path_id"], "semantic_text": semantic_texts[idx]}
                for idx, path in enumerate(paths)
            ],
        }
        write_json(lake_dir / JOIN_PATH_EMBEDDING_LABELS_ARTIFACT, labels)
        return labels


def _true_join_cardinality(tables: dict[str, pd.DataFrame], tables_list: list[str], join_edges: list[dict[str, Any]]) -> int:
    if not tables_list:
        return 0
    joined = tables[tables_list[0]].copy()
    for edge in join_edges:
        right = tables[edge["right_table"]].copy()
        joined = joined.merge(
            right,
            how="inner",
            left_on=edge["left_col"],
            right_on=edge["right_col"],
            suffixes=("", f"__{edge['right_table']}"),
        )
        if joined.empty:
            return 0
    return int(len(joined))


def _canonical_path_key(path: list[str]) -> str:
    forward = "|".join(path)
    reverse = "|".join(reversed(path))
    return min(forward, reverse)


def _semantic_terms_for_path(path: dict[str, Any], semantic_types: dict[str, Any]) -> list[str]:
    tables = semantic_types.get("tables", {})
    parts: list[str] = []
    for table in path["tables_list"]:
        semantic_table = tables.get(table, {})
        for column, metadata in semantic_table.get("columns", {}).items():
            parts.append(str(metadata.get("semantic_type") or column))
    return parts or list(path["attributes"])
