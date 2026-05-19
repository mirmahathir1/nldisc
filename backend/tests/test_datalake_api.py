from __future__ import annotations

from pathlib import Path

import pytest

from backend.app import create_app
from backend.config import BackendConfig
from backend.services.datalake import DataLakeService, InvalidDataLakeName, sha256_file


@pytest.fixture()
def app():
    root = Path(__file__).resolve().parents[2]
    config = BackendConfig(
        project_root=root,
        datalake_dir=root / "datalake",
        preprocessed_dir=root / "preprocessed_data",
        openai_model="test-model",
        sample_row_limit=3,
        cors_origins=["*"],
    )
    return create_app(config)


@pytest.fixture()
def client(app):
    return app.test_client()


def test_list_lakes_returns_orders_and_country(client):
    response = client.get("/api/datalakes")

    assert response.status_code == 200
    payload = response.get_json()
    assert payload["status"] == "ok"
    assert set(payload["data"]["datalakes"]) >= {"orders", "country"}
    assert payload["error"] is None


def test_orders_summary_contains_csv_metadata(client):
    response = client.get("/api/datalakes/orders/summary")

    assert response.status_code == 200
    payload = response.get_json()
    data = payload["data"]
    tables = {table["name"]: table for table in data["tables"]}

    assert payload["status"] == "ok"
    assert data["name"] == "orders"
    assert data["table_count"] == 7
    assert data["total_rows"] > 0
    assert {"orders", "customers", "order_items", "products", "categories", "shipments", "query"} <= set(tables)
    assert tables["orders"]["columns"] == [
        "order_id",
        "customer_id",
        "order_date",
        "ship_country",
        "preferred_carrier",
        "customer_no",
        "order_no",
    ]
    assert tables["orders"]["row_count"] == 4
    assert len(tables["orders"]["sample_rows"]) == 3
    assert len(tables["orders"]["file_hash"]) == 64


def test_country_summary_contains_expected_tables(client):
    response = client.get("/api/datalakes/country/summary")

    assert response.status_code == 200
    payload = response.get_json()
    tables = {table["name"]: table for table in payload["data"]["tables"]}

    assert payload["data"]["name"] == "country"
    assert "currency" in tables
    assert tables["currency"]["columns"] == ["country", "currency"]
    assert tables["currency"]["row_count"] > 0


def test_unknown_lake_returns_error_envelope(client):
    response = client.get("/api/datalakes/missing/summary")

    assert response.status_code == 404
    payload = response.get_json()
    assert payload["status"] == "error"
    assert payload["data"] is None
    assert payload["error"]["code"] == "datalake_not_found"


def test_invalid_lake_name_returns_error_envelope(client):
    response = client.get("/api/datalakes/../summary")

    assert response.status_code == 400
    payload = response.get_json()
    assert payload["status"] == "error"
    assert payload["error"]["code"] == "invalid_datalake"


def test_datalake_service_hashes_files_stably():
    root = Path(__file__).resolve().parents[2]
    service = DataLakeService(root / "datalake")
    summary = service.summary("orders", sample_limit=2)
    orders = next(table for table in summary["tables"] if table["name"] == "orders")

    assert orders["file_hash"] == sha256_file(root / "datalake" / "orders" / "orders.csv")
    assert len(orders["sample_rows"]) == 2


def test_datalake_service_rejects_unsafe_names():
    root = Path(__file__).resolve().parents[2]
    service = DataLakeService(root / "datalake")

    with pytest.raises(InvalidDataLakeName):
        service.summary("../orders")
