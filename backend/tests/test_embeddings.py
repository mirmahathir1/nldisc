from __future__ import annotations

import numpy as np

from backend.services.embeddings import (
    TABLE_DESCRIPTION_EMBEDDINGS,
    TABLE_DESCRIPTION_HNSW,
    TABLE_DESCRIPTION_LABELS,
    TableDescriptionEmbeddingService,
)


class KeywordEmbedder:
    def encode(self, texts: list[str]) -> np.ndarray:
        vectors = []
        for text in texts:
            lower = text.lower()
            vectors.append(
                [
                    _count(lower, "order", "customer", "shipment", "carrier"),
                    _count(lower, "product", "category", "quantity", "family"),
                    _count(lower, "country", "currency", "continent"),
                    _count(lower, "gdp", "population", "literacy", "life expectancy"),
                ]
            )
        return np.asarray(vectors, dtype=np.float32)


def _count(text: str, *terms: str) -> float:
    return float(sum(text.count(term) for term in terms))


def _table_descriptions() -> dict:
    return {
        "schema_version": "table-descriptions-v1",
        "datalake": "orders",
        "tables": {
            "orders": {
                "description": "Orders contains customer order dates, ship countries, and preferred shipment carriers.",
                "cache_key": "orders-cache",
            },
            "products": {
                "description": "Products contains product names, product families, categories, and product identifiers.",
                "cache_key": "products-cache",
            },
            "country_profiles": {
                "description": "Country profiles contain country currency, continent, GDP, population, literacy, and life expectancy fields.",
                "cache_key": "country-cache",
            },
        },
    }


def test_build_table_description_index_persists_artifacts(tmp_path):
    service = TableDescriptionEmbeddingService(tmp_path, model_name="fake-keywords", embedder=KeywordEmbedder())

    artifact = service.build_index("orders", _table_descriptions())

    assert artifact["schema_version"] == "table-description-index-v1"
    assert artifact["embedding_model"] == "fake-keywords"
    assert artifact["dimensions"] == 4
    assert artifact["table_count"] == 3
    assert [label["vector_id"] for label in artifact["labels"]] == [0, 1, 2]
    assert (tmp_path / "orders" / TABLE_DESCRIPTION_EMBEDDINGS).exists()
    assert (tmp_path / "orders" / TABLE_DESCRIPTION_HNSW).exists()
    assert (tmp_path / "orders" / TABLE_DESCRIPTION_LABELS).exists()

    embeddings = np.load(tmp_path / "orders" / TABLE_DESCRIPTION_EMBEDDINGS)
    assert embeddings.shape == (3, 4)
    assert np.allclose(np.linalg.norm(embeddings, axis=1), np.ones(3))


def test_retrieve_ranks_context_tables_from_hnsw_index(tmp_path):
    service = TableDescriptionEmbeddingService(tmp_path, model_name="fake-keywords", embedder=KeywordEmbedder())
    service.build_index("orders", _table_descriptions())

    product_results = service.retrieve("orders", "Show products with categories and quantity.", top_k=2)
    country_results = service.retrieve("orders", "Show countries with currency, GDP, population, and literacy.", top_k=2)

    assert product_results[0]["table_name"] == "products"
    assert product_results[0]["score"] > product_results[1]["score"]
    assert country_results[0]["table_name"] == "country_profiles"
    assert country_results[0]["score"] > country_results[1]["score"]


def test_build_index_reuses_existing_artifacts_without_reembedding(tmp_path):
    class CountingEmbedder(KeywordEmbedder):
        def __init__(self) -> None:
            self.calls = 0

        def encode(self, texts: list[str]) -> np.ndarray:
            self.calls += 1
            return super().encode(texts)

    embedder = CountingEmbedder()
    service = TableDescriptionEmbeddingService(tmp_path, model_name="fake-keywords", embedder=embedder)

    first = service.build_index("orders", _table_descriptions())
    second = service.build_index("orders", _table_descriptions())

    assert second == first
    assert embedder.calls == 1

