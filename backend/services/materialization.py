from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Any

import pandas as pd

from backend.config import BackendConfig
from backend.services.datalake import DataLakeService
from backend.services.join_paths import JOIN_PATHS_ARTIFACT
from backend.services.json_io import read_json


@dataclass
class MaterializationService:
    config: BackendConfig
    datalake_service: DataLakeService

    def path_metadata(self, datalake: str, path_id: str) -> dict[str, Any]:
        path = self._path_record(datalake, path_id)
        aliases = _aliases_for(path["tables_list"])
        return {
            "datalake": datalake,
            "path": _path_payload(path, aliases),
            "join_path": _path_payload(path, aliases),
        }

    def sql(self, datalake: str, path_id: str) -> dict[str, Any]:
        path = self._path_record(datalake, path_id)
        tables = self._load_path_tables(datalake, path)
        aliases = _aliases_for(path["tables_list"])
        columns = _prefixed_columns(path["tables_list"], tables)
        sql = _sql_for_path(path, tables, aliases)
        return {
            "datalake": datalake,
            "path_id": path["path_id"],
            "sql": sql,
            "columns": columns,
            "join_order": path.get("join_order", []),
            "aliases": aliases,
        }

    def materialize(self, datalake: str, path_id: str, *, limit: int = 50) -> dict[str, Any]:
        path = self._path_record(datalake, path_id)
        tables = self._load_path_tables(datalake, path)
        aliases = _aliases_for(path["tables_list"])
        materialized = _materialized_frame(path, tables)
        preview = materialized.head(max(0, int(limit)))
        rows = preview.to_dict(orient="records")
        columns = list(materialized.columns)
        return {
            "datalake": datalake,
            "path_id": path["path_id"],
            "columns": columns,
            "rows": rows,
            "row_count": int(len(materialized)),
            "preview_row_count": len(rows),
            "limit": max(0, int(limit)),
            "join_order": path.get("join_order", []),
            "aliases": aliases,
        }

    def csv(self, datalake: str, path_id: str) -> tuple[str, str]:
        path = self._path_record(datalake, path_id)
        tables = self._load_path_tables(datalake, path)
        materialized = _materialized_frame(path, tables)
        filename = f"nldisc_{datalake}_{path['path_id']}.csv"
        return materialized.to_csv(index=False), filename

    def _path_record(self, datalake: str, path_id: str) -> dict[str, Any]:
        self.datalake_service.resolve_lake(datalake)
        path_id = str(path_id).strip()
        if not path_id:
            raise ValueError("path_id must not be empty")

        artifact = _read_object(self.config.preprocessed_dir / datalake / JOIN_PATHS_ARTIFACT)
        for path in artifact.get("paths", []):
            if path.get("path_id") == path_id:
                return path
        raise JoinPathNotFound(f"Unknown join path {path_id!r} for data lake {datalake!r}")

    def _load_path_tables(self, datalake: str, path: dict[str, Any]) -> dict[str, pd.DataFrame]:
        lake_path = self.datalake_service.resolve_lake(datalake)
        tables: dict[str, pd.DataFrame] = {}
        for table_name in path.get("tables_list", []):
            csv_path = lake_path / f"{table_name}.csv"
            if not csv_path.exists():
                raise FileNotFoundError(f"Missing source table CSV: {csv_path}")
            tables[table_name] = pd.read_csv(csv_path, dtype=str, keep_default_na=False)
        return tables


class JoinPathNotFound(ValueError):
    pass


def build_materialization_service(config: BackendConfig, datalake_service: DataLakeService) -> MaterializationService:
    return MaterializationService(config=config, datalake_service=datalake_service)


def _path_payload(path: dict[str, Any], aliases: dict[str, str]) -> dict[str, Any]:
    return {
        "path_id": path["path_id"],
        "tables": path.get("tables", " -> ".join(path.get("tables_list", []))),
        "tables_list": path.get("tables_list", []),
        "ordered_tables": path.get("tables_list", []),
        "join_edges": path.get("join_edges", []),
        "join_order": path.get("join_order", []),
        "attributes": path.get("attributes", []),
        "hop_count": int(path.get("hop_count", max(0, len(path.get("tables_list", [])) - 1))),
        "length": int(path.get("length", len(path.get("tables_list", [])))),
        "score": float(path.get("score", 0.0)),
        "row_count_estimate": int(path.get("row_count_estimate", path.get("cardinality_estimate", 0))),
        "cardinality_estimate": int(path.get("cardinality_estimate", path.get("row_count_estimate", 0))),
        "aliases": aliases,
    }


def _aliases_for(tables_list: list[str]) -> dict[str, str]:
    return {table: f"t{idx}" for idx, table in enumerate(tables_list, start=1)}


def _prefixed_columns(tables_list: list[str], tables: dict[str, pd.DataFrame]) -> list[str]:
    return [f"{table}.{column}" for table in tables_list for column in tables[table].columns]


def _sql_for_path(
    path: dict[str, Any],
    tables: dict[str, pd.DataFrame],
    aliases: dict[str, str],
) -> str:
    tables_list = path.get("tables_list", [])
    if not tables_list:
        raise ValueError("join path has no tables")

    select_lines = []
    for table in tables_list:
        alias = aliases[table]
        for column in tables[table].columns:
            select_lines.append(f"  {alias}.{_quote_identifier(column)} AS {_quote_identifier(f'{table}.{column}')}")

    lines = ["SELECT", ",\n".join(select_lines), f"FROM {_quote_identifier(tables_list[0])} AS {aliases[tables_list[0]]}"]
    for join in path.get("join_order", []):
        parent = join["parent"]
        child = join["child"]
        parent_column = join["parent_column"]
        child_column = join["child_column"]
        lines.append(
            "JOIN "
            f"{_quote_identifier(child)} AS {aliases[child]} "
            "ON "
            f"{aliases[parent]}.{_quote_identifier(parent_column)} = {aliases[child]}.{_quote_identifier(child_column)}"
        )
    return f"{chr(10).join(lines)};"


def _materialized_frame(path: dict[str, Any], tables: dict[str, pd.DataFrame]) -> pd.DataFrame:
    tables_list = path.get("tables_list", [])
    if not tables_list:
        raise ValueError("join path has no tables")

    joined = _prefixed_frame(tables[tables_list[0]], tables_list[0])
    for join in path.get("join_order", []):
        parent = join["parent"]
        child = join["child"]
        parent_column = join["parent_column"]
        child_column = join["child_column"]
        right = _prefixed_frame(tables[child], child)
        joined = joined.merge(
            right,
            how="inner",
            left_on=f"{parent}.{parent_column}",
            right_on=f"{child}.{child_column}",
        )
        if joined.empty:
            break
    return joined


def _prefixed_frame(frame: pd.DataFrame, table_name: str) -> pd.DataFrame:
    return frame.rename(columns={column: f"{table_name}.{column}" for column in frame.columns})


def _quote_identifier(identifier: str) -> str:
    return f'"{str(identifier).replace(chr(34), chr(34) + chr(34))}"'


def _read_object(path: Path) -> dict[str, Any]:
    if not path.exists():
        raise FileNotFoundError(f"Missing preprocessing artifact: {path}")
    payload = read_json(path)
    if not isinstance(payload, dict):
        raise ValueError(f"Expected JSON object at {path}")
    return payload
