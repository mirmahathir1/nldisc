from __future__ import annotations

from pathlib import Path

import numpy as np

from backend.services.datalake import DataLakeService
from backend.services.join_detection import (
    EXACT_JOINABILITY_ARTIFACT,
    JOIN_GRAPH_ARTIFACT,
    MINHASH_JACCARD_ARTIFACT,
    SEMANTIC_JOINABILITY_ARTIFACT,
    JoinDetectionParams,
    JoinDetectionService,
)
from backend.services.join_paths import (
    JOIN_PATH_EMBEDDING_LABELS_ARTIFACT,
    JOIN_PATH_EMBEDDINGS_ARTIFACT,
    JOIN_PATHS_ARTIFACT,
    TABLE_INDEX_MAP_ARTIFACT,
    TABLE_TO_PATH_INDEX_ARTIFACT,
    JoinPathParams,
    JoinPathService,
)
from backend.services.offline_artifacts import OfflineJoinArtifactService


class TinyEmbedder:
    def encode(self, texts: list[str]) -> np.ndarray:
        vectors = []
        for text in texts:
            lower = text.lower()
            vectors.append(
                [
                    float(lower.count("order") + lower.count("customer")),
                    float(lower.count("product") + lower.count("category")),
                    float(lower.count("shipment") + lower.count("carrier")),
                ]
            )
        return np.asarray(vectors, dtype=np.float32)


def _root() -> Path:
    return Path(__file__).resolve().parents[2]


def _semantic_types() -> dict:
    return {
        "schema_version": "semantic-types-v1",
        "datalake": "orders",
        "tables": {
            "orders": {
                "columns": {
                    "order_id": {"semantic_type": "order identifier"},
                    "customer_id": {"semantic_type": "customer identifier"},
                    "preferred_carrier": {"semantic_type": "shipment carrier"},
                }
            },
            "customers": {
                "columns": {
                    "customer_id": {"semantic_type": "customer identifier"},
                    "country": {"semantic_type": "customer country"},
                }
            },
            "order_items": {
                "columns": {
                    "order_id": {"semantic_type": "order identifier"},
                    "product_id": {"semantic_type": "product identifier"},
                    "qty": {"semantic_type": "ordered quantity"},
                }
            },
            "products": {
                "columns": {
                    "product_id": {"semantic_type": "product identifier"},
                    "category_id": {"semantic_type": "category identifier"},
                    "product_family": {"semantic_type": "product family"},
                }
            },
            "categories": {
                "columns": {
                    "category_id": {"semantic_type": "category identifier"},
                    "category": {"semantic_type": "product category"},
                }
            },
            "shipments": {
                "columns": {
                    "order_id": {"semantic_type": "order identifier"},
                    "carrier": {"semantic_type": "shipment carrier"},
                }
            },
        },
    }


def test_join_detection_discovers_expected_orders_equi_joins(tmp_path):
    service = JoinDetectionService(DataLakeService(_root() / "datalake"), tmp_path, embedder=TinyEmbedder())

    result = service.discover("orders", JoinDetectionParams(equi_joinability_threshold=0.9))
    edges = result["join_graph"]["edges"]
    equi_keys = {
        (edge["left_table"], edge["left_col"], edge["right_table"], edge["right_col"])
        for edge in edges
        if edge["edge_type"] == "equi"
    }
    semantic_keys = {
        (edge["left_table"], edge["left_col"], edge["right_table"], edge["right_col"])
        for edge in edges
        if edge["edge_type"] == "semantic"
    }

    # The `_no` columns hold purely numeric keys -> equi-joins.
    assert ("order_items", "order_no", "orders", "order_no") in equi_keys
    assert ("orders", "order_no", "shipments", "order_no") in equi_keys
    assert ("customers", "customer_no", "orders", "customer_no") in equi_keys
    assert ("order_items", "product_no", "products", "product_no") in equi_keys
    assert ("categories", "category_no", "products", "category_no") in equi_keys

    # The string `*_id` columns are non-numeric -> semantic (simhash+minhash) joins.
    assert ("order_items", "order_id", "orders", "order_id") in semantic_keys
    assert ("order_items", "product_id", "products", "product_id") in semantic_keys

    assert all(edge["left_table"] != edge["right_table"] for edge in edges)
    assert all(edge["edge_type"] in {"equi", "semantic"} for edge in edges)

    assert (tmp_path / "orders" / JOIN_GRAPH_ARTIFACT).exists()
    assert (tmp_path / "orders" / MINHASH_JACCARD_ARTIFACT).exists()
    assert (tmp_path / "orders" / EXACT_JOINABILITY_ARTIFACT).exists()
    assert (tmp_path / "orders" / SEMANTIC_JOINABILITY_ARTIFACT).exists()


