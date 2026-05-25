from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Any

from backend.services.datalake import DataLakeService
from backend.services.embeddings import TextEmbedder
from backend.services.join_detection import JoinDetectionParams, JoinDetectionService
from backend.services.join_paths import JoinPathParams, JoinPathService


@dataclass
class OfflineJoinArtifactService:
    datalake_service: DataLakeService
    preprocessed_dir: Path
    path_embedder: TextEmbedder | None = None
    value_embedder: TextEmbedder | None = None

    def build(
        self,
        datalake: str,
        *,
        equi_joinability_threshold: float = 0.9,
        semantic_joinability_threshold: float = 0.75,
        semantic_type_similarity_threshold: float = 0.3,
        max_join_path_length: int = 4,
        semantic_types: dict[str, Any] | None = None,
        embedding_model: str = "sentence-transformers/all-mpnet-base-v2",
    ) -> dict[str, Any]:
        detection = JoinDetectionService(
            self.datalake_service, self.preprocessed_dir, embedder=self.value_embedder
        )
        detected = detection.discover(
            datalake,
            JoinDetectionParams(
                equi_joinability_threshold=equi_joinability_threshold,
                semantic_joinability_threshold=semantic_joinability_threshold,
                semantic_type_similarity_threshold=semantic_type_similarity_threshold,
            ),
            semantic_types=semantic_types,
        )
        paths = JoinPathService(self.preprocessed_dir, embedder=self.path_embedder).build(
            datalake,
            detected["join_graph"],
            detected["tables"],
            semantic_types=semantic_types,
            params=JoinPathParams(max_join_path_length=max_join_path_length, embedding_model=embedding_model),
        )
        return {
            "join_graph": detected["join_graph"],
            "minhash_jaccard": detected["minhash_jaccard"],
            "exact_joinability": detected["exact_joinability"],
            "semantic_joinability": detected["semantic_joinability"],
            **paths,
        }
