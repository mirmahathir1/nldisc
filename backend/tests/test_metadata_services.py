from __future__ import annotations

from pathlib import Path

import pytest

from backend.services.datalake import DataLakeService
from backend.services.llm import OpenAIResponsesLLM
from backend.services.openai_cache import OpenAICache
from backend.services.semantic_types import SemanticTypeService
from backend.services.table_descriptions import TableDescriptionService


def _root() -> Path:
    return Path(__file__).resolve().parents[2]


def test_semantic_type_service_writes_artifact_and_maps_real_columns(tmp_path):
    calls = []

    def requester(**kwargs):
        payload = kwargs["input_payload"]
        calls.append(payload["table_name"])
        return {
            "table_name": payload["table_name"],
            "columns": [
                {
                    "column": column.replace("_", " "),
                    "semantic_type": f"{column.replace('_', ' ')} semantic type",
                    "examples": payload["top_values"].get(column, [])[:2],
                }
                for column in payload["columns"]
            ],
        }

    datalake_service = DataLakeService(_root() / "datalake")
    llm = OpenAIResponsesLLM(OpenAICache(tmp_path), "test-model", requester=requester)
    service = SemanticTypeService(datalake_service, tmp_path, llm)

    artifact = service.extract("orders")
    orders_columns = artifact["tables"]["orders"]["columns"]

    assert set(artifact["tables"]) >= {"orders", "customers", "order_items", "products", "categories", "shipments", "query"}
    assert "order_id" in orders_columns
    assert "order id" not in orders_columns
    assert orders_columns["order_id"]["semantic_type"] == "order id semantic type"
    assert orders_columns["order_id"]["source"] == "openai"
    assert (tmp_path / "orders" / "semantic_types.json").exists()
    assert len(list((tmp_path / "orders" / "openai_cache").glob("*.json"))) == 7

    cached_artifact = service.extract("orders")
    assert cached_artifact == artifact
    assert len(calls) == 7


def test_semantic_type_service_rejects_unknown_returned_columns(tmp_path):
    def requester(**kwargs):
        return {
            "table_name": kwargs["input_payload"]["table_name"],
            "columns": [{"column": "not_a_real_column", "semantic_type": "bad", "examples": []}],
        }

    service = SemanticTypeService(
        DataLakeService(_root() / "datalake"),
        tmp_path,
        OpenAIResponsesLLM(OpenAICache(tmp_path), "test-model", requester=requester),
    )

    with pytest.raises(ValueError, match="unknown column"):
        service.extract("orders")


def test_table_description_service_writes_one_sentence_artifact_and_reuses_it(tmp_path):
    calls = []
    semantic_types = {
        "datalake": "orders",
        "tables": {
            "orders": {
                "columns": {
                    "order_id": {"semantic_type": "order identifier"},
                    "customer_id": {"semantic_type": "customer identifier"},
                }
            }
        },
    }

    def requester(**kwargs):
        payload = kwargs["input_payload"]
        calls.append(payload["table_name"])
        return {
            "table_name": payload["table_name"],
            "description": "Orders contains order, customer, date, country, and carrier details. Extra sentence ignored.",
        }

    service = TableDescriptionService(
        DataLakeService(_root() / "datalake"),
        tmp_path,
        OpenAIResponsesLLM(OpenAICache(tmp_path), "test-model", requester=requester),
    )

    artifact = service.extract("orders", semantic_types)

    assert artifact["tables"]["orders"]["description"] == "Orders contains order, customer, date, country, and carrier details."
    assert artifact["tables"]["orders"]["source"] == "openai"
    assert (tmp_path / "orders" / "table_descriptions.json").exists()

    cached_artifact = service.extract("orders", semantic_types)
    assert cached_artifact == artifact
    assert calls == ["orders"]