def test_semantic_type_gate_blocks_joins_with_dissimilar_types(tmp_path):
    service = JoinDetectionService(DataLakeService(_root() / "datalake"), tmp_path, embedder=TinyEmbedder())

    # Force every column's semantic type to an orthogonal token so no pair clears
    # even a low type-similarity threshold -> no edges survive the second gate.
    orthogonal_types = {
        "schema_version": "semantic-types-v1",
        "datalake": "orders",
        "tables": {
            table: {"columns": {column: {"semantic_type": "shipment carrier"} for column in df.columns}}
            for table, df in service.load_tables("orders").items()
        },
    }
    # Make one table's columns embed to a fully orthogonal axis (product/category)
    # so cross-table pairs have cosine 0 under the TinyEmbedder.
    orthogonal_types["tables"]["orders"]["columns"] = {
        column: {"semantic_type": "product category"} for column in orthogonal_types["tables"]["orders"]["columns"]
    }

    gated = service.discover(
        "orders",
        JoinDetectionParams(equi_joinability_threshold=0.9, semantic_type_similarity_threshold=0.5),
        semantic_types=orthogonal_types,
    )
    ungated = service.discover(
        "orders",
        JoinDetectionParams(equi_joinability_threshold=0.9, semantic_type_similarity_threshold=0.0),
        semantic_types=orthogonal_types,
    )

    # Lowering the gate to 0.0 restores edges that the 0.5 gate removed.
    assert len(gated["join_graph"]["edges"]) < len(ungated["join_graph"]["edges"])
    for edge in ungated["join_graph"]["edges"]:
        assert "semantic_type_similarity" in edge["metadata"]


def test_unique_value_ratio_gate_discards_low_cardinality_joins(tmp_path):
    service = JoinDetectionService(DataLakeService(_root() / "datalake"), tmp_path, embedder=TinyEmbedder())

    permissive = service.discover(
        "orders",
        JoinDetectionParams(equi_joinability_threshold=0.9, unique_value_ratio_threshold=0.0),
    )
    # A threshold above 1.0 is impossible to satisfy, so every join is discarded.
    strict = service.discover(
        "orders",
        JoinDetectionParams(equi_joinability_threshold=0.9, unique_value_ratio_threshold=1.01),
    )

    assert permissive["join_graph"]["edges"]
    assert strict["join_graph"]["edges"] == []


def test_join_paths_respect_max_length_and_build_table_index(tmp_path):
    detector = JoinDetectionService(DataLakeService(_root() / "datalake"), tmp_path, embedder=TinyEmbedder())
    detected = detector.discover("orders", JoinDetectionParams(equi_joinability_threshold=0.9))
    service = JoinPathService(tmp_path, embedder=TinyEmbedder())

    result = service.build(
        "orders",
        detected["join_graph"],
        detected["tables"],
        semantic_types=_semantic_types(),
        params=JoinPathParams(max_join_path_length=5, embedding_model="tiny"),
    )
    paths = result["join_paths"]["paths"]
    table_index_map = result["table_index_map"]
    table_to_path_index = result["table_to_path_index"]

    assert paths
    assert max(path["length"] for path in paths) <= 5
    assert all(path["hop_count"] == path["length"] - 1 for path in paths)
    assert all(path["row_count_estimate"] >= 0 for path in paths)
    assert table_to_path_index.shape == (len(table_index_map["tables"]), len(paths))

    orders_idx = table_index_map["table_to_index"]["orders"]
    products_idx = table_index_map["table_to_index"]["products"]
    covering = np.where(np.all(table_to_path_index[[orders_idx, products_idx]] == 1, axis=0))[0]
    assert len(covering) > 0

    order_product_paths = [paths[idx] for idx in covering]
    assert any("order_items" in path["tables_list"] for path in order_product_paths)
    best_order_item_edge = next(
        edge
        for path in order_product_paths
        for edge in path["join_edges"]
        if {edge["left_table"], edge["right_table"]} == {"orders", "order_items"}
    )
    assert {best_order_item_edge["left_col"], best_order_item_edge["right_col"]} == {"order_id"}

    assert (tmp_path / "orders" / JOIN_PATHS_ARTIFACT).exists()
    assert (tmp_path / "orders" / TABLE_TO_PATH_INDEX_ARTIFACT).exists()
    assert (tmp_path / "orders" / TABLE_INDEX_MAP_ARTIFACT).exists()
    assert (tmp_path / "orders" / JOIN_PATH_EMBEDDINGS_ARTIFACT).exists()
    assert (tmp_path / "orders" / JOIN_PATH_EMBEDDING_LABELS_ARTIFACT).exists()

    embeddings = np.load(tmp_path / "orders" / JOIN_PATH_EMBEDDINGS_ARTIFACT)
    assert embeddings.shape[0] == len(paths)
    assert embeddings.shape[1] == 3


def test_offline_join_artifact_service_builds_phase4_artifact_set(tmp_path):
    service = OfflineJoinArtifactService(
        DataLakeService(_root() / "datalake"),
        tmp_path,
        path_embedder=TinyEmbedder(),
        value_embedder=TinyEmbedder(),
    )

    result = service.build(
        "orders",
        equi_joinability_threshold=0.9,
        max_join_path_length=4,
        semantic_types=_semantic_types(),
        embedding_model="tiny",
    )

    assert result["join_graph"]["edges"]
    assert result["join_paths"]["paths"]
    assert result["table_to_path_index"].shape[1] == len(result["join_paths"]["paths"])

