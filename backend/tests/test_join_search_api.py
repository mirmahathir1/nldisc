from __future__ import annotations

from pathlib import Path

import numpy as np
import pytest

from backend.app import create_app
from backend.config import BackendConfig
from backend.services.datalake import DataLakeService
from backend.services.join_search import build_join_search_service
from backend.services.preprocessing import build_preprocessing_service


class KeywordEmbedder:
    def encode(self, texts: list[str]) -> np.ndarray:
        vectors = []
        for text in texts:
            lower = text.lower()
            vectors.append(
                [
                    1.0,
                    float(lower.count("order") + lower.count("customer")),
                    float(lower.count("product") + lower.count("category") + lower.count("quantity")),
                    float(lower.count("shipment") + lower.count("carrier")),
                    float(lower.count("country") + lower.count("currency") + lower.count("continent")),
                    float(lower.count("gdp") + lower.count("population")),
                    float(lower.count("literacy") + lower.count("life") + lower.count("health")),
                ]
            )
        return np.asarray(vectors, dtype=np.float32)


@pytest.fixture()
def join_search_client(tmp_path):
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

    def requester(**kwargs):
        response_model = kwargs["response_model"].__name__
        payload = kwargs["input_payload"]
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
            columns = ", ".join(column["semantic_type"] for column in payload["columns"][:4])
            return {
                "table_name": payload["table_name"],
                "description": f"{payload['table_name']} contains {columns}.",
            }
        raise AssertionError(f"Unexpected response model: {response_model}")

    app = create_app(config)
    datalake_service = DataLakeService(config.datalake_dir)
    embedder = KeywordEmbedder()
    app.config["DATALAKE_SERVICE"] = datalake_service
    app.config["PREPROCESSING_SERVICE"] = build_preprocessing_service(
        config,
        datalake_service,
        requester=requester,
        table_description_embedder=embedder,
        join_path_embedder=embedder,
    )
    app.config["JOIN_SEARCH_SERVICE"] = build_join_search_service(config, datalake_service)
    return app.test_client()


def test_join_search_returns_diverse_orders_paths_for_confirmed_query_table(join_search_client):
    client = join_search_client
    preprocess_response = client.post(
        "/api/preprocess",
        json={
            "datalake": "orders",
            "params": {
                "equi_joinability_threshold": 0.9,
                "max_join_path_length": 6,
            },
        },
    )
    assert preprocess_response.status_code == 200

    confirmed_rows = [
        {
            "Order ID": "O100",
            "Customer Country": "US",
            "Product": "Keyboard",
            "Quantity": "1",
            "Product Category": "Accessories",
            "Shipment Carrier": "DHL",
        },
        {
            "Order ID": "O101",
            "Customer Country": "SG",
            "Product": "Monitor",
            "Quantity": "1",
            "Product Category": "Displays",
            "Shipment Carrier": "UPS",
        },
        {
            "Order ID": "O102",
            "Customer Country": "US",
            "Product": "Keyboard",
            "Quantity": "1",
            "Product Category": "Accessories",
            "Shipment Carrier": "FedEx",
        },
    ]

    response = client.post(
        "/api/join-search",
        json={
            "datalake": "orders",
            "natural_language_query": "Show orders with customer country, ordered products, quantities, categories, and shipment carriers.",
            "confirmed_query_table_rows": confirmed_rows,
            "top_k": 5,
            "dedup_threshold": 0.95,
        },
    )

    assert response.status_code == 200
    data = response.get_json()["data"]
    assert data["coverage_mode"] == "strict"
    assert {"customers", "orders", "order_items", "products", "categories", "shipments"} <= set(data["required_tables"])
    assert data["join_paths"]
    assert data["deduplicated_path_count"] <= data["ranked_path_count"]

    best_path = data["join_paths"][0]
    assert {"customers", "orders", "order_items", "products", "categories", "shipments"} <= set(best_path["tables_list"])
    assert best_path["coverage"]["mode"] == "strict"
    assert best_path["matched_query_columns"]
    assert "query" not in best_path["tables_list"]


def test_join_search_country_falls_back_to_country_connected_subset(join_search_client):
    client = join_search_client
    preprocess_response = client.post(
        "/api/preprocess",
        json={
            "datalake": "country",
            "params": {
                "equi_joinability_threshold": 0.9,
                "max_join_path_length": 3,
            },
        },
    )
    assert preprocess_response.status_code == 200

    confirmed_rows = [
        {
            "Country": "United States",
            "Currency": "USD",
            "Continent": "Oceania",
            "GDP Per Capita": "81325.30120481928",
            "Population": "333.3",
            "Literacy Rate": "79.7",
            "Life Expectancy": "77.3",
        },
        {
            "Country": "China",
            "Currency": "CNY",
            "Continent": "Asia",
            "GDP Per Capita": "12544.294826364281",
            "Population": "1411.8",
            "Literacy Rate": "",
            "Life Expectancy": "",
        },
        {
            "Country": "Germany",
            "Currency": "EUR",
            "Continent": "Asia",
            "GDP Per Capita": "54216.867469879515",
            "Population": "83.3",
            "Literacy Rate": "",
            "Life Expectancy": "",
        },
    ]

    response = client.post(
        "/api/join-search",
        json={
            "datalake": "country",
            "natural_language_query": "Show countries with currency, continent, GDP per capita, population, literacy rate, and life expectancy.",
            "confirmed_query_table_rows": confirmed_rows,
            "top_k": 4,
            "dedup_threshold": 0.95,
        },
    )

    assert response.status_code == 200
    data = response.get_json()["data"]
    assert data["coverage_mode"] == "fallback_largest_subset"
    assert data["fallback"] is True
    assert data["join_paths"]
    assert {"GDP_Per_Capita_Completed", "census_data", "literacy_rates", "health_indicators"} & set(data["required_tables"])

    best_path = data["join_paths"][0]
    assert best_path["coverage"]["mode"] == "fallback_largest_subset"
    assert best_path["coverage"]["coverage_ratio"] > 0
    assert any(edge["left_col"].lower() == "country" or edge["right_col"].lower() == "country" for edge in best_path["join_edges"])
    assert "query" not in best_path["tables_list"]


def test_join_search_requires_preprocessing_artifacts(join_search_client):
    response = join_search_client.post(
        "/api/join-search",
        json={
            "datalake": "orders",
            "confirmed_query_table_rows": [{"Order ID": "O100"}],
        },
    )

    assert response.status_code == 404
    payload = response.get_json()
    assert payload["status"] == "error"
    assert payload["error"]["code"] == "preprocess_artifacts_not_found"
