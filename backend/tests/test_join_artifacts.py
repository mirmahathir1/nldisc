from __future__ import annotations

from pathlib import Path

import numpy as np

from backend.services.datalake import DataLakeService
from backend.services.join_detection import (
    EXACT_JOINABILITY_ARTIFACT,
    JOIN_GRAPH_ARTIFACT,
    MINHASH_JACCARD_ARTIFACT,
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
    service = JoinDetectionService(DataLakeService(_root() / "datalake"), tmp_path)

    result = service.discover("orders", JoinDetectionParams(equi_joinability_threshold=0.9))
    edges = result["join_graph"]["edges"]
    edge_keys = {(edge["left_table"], edge["left_col"], edge["right_table"], edge["right_col"]) for edge in edges}

    assert ("order_items", "order_id", "orders", "order_id") in edge_keys
    assert ("orders", "order_id", "shipments", "order_id") in edge_keys
    assert ("customers", "customer_id", "orders", "customer_id") in edge_keys
    assert ("order_items", "product_id", "products", "product_id") in edge_keys
    assert ("categories", "category_id", "products", "category_id") in edge_keys
    assert all(edge["left_table"] != edge["right_table"] for edge in edges)
    assert all(edge["edge_type"] == "equi" for edge in edges)

    assert (tmp_path / "orders" / JOIN_GRAPH_ARTIFACT).exists()
    assert (tmp_path / "orders" / MINHASH_JACCARD_ARTIFACT).exists()
    assert (tmp_path / "orders" / EXACT_JOINABILITY_ARTIFACT).exists()


def test_join_paths_respect_max_length_and_build_table_index(tmp_path):
    detector = JoinDetectionService(DataLakeService(_root() / "datalake"), tmp_path)
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

