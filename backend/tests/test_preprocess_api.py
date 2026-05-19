from __future__ import annotations

from pathlib import Path

import numpy as np
import pytest

from backend.app import create_app
from backend.config import BackendConfig
from backend.services.datalake import DataLakeService
from backend.services.preprocessing import (
    EXACT_JOINABILITY_ARTIFACT,
    JOIN_GRAPH_ARTIFACT,
    JOIN_PATHS_ARTIFACT,
    METADATA_ARTIFACT,
    TABLES_ARTIFACT,
    build_preprocessing_service,
)


class KeywordEmbedder:
    def encode(self, texts: list[str]) -> np.ndarray:
        vectors = []
        for text in texts:
            lower = text.lower()
            vectors.append(
                [
                    1.0,
                    float(lower.count("order") + lower.count("customer")),
                    float(lower.count("product") + lower.count("category")),
                    float(lower.count("shipment") + lower.count("carrier")),
                ]
            )
        return np.asarray(vectors, dtype=np.float32)


@pytest.fixture()
def preprocess_client(tmp_path):
    root = Path(__file__).resolve().parents[2]
    config = BackendConfig(
        project_root=root,
        datalake_dir=root / "datalake",
        preprocessed_dir=tmp_path,
        openai_model="test-model",
        sample_row_limit=3,
        cors_origins=["*"],
        embedding_model="fake-keywords",
    )
    calls = []

    def requester(**kwargs):
        response_model = kwargs["response_model"].__name__
        payload = kwargs["input_payload"]
        calls.append((response_model, payload["table_name"]))
        if response_model == "TableSemanticTypesResponse":
            return {
                "table_name": payload["table_name"],
                "columns": [
                    {
                        "column": column,
                        "semantic_type": f"{payload['table_name']} {column.replace('_', ' ')}",
                        "examples": payload.get("top_values", {}).get(column, [])[:2],
                    }
                    for column in payload["columns"]
                ],
            }
        if response_model == "TableDescriptionResponse":
            columns = ", ".join(column["semantic_type"] for column in payload["columns"][:3])
            return {
                "table_name": payload["table_name"],
                "description": f"{payload['table_name']} contains {columns}.",
            }
        raise AssertionError(f"Unexpected response model: {response_model}")

    app = create_app(config)
    datalake_service = DataLakeService(config.datalake_dir)
    app.config["DATALAKE_SERVICE"] = datalake_service
    app.config["PREPROCESSING_SERVICE"] = build_preprocessing_service(
        config,
        datalake_service,
        requester=requester,
        table_description_embedder=KeywordEmbedder(),
        join_path_embedder=KeywordEmbedder(),
    )
    return app.test_client(), tmp_path, calls


def test_preprocess_endpoint_builds_artifacts_and_reuses_cache(preprocess_client):
    client, preprocessed_dir, calls = preprocess_client
    payload = {
        "datalake": "orders",
        "params": {
            "semantic_type_similarity_threshold": 0.75,
            "semantic_joinability_threshold": 0.75,
            "equi_joinability_threshold": 0.9,
            "max_join_path_length": 4,
        },
    }

    first = client.post("/api/preprocess", json=payload)

    assert first.status_code == 200
    first_data = first.get_json()["data"]
    assert first_data["preprocessing"]["status"] == "rebuilt"
    assert first_data["metadata"]["signature"]["params"]["max_join_path_length"] == 4
    assert first_data["join_edges"]
    assert first_data["join_paths"]
    assert first_data["table_descriptions"]
    assert first_data["row_counts"]["orders"] == 4
    assert len(calls) == 14

    for artifact in [METADATA_ARTIFACT, TABLES_ARTIFACT, JOIN_GRAPH_ARTIFACT, EXACT_JOINABILITY_ARTIFACT, JOIN_PATHS_ARTIFACT]:
        assert (preprocessed_dir / "orders" / artifact).exists()

    fetched = client.get("/api/preprocess/orders/artifacts")
    assert fetched.status_code == 200
    fetched_data = fetched.get_json()["data"]
    assert fetched_data["preprocessing"]["status"] == "loaded"
    assert fetched_data["join_path_index"] == fetched_data["join_paths"]

    second = client.post("/api/preprocess", json=payload)
    assert second.status_code == 200
    second_data = second.get_json()["data"]
    assert second_data["preprocessing"]["status"] == "cached"
    assert second_data["preprocessing"]["cached"] is True
    assert len(calls) == 14

    changed = client.post(
        "/api/preprocess",
        json={
            **payload,
            "params": {
                **payload["params"],
                "equi_joinability_threshold": 0.95,
            },
        },
    )
    assert changed.status_code == 200
    changed_data = changed.get_json()["data"]
    assert changed_data["preprocessing"]["status"] == "rebuilt"
    assert changed_data["metadata"]["signature"]["params"]["equi_joinability_threshold"] == 0.95
    assert len(calls) == 14


def test_preprocess_artifacts_returns_404_before_build(preprocess_client):
    client, _preprocessed_dir, _calls = preprocess_client

    response = client.get("/api/preprocess/orders/artifacts")

    assert response.status_code == 404
    payload = response.get_json()
    assert payload["status"] == "error"
    assert payload["error"]["code"] == "preprocess_artifacts_not_found"

