from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from backend.config import BackendConfig
from backend.services.datalake import DataLakeService
from backend.services.embeddings import (
    TABLE_DESCRIPTION_EMBEDDINGS,
    TABLE_DESCRIPTION_HNSW,
    TABLE_DESCRIPTION_LABELS,
    TableDescriptionEmbeddingService,
    TextEmbedder,
)
from backend.services.join_detection import EXACT_JOINABILITY_ARTIFACT, JOIN_GRAPH_ARTIFACT, MINHASH_JACCARD_ARTIFACT
from backend.services.join_paths import (
    JOIN_PATH_EMBEDDING_LABELS_ARTIFACT,
    JOIN_PATH_EMBEDDINGS_ARTIFACT,
    JOIN_PATHS_ARTIFACT,
    TABLE_INDEX_MAP_ARTIFACT,
    TABLE_TO_PATH_INDEX_ARTIFACT,
)
from backend.services.json_io import read_json, write_json
from backend.services.llm import OpenAIResponsesLLM
from backend.services.offline_artifacts import OfflineJoinArtifactService
from backend.services.openai_cache import OpenAICache
from backend.services.semantic_types import SEMANTIC_TYPES_ARTIFACT, SemanticTypeService
from backend.services.table_descriptions import TABLE_DESCRIPTIONS_ARTIFACT, TableDescriptionService


METADATA_ARTIFACT = "metadata.json"
TABLES_ARTIFACT = "tables.json"
PREPROCESSING_VERSION = "phase5-v1"


DEFAULT_PREPROCESS_PARAMS = {
    "semantic_type_similarity_threshold": 0.75,
    "semantic_joinability_threshold": 0.75,
    "equi_joinability_threshold": 0.9,
    "max_join_path_length": 5,
}


REQUIRED_ARTIFACTS = [
    METADATA_ARTIFACT,
    TABLES_ARTIFACT,
    SEMANTIC_TYPES_ARTIFACT,
    TABLE_DESCRIPTIONS_ARTIFACT,
    TABLE_DESCRIPTION_EMBEDDINGS,
    TABLE_DESCRIPTION_HNSW,
    TABLE_DESCRIPTION_LABELS,
    MINHASH_JACCARD_ARTIFACT,
    EXACT_JOINABILITY_ARTIFACT,
    JOIN_GRAPH_ARTIFACT,
    JOIN_PATHS_ARTIFACT,
    TABLE_TO_PATH_INDEX_ARTIFACT,
    TABLE_INDEX_MAP_ARTIFACT,
    JOIN_PATH_EMBEDDINGS_ARTIFACT,
    JOIN_PATH_EMBEDDING_LABELS_ARTIFACT,
]


