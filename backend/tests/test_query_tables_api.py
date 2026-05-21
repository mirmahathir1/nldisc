from __future__ import annotations

from pathlib import Path

import numpy as np
import pytest

from backend.app import create_app
from backend.config import BackendConfig
from backend.services.datalake import DataLakeService
from backend.services.preprocessing import build_preprocessing_service
from backend.services.query_tables import build_query_table_service


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
                    float(lower.count("country") + lower.count("currency") + lower.count("gdp")),
                ]
            )
        return np.asarray(vectors, dtype=np.float32)


@pytest.fixture()
def query_client(tmp_path):
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
        calls.append((response_model, payload.get("table_name") or payload.get("natural_language_query")))
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
        if response_model == "QueryTableSuggestionsResponse":
            count = payload["suggestion_count"]
            context_names = [table["table_name"] for table in payload["context_tables"]]
            is_resubmit = "edited_query_table" in payload
            assert "orders" in context_names or "edited_query_table" in payload
            assert "products" in context_names or "order_items" in context_names
            if is_resubmit:
                evidence_tables = {
                    match["table_name"]
                    for column in payload["candidate_column_evidence"]
                    for match in column["matches"]
                }
                assert {"products", "order_items"} <= evidence_tables
            columns = (
                [
                    {"name": "Order ID", "semantic_type": "order identifier"},
                    {"name": "Product Family", "semantic_type": "product family"},
                    {"name": "Quantity", "semantic_type": "ordered quantity"},
                    {"name": "Carrier", "semantic_type": "shipment carrier"},
                ]
                if is_resubmit
                else [
                    {"name": "Order ID", "semantic_type": "order identifier"},
                    {"name": "Product", "semantic_type": "ordered product"},
                    {"name": "Carrier", "semantic_type": "shipment carrier"},
                ]
            )
            row_dicts = (
                [
                    {"Order ID": "O100", "Product Family": "Accessories", "Quantity": "1", "Carrier": "DHL"},
                    {"Order ID": "O101", "Product Family": "Accessories", "Quantity": "2", "Carrier": "UPS"},
                    {"Order ID": "O102", "Product Family": "Displays", "Quantity": "1", "Carrier": "FedEx"},
                ]
                if is_resubmit
                else [
                    {"Order ID": "O100", "Product": "Keyboard", "Carrier": "DHL"},
                    {"Order ID": "O101", "Product": "Mouse", "Carrier": "UPS"},
                    {"Order ID": "O102", "Product": "Monitor", "Carrier": "FedEx"},
                ]
            )
            # Match the cell-list wire shape the strict Structured Outputs schema
            # demands; `_normalize_suggestion` re-keys cells back into a dict.
            rows = [
                {"cells": [{"column": k, "value": v} for k, v in row.items()]}
                for row in row_dicts
            ]
            return {
                "suggestions": [
                    {
                        "name": f"{'Revised' if is_resubmit else 'Suggested'} Query Table {idx + 1}",
                        "columns": columns,
                        "rows": rows,
                    }
                    for idx in range(count)
                ]
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
    app.config["QUERY_TABLE_SERVICE"] = build_query_table_service(
        config,
        datalake_service,
        requester=requester,
        retrieval_embedder=embedder,
    )
    return app.test_client(), calls


def test_sample_queries_endpoint_returns_orders_queries(query_client):
    client, _calls = query_client

    response = client.get("/api/sample-queries?datalake=orders")

    assert response.status_code == 200
    data = response.get_json()["data"]
    assert data["datalake"] == "orders"
    assert [query["label"] for query in data["queries"]] == ["Query 1", "Query 2"]
    assert "shipment carriers" in data["queries"][0]["query"]


def test_query_tables_endpoint_generates_suggestions_with_context_and_cache(query_client):
    client, calls = query_client
    preprocess_response = client.post(
        "/api/preprocess",
        json={
            "datalake": "orders",
            "params": {
                "equi_joinability_threshold": 0.9,
                "max_join_path_length": 4,
            },
        },
    )
    assert preprocess_response.status_code == 200
    assert len(calls) == 14

    payload = {
        "datalake": "orders",
        "natural_language_query": "Show orders with customer country, ordered products, quantities, categories, and shipment carriers.",
        "desired_suggestion_count": 2,
        "ann_topk": 5,
    }
    first = client.post("/api/query-tables", json=payload)

    assert first.status_code == 200
    first_data = first.get_json()["data"]
    assert len(first_data["query_tables"]) == 2
    assert first_data["queryTables"] == first_data["query_tables"]
    assert first_data["query_tables"][0]["name"] == "Suggested Query Table 1"
    assert first_data["query_tables"][0]["columns"] == ["Order ID", "Product", "Carrier"]
    assert len(first_data["query_tables"][0]["rows"]) == 3
    assert first_data["query_tables"][0]["rows"][0] == {
        "Order ID": "O100",
        "Product": "Keyboard",
        "Carrier": "DHL",
    }
    assert first_data["candidate_context_tables"]
    assert first_data["cache_hit"] is False
    assert len(calls) == 15

    second = client.post("/api/query-tables", json=payload)
    second_data = second.get_json()["data"]
    assert second.status_code == 200
    assert second_data["cache_hit"] is True
    assert second_data["query_tables"] == first_data["query_tables"]
    assert len(calls) == 15


def test_query_tables_endpoint_requires_preprocessing_artifacts(query_client):
    client, _calls = query_client

    response = client.post(
        "/api/query-tables",
        json={
            "datalake": "orders",
            "natural_language_query": "Show orders with products.",
            "desired_suggestion_count": 1,
        },
    )

    assert response.status_code == 404
    payload = response.get_json()
    assert payload["status"] == "error"
    assert payload["error"]["code"] == "preprocess_artifacts_not_found"


def test_query_table_resubmit_preserves_edit_and_returns_evidence(query_client):
    client, calls = query_client
    preprocess_response = client.post(
        "/api/preprocess",
        json={
            "datalake": "orders",
            "params": {
                "equi_joinability_threshold": 0.9,
                "max_join_path_length": 4,
            },
        },
    )
    assert preprocess_response.status_code == 200
    assert len(calls) == 14

    edited_rows = [
        {"Order ID": "O100", "product_family": "Accessories", "Quantity": "1", "Carrier": "DHL"},
        {"Order ID": "O101", "product_family": "Accessories", "Quantity": "2", "Carrier": "UPS"},
        {"Order ID": "O102", "product_family": "Displays", "Quantity": "1", "Carrier": "FedEx"},
    ]
    response = client.post(
        "/api/query-tables/resubmit",
        json={
            "datalake": "orders",
            "natural_language_query": "Build a table of customers, orders, product families, quantities, and preferred carriers.",
            "edited_query_table_rows": edited_rows,
            "prior_selected_table_name": "Edited Product Family Table",
            "desired_suggestion_count": 3,
            "ann_topk": 6,
        },
    )

    assert response.status_code == 200
    data = response.get_json()["data"]
    assert data["query_tables"][0]["name"] == "Edited Product Family Table"
    assert data["query_tables"][0]["rows"] == edited_rows
    assert data["query_tables"][1]["name"] == "Revised Query Table 1"
    assert data["cache_hit"] is False
    assert len(calls) == 15

    evidence_tables = {
        match["table_name"]
        for column in data["candidate_column_evidence"]
        for match in column["matches"]
    }
    assert {"products", "order_items"} <= evidence_tables

    product_family_evidence = next(
        column for column in data["candidate_column_evidence"] if column["query_column"] == "product_family"
    )
    assert product_family_evidence["matches"][0]["table_name"] == "products"
    assert product_family_evidence["matches"][0]["column"] == "product_family"

    cached = client.post(
        "/api/query-tables/resubmit",
        json={
            "datalake": "orders",
            "natural_language_query": "Build a table of customers, orders, product families, quantities, and preferred carriers.",
            "edited_query_table_rows": edited_rows,
            "prior_selected_table_name": "Edited Product Family Table",
            "desired_suggestion_count": 3,
            "ann_topk": 6,
        },
    )
    cached_data = cached.get_json()["data"]
    assert cached.status_code == 200
    assert cached_data["cache_hit"] is True
    assert cached_data["query_tables"] == data["query_tables"]
    assert len(calls) == 15
