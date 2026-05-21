from __future__ import annotations

from pathlib import Path

import numpy as np
import pytest

from backend.app import create_app
from backend.config import BackendConfig
from backend.services.datalake import DataLakeService
from backend.services.join_search import build_join_search_service
from backend.services.materialization import build_materialization_service
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
def materialization_client(tmp_path):
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
    app.config["MATERIALIZATION_SERVICE"] = build_materialization_service(
        config,
        datalake_service,
        embedder=embedder,
    )
    return app.test_client()


def test_join_path_sql_materialization_and_csv_for_orders_query(materialization_client):
    client = materialization_client
    preprocess = client.post(
        "/api/preprocess",
        json={
            "datalake": "orders",
            "params": {
                "equi_joinability_threshold": 0.9,
                "max_join_path_length": 6,
            },
        },
    )
    assert preprocess.status_code == 200

    join_search = client.post(
        "/api/join-search",
        json={
            "datalake": "orders",
            "natural_language_query": "Show orders with customer country, ordered products, quantities, categories, and shipment carriers.",
            "confirmed_query_table_rows": [
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
            ],
            "top_k": 3,
            "dedup_threshold": 0.95,
        },
    )
    assert join_search.status_code == 200
    path_id = join_search.get_json()["data"]["join_paths"][0]["path_id"]

    metadata = client.get(f"/api/join-paths/{path_id}?datalake=orders")
    assert metadata.status_code == 200
    metadata_data = metadata.get_json()["data"]
    assert metadata_data["path"]["path_id"] == path_id
    assert metadata_data["path"]["join_order"]

    sql_response = client.get(f"/api/join-paths/{path_id}/sql?datalake=orders")
    assert sql_response.status_code == 200
    sql_data = sql_response.get_json()["data"]
    sql = sql_data["sql"]
    assert 'JOIN "products"' in sql
    assert '"category_id"' in sql
    assert '"product_id"' in sql
    assert '"order_id"' in sql
    assert '"customer_id"' in sql

    materialized = client.get(f"/api/join-paths/{path_id}/materialize?datalake=orders&limit=10")
    assert materialized.status_code == 200
    materialized_data = materialized.get_json()["data"]
    assert materialized_data["row_count"] > 0
    assert materialized_data["preview_row_count"] > 0
    assert materialized_data["join_order"] == sql_data["join_order"]
    assert materialized_data["columns"] == sql_data["columns"]
    assert {"orders.order_id", "products.product", "shipments.carrier"} <= set(materialized_data["columns"])
    assert materialized_data["rows"][0]["orders.order_id"]

    csv_response = client.get(f"/api/join-paths/{path_id}/csv?datalake=orders")
    assert csv_response.status_code == 200
    assert csv_response.content_type.startswith("text/csv")
    csv_text = csv_response.get_data(as_text=True)
    assert csv_text.splitlines()[0].split(",") == materialized_data["columns"]
    assert len(csv_text.splitlines()) == materialized_data["row_count"] + 1


def test_country_selected_path_materialization_is_non_empty(materialization_client):
    client = materialization_client
    preprocess = client.post(
        "/api/preprocess",
        json={
            "datalake": "country",
            "params": {
                "equi_joinability_threshold": 0.9,
                "max_join_path_length": 3,
            },
        },
    )
    assert preprocess.status_code == 200

    join_search = client.post(
        "/api/join-search",
        json={
            "datalake": "country",
            "natural_language_query": "Show countries with currency, continent, GDP per capita, population, literacy rate, and life expectancy.",
            "confirmed_query_table_rows": [
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
                    "Country": "Australia",
                    "Currency": "AUD",
                    "Continent": "Oceania",
                    "GDP Per Capita": "65384.61538461538",
                    "Population": "26.4",
                    "Literacy Rate": "99.0",
                    "Life Expectancy": "83.0",
                },
            ],
            "top_k": 4,
            "dedup_threshold": 0.95,
        },
    )
    assert join_search.status_code == 200
    path_id = join_search.get_json()["data"]["join_paths"][0]["path_id"]

    materialized = client.get(f"/api/join-paths/{path_id}/materialize?datalake=country&limit=5")
    assert materialized.status_code == 200
    data = materialized.get_json()["data"]
    assert data["row_count"] > 0
    assert data["preview_row_count"] > 0
    assert any(column.endswith(".country") for column in data["columns"])


def test_join_path_materialize_projects_on_query_columns(materialization_client):
    client = materialization_client
    assert client.post(
        "/api/preprocess",
        json={
            "datalake": "orders",
            "params": {"equi_joinability_threshold": 0.9, "max_join_path_length": 6},
        },
    ).status_code == 200

    join_search = client.post(
        "/api/join-search",
        json={
            "datalake": "orders",
            "natural_language_query": "Show orders with customer country, ordered products, quantities, categories, and shipment carriers.",
            "confirmed_query_table_rows": [
                {
                    "Order ID": "O100",
                    "Customer Country": "US",
                    "Product": "Keyboard",
                    "Quantity": "1",
                    "Product Category": "Accessories",
                    "Shipment Carrier": "DHL",
                },
            ],
            "top_k": 1,
            "dedup_threshold": 0.95,
        },
    )
    assert join_search.status_code == 200
    path_id = join_search.get_json()["data"]["join_paths"][0]["path_id"]

    full = client.get(f"/api/join-paths/{path_id}/materialize?datalake=orders&limit=10").get_json()["data"]
    full_columns = full["columns"]

    projected = client.post(
        f"/api/join-paths/{path_id}/materialize",
        json={
            "datalake": "orders",
            "limit": 10,
            "query_columns": ["Customer Country", "Product", "Shipment Carrier"],
            "query_semantic_types": {
                "Customer Country": "customer country",
                "Product": "product name",
                "Shipment Carrier": "shipment carrier",
            },
        },
    )
    assert projected.status_code == 200
    data = projected.get_json()["data"]
    assert data["projection"], "projection metadata should be included"
    assert set(data["columns"]).issubset(set(full_columns))
    assert len(data["columns"]) <= 3
    assert len(data["projection"]["column_mapping"]) == 3
    for entry in data["projection"]["column_mapping"]:
        assert entry["lake_column"] in full_columns
        assert entry["cosine_similarity"] >= 0.0
    for row in data["rows"]:
        assert set(row.keys()).issubset(set(data["columns"]))

    csv_response = client.post(
        f"/api/join-paths/{path_id}/csv",
        json={
            "datalake": "orders",
            "query_columns": ["Customer Country", "Product"],
            "query_semantic_types": {
                "Customer Country": "customer country",
                "Product": "product name",
            },
        },
    )
    assert csv_response.status_code == 200
    assert csv_response.content_type.startswith("text/csv")
    csv_header = csv_response.get_data(as_text=True).splitlines()[0].split(",")
    assert set(csv_header) <= set(full_columns)
    assert len(csv_header) <= 2


def test_join_path_endpoints_report_missing_path(materialization_client):
    client = materialization_client
    preprocess = client.post(
        "/api/preprocess",
        json={
            "datalake": "orders",
            "params": {
                "equi_joinability_threshold": 0.9,
                "max_join_path_length": 4,
            },
        },
    )
    assert preprocess.status_code == 200

    response = client.get("/api/join-paths/jp_missing?datalake=orders")

    assert response.status_code == 404
    payload = response.get_json()
    assert payload["status"] == "error"
    assert payload["error"]["code"] == "join_path_not_found"
