from __future__ import annotations

import os
from dataclasses import dataclass
from pathlib import Path


try:
    from dotenv import load_dotenv
except ImportError:  # pragma: no cover - dependency is installed in the backend env
    load_dotenv = None


BACKEND_DIR = Path(__file__).resolve().parent
PROJECT_ROOT = BACKEND_DIR.parent


@dataclass(frozen=True)
class BackendConfig:
    project_root: Path
    datalake_dir: Path
    preprocessed_dir: Path
    openai_model: str
    sample_row_limit: int
    cors_origins: list[str]
    llm_temperature: float = 0.0
    metadata_schema_version: str = "phase2-v1"


def _split_origins(value: str) -> list[str]:
    origins = [origin.strip() for origin in value.split(",") if origin.strip()]
    return origins or ["*"]


def load_config() -> BackendConfig:
    env_file = BACKEND_DIR / ".env"
    if load_dotenv is not None:
        load_dotenv(env_file)

    datalake_dir = Path(os.getenv("DATALAKE_DIR", PROJECT_ROOT / "datalake")).resolve()
    preprocessed_dir = Path(os.getenv("PREPROCESSED_DIR", PROJECT_ROOT / "preprocessed_data")).resolve()

    return BackendConfig(
        project_root=PROJECT_ROOT,
        datalake_dir=datalake_dir,
        preprocessed_dir=preprocessed_dir,
        openai_model=os.getenv("OPENAI_MODEL", "gpt-5.5"),
        sample_row_limit=int(os.getenv("SUMMARY_SAMPLE_ROW_LIMIT", "5")),
        cors_origins=_split_origins(os.getenv("CORS_ORIGINS", "*")),
        llm_temperature=float(os.getenv("OPENAI_TEMPERATURE", "0")),
        metadata_schema_version=os.getenv("METADATA_SCHEMA_VERSION", "phase2-v1"),
    )