@dataclass
class PreprocessingService:
    config: BackendConfig
    datalake_service: DataLakeService
    llm: OpenAIResponsesLLM
    table_description_embedder: TextEmbedder | None = None
    join_path_embedder: TextEmbedder | None = None

    def preprocess(self, datalake: str, params: dict[str, Any] | None = None, *, force: bool = False) -> dict[str, Any]:
        normalized_params = normalize_preprocess_params(params)
        signature = self._signature(datalake, normalized_params)
        metadata_path = self._artifact_path(datalake, METADATA_ARTIFACT)

        if not force and self._metadata_matches(metadata_path, signature) and self._required_artifacts_exist(datalake):
            return self.load_artifacts(datalake, status="cached")

        started_at = _utc_now()
        tables_artifact = self._write_tables_artifact(datalake)

        semantic_types = SemanticTypeService(self.datalake_service, self.config.preprocessed_dir, self.llm).extract(
            datalake,
            force=True,
        )
        table_descriptions = TableDescriptionService(
            self.datalake_service,
            self.config.preprocessed_dir,
            self.llm,
        ).extract(datalake, semantic_types, force=True)
        table_description_index = TableDescriptionEmbeddingService(
            self.config.preprocessed_dir,
            model_name=self.config.embedding_model,
            embedder=self.table_description_embedder,
        ).build_index(datalake, table_descriptions, force=True)
        join_artifacts = OfflineJoinArtifactService(
            self.datalake_service,
            self.config.preprocessed_dir,
            path_embedder=self.join_path_embedder,
        ).build(
            datalake,
            equi_joinability_threshold=normalized_params["equi_joinability_threshold"],
            max_join_path_length=int(normalized_params["max_join_path_length"]),
            semantic_types=semantic_types,
            embedding_model=self.config.embedding_model,
        )

        metadata = {
            "schema_version": PREPROCESSING_VERSION,
            "datalake": datalake,
            "status": "ready",
            "created_at": started_at,
            "updated_at": _utc_now(),
            "signature": signature,
            "artifacts": {artifact: artifact for artifact in REQUIRED_ARTIFACTS},
            "table_count": len(tables_artifact["tables"]),
            "join_edge_count": len(join_artifacts["join_graph"]["edges"]),
            "join_path_count": len(join_artifacts["join_paths"]["paths"]),
            "table_description_index": {
                "dimensions": table_description_index["dimensions"],
                "table_count": table_description_index["table_count"],
            },
        }
        write_json(metadata_path, metadata)
        return self.load_artifacts(datalake, status="rebuilt")

    def load_artifacts(self, datalake: str, *, status: str = "loaded") -> dict[str, Any]:
        metadata_path = self._artifact_path(datalake, METADATA_ARTIFACT)
        if not metadata_path.exists():
            raise FileNotFoundError(f"No preprocessing metadata found for data lake {datalake!r}")

        metadata = _read_object(metadata_path)
        tables = _read_object(self._artifact_path(datalake, TABLES_ARTIFACT))
        table_descriptions = _read_object(self._artifact_path(datalake, TABLE_DESCRIPTIONS_ARTIFACT))
        semantic_types = _read_object(self._artifact_path(datalake, SEMANTIC_TYPES_ARTIFACT))
        join_graph = _read_object(self._artifact_path(datalake, JOIN_GRAPH_ARTIFACT))
        join_paths = _read_object(self._artifact_path(datalake, JOIN_PATHS_ARTIFACT))
        table_index_map = _read_object(self._artifact_path(datalake, TABLE_INDEX_MAP_ARTIFACT))
        table_description_labels = _read_object(self._artifact_path(datalake, TABLE_DESCRIPTION_LABELS))
        join_path_embedding_labels = _read_object(self._artifact_path(datalake, JOIN_PATH_EMBEDDING_LABELS_ARTIFACT))

        table_rows = tables.get("tables", [])
        row_counts = {table["name"]: table["row_count"] for table in table_rows}

        return {
            "preprocessing": {
                "status": status,
                "cached": status == "cached",
                "datalake": datalake,
            },
            "metadata": metadata,
            "tables": table_rows,
            "row_counts": row_counts,
            "semantic_types": semantic_types.get("tables", {}),
            "table_descriptions": table_descriptions.get("tables", {}),
            "table_description_index": table_description_labels,
            "join_edges": join_graph.get("edges", []),
            "join_graph": join_graph,
            "join_paths": join_paths.get("paths", []),
            "join_path_index": join_paths.get("paths", []),
            "table_index_map": table_index_map,
            "join_path_embedding_labels": join_path_embedding_labels,
        }

    def _write_tables_artifact(self, datalake: str) -> dict[str, Any]:
        profiles = self.datalake_service.table_profiles(datalake, sample_limit=self.config.sample_row_limit)
        artifact = {
            "schema_version": PREPROCESSING_VERSION,
            "datalake": datalake,
            "tables": profiles,
        }
        write_json(self._artifact_path(datalake, TABLES_ARTIFACT), artifact)
        return artifact

    def _signature(self, datalake: str, params: dict[str, Any]) -> dict[str, Any]:
        summary = self.datalake_service.summary(datalake, sample_limit=0)
        csv_hashes = {
            table["file_name"]: {
                "table": table["name"],
                "file_hash": table["file_hash"],
                "row_count": table["row_count"],
                "columns": table["columns"],
            }
            for table in sorted(summary["tables"], key=lambda item: item["file_name"])
        }
        return {
            "preprocessing_version": PREPROCESSING_VERSION,
            "csv_hashes": csv_hashes,
            "params": params,
            "openai_model": self.config.openai_model,
            "embedding_model": self.config.embedding_model,
            "metadata_schema_version": self.config.metadata_schema_version,
        }

    def _metadata_matches(self, metadata_path: Path, signature: dict[str, Any]) -> bool:
        if not metadata_path.exists():
            return False
        metadata = read_json(metadata_path)
        return isinstance(metadata, dict) and metadata.get("signature") == signature

    def _required_artifacts_exist(self, datalake: str) -> bool:
        return all(self._artifact_path(datalake, artifact).exists() for artifact in REQUIRED_ARTIFACTS)

    def _artifact_path(self, datalake: str, artifact: str) -> Path:
        return self.config.preprocessed_dir / datalake / artifact


def build_preprocessing_service(
    config: BackendConfig,
    datalake_service: DataLakeService,
    *,
    requester=None,
    table_description_embedder: TextEmbedder | None = None,
    join_path_embedder: TextEmbedder | None = None,
) -> PreprocessingService:
    llm = OpenAIResponsesLLM(
        OpenAICache(config.preprocessed_dir),
        config.openai_model,
        temperature=config.llm_temperature,
        requester=requester,
        schema_version=config.metadata_schema_version,
    )
    return PreprocessingService(
        config=config,
        datalake_service=datalake_service,
        llm=llm,
        table_description_embedder=table_description_embedder,
        join_path_embedder=join_path_embedder,
    )


def normalize_preprocess_params(params: dict[str, Any] | None) -> dict[str, Any]:
    merged = {**DEFAULT_PREPROCESS_PARAMS, **(params or {})}
    return {
        "semantic_type_similarity_threshold": float(merged["semantic_type_similarity_threshold"]),
        "semantic_joinability_threshold": float(merged["semantic_joinability_threshold"]),
        "equi_joinability_threshold": float(merged["equi_joinability_threshold"]),
        "max_join_path_length": int(merged["max_join_path_length"]),
    }


def _read_object(path: Path) -> dict[str, Any]:
    payload = read_json(path)
    if not isinstance(payload, dict):
        raise ValueError(f"Expected JSON object at {path}")
    return payload


def _utc_now() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds")
