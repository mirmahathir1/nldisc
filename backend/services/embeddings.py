from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Any, Protocol

import hnswlib
import numpy as np

from backend.services.json_io import read_json, write_json


TABLE_DESCRIPTION_EMBEDDINGS = "table_description_embeddings.npy"
TABLE_DESCRIPTION_HNSW = "table_description_hnsw.bin"
TABLE_DESCRIPTION_LABELS = "table_description_labels.json"
TABLE_DESCRIPTION_INDEX_SCHEMA_VERSION = "table-description-index-v1"
DEFAULT_EMBEDDING_MODEL = "sentence-transformers/all-mpnet-base-v2"


class TextEmbedder(Protocol):
    def encode(self, texts: list[str]) -> np.ndarray:
        ...


class SentenceTransformerEmbedder:
    def __init__(self, model_name: str = DEFAULT_EMBEDDING_MODEL) -> None:
        self.model_name = model_name
        self._model = None

    def encode(self, texts: list[str]) -> np.ndarray:
        if self._model is None:
            from sentence_transformers import SentenceTransformer

            self._model = SentenceTransformer(self.model_name)
        embeddings = self._model.encode(
            texts,
            convert_to_numpy=True,
            normalize_embeddings=True,
            show_progress_bar=False,
        )
        return np.asarray(embeddings, dtype=np.float32)


@dataclass
class TableDescriptionEmbeddingService:
    preprocessed_dir: Path
    model_name: str = DEFAULT_EMBEDDING_MODEL
    embedder: TextEmbedder | None = None

    def build_index(self, datalake: str, table_descriptions: dict[str, Any], *, force: bool = False) -> dict[str, Any]:
        labels_path = self._labels_path(datalake)
        embeddings_path = self._embeddings_path(datalake)
        hnsw_path = self._hnsw_path(datalake)
        if labels_path.exists() and embeddings_path.exists() and hnsw_path.exists() and not force:
            labels = read_json(labels_path)
            if isinstance(labels, dict):
                return labels

        labels = self._description_labels(datalake, table_descriptions)
        descriptions = [label["description"] for label in labels]
        if not descriptions:
            raise ValueError(f"No table descriptions available for data lake {datalake!r}")

        embeddings = _normalize_embeddings(self._get_embedder().encode(descriptions))
        if embeddings.ndim != 2 or embeddings.shape[0] != len(labels):
            raise ValueError("Embedder returned an invalid embedding matrix")

        embeddings_path.parent.mkdir(parents=True, exist_ok=True)
        np.save(embeddings_path, embeddings)
        self._write_hnsw_index(hnsw_path, embeddings)

        artifact = {
            "schema_version": TABLE_DESCRIPTION_INDEX_SCHEMA_VERSION,
            "datalake": datalake,
            "embedding_model": self.model_name,
            "metric": "cosine",
            "dimensions": int(embeddings.shape[1]),
            "table_count": len(labels),
            "labels": labels,
            "artifacts": {
                "embeddings": TABLE_DESCRIPTION_EMBEDDINGS,
                "hnsw": TABLE_DESCRIPTION_HNSW,
                "labels": TABLE_DESCRIPTION_LABELS,
            },
        }
        write_json(labels_path, artifact)
        return artifact

    def retrieve(self, datalake: str, query: str, *, top_k: int = 5, ef: int = 50) -> list[dict[str, Any]]:
        labels_artifact = self._load_labels(datalake)
        labels = labels_artifact["labels"]
        if not labels:
            return []

        query_embedding = _normalize_embeddings(self._get_embedder().encode([query]))
        if query_embedding.shape[1] != labels_artifact["dimensions"]:
            raise ValueError(
                f"Query embedding dimension {query_embedding.shape[1]} does not match index dimension "
                f"{labels_artifact['dimensions']}"
            )

        index = hnswlib.Index(space="cosine", dim=labels_artifact["dimensions"])
        index.load_index(str(self._hnsw_path(datalake)))
        index.set_ef(max(ef, min(top_k, len(labels))))

        ids, distances = index.knn_query(query_embedding, k=min(top_k, len(labels)))
        by_id = {label["vector_id"]: label for label in labels}
        results: list[dict[str, Any]] = []
        for vector_id, distance in zip(ids[0].tolist(), distances[0].tolist()):
            label = by_id[int(vector_id)]
            results.append(
                {
                    "table_name": label["table_name"],
                    "description": label["description"],
                    "vector_id": int(vector_id),
                    "distance": float(distance),
                    "score": float(1.0 - distance),
                }
            )
        return results

    def _description_labels(self, datalake: str, table_descriptions: dict[str, Any]) -> list[dict[str, Any]]:
        tables = table_descriptions.get("tables", {})
        labels: list[dict[str, Any]] = []
        for table_name in sorted(tables):
            description = " ".join(str(tables[table_name].get("description", "")).split())
            if not description:
                continue
            labels.append(
                {
                    "vector_id": len(labels),
                    "table_name": table_name,
                    "description": description,
                    "source_cache_key": tables[table_name].get("cache_key"),
                }
            )
        return labels

    def _write_hnsw_index(self, path: Path, embeddings: np.ndarray) -> None:
        index = hnswlib.Index(space="cosine", dim=int(embeddings.shape[1]))
        index.init_index(max_elements=int(embeddings.shape[0]), ef_construction=100, M=16)
        index.add_items(embeddings, np.arange(embeddings.shape[0]))
        index.set_ef(min(50, max(1, embeddings.shape[0])))
        path.parent.mkdir(parents=True, exist_ok=True)
        index.save_index(str(path))

    def _load_labels(self, datalake: str) -> dict[str, Any]:
        labels = read_json(self._labels_path(datalake))
        if not isinstance(labels, dict):
            raise ValueError(f"Invalid labels artifact for data lake {datalake!r}")
        return labels

    def _get_embedder(self) -> TextEmbedder:
        if self.embedder is None:
            self.embedder = SentenceTransformerEmbedder(self.model_name)
        return self.embedder

    def _lake_dir(self, datalake: str) -> Path:
        return self.preprocessed_dir / datalake

    def _embeddings_path(self, datalake: str) -> Path:
        return self._lake_dir(datalake) / TABLE_DESCRIPTION_EMBEDDINGS

    def _hnsw_path(self, datalake: str) -> Path:
        return self._lake_dir(datalake) / TABLE_DESCRIPTION_HNSW

    def _labels_path(self, datalake: str) -> Path:
        return self._lake_dir(datalake) / TABLE_DESCRIPTION_LABELS


def _normalize_embeddings(embeddings: np.ndarray) -> np.ndarray:
    matrix = np.asarray(embeddings, dtype=np.float32)
    if matrix.ndim == 1:
        matrix = matrix.reshape(1, -1)
    norms = np.linalg.norm(matrix, axis=1, keepdims=True)
    norms[norms == 0] = 1.0
    return matrix / norms
