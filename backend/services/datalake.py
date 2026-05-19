from __future__ import annotations

import csv
from collections import Counter
import hashlib
import re
from dataclasses import dataclass
from pathlib import Path
from typing import Any


class DataLakeError(Exception):
    status_code = 400
    code = "datalake_error"


class InvalidDataLakeName(DataLakeError):
    code = "invalid_datalake"


class DataLakeNotFound(DataLakeError):
    status_code = 404
    code = "datalake_not_found"


_SAFE_LAKE_NAME = re.compile(r"^[A-Za-z0-9_-]+$")


@dataclass(frozen=True)
class DataLakeService:
    datalake_dir: Path

    def list_lakes(self) -> list[str]:
        if not self.datalake_dir.exists():
            return []

        lakes = []
        for child in self.datalake_dir.iterdir():
            if child.is_dir() and not child.name.startswith("."):
                lakes.append(child.name)
        return sorted(lakes)

    def summary(self, name: str, sample_limit: int = 5) -> dict[str, Any]:
        lake_path = self.resolve_lake(name)
        tables = [self._table_summary(csv_path, sample_limit) for csv_path in sorted(lake_path.glob("*.csv"))]

        return {
            "name": name,
            "table_count": len(tables),
            "total_rows": sum(table["row_count"] for table in tables),
            "tables": tables,
        }

    def table_profiles(self, name: str, sample_limit: int = 5, value_limit: int = 8) -> list[dict[str, Any]]:
        lake_path = self.resolve_lake(name)
        return [self._table_profile(csv_path, sample_limit, value_limit) for csv_path in sorted(lake_path.glob("*.csv"))]

    def resolve_lake(self, name: str) -> Path:
        if not name or not _SAFE_LAKE_NAME.fullmatch(name):
            raise InvalidDataLakeName(f"Invalid data lake name: {name!r}")

        lake_path = (self.datalake_dir / name).resolve()
        try:
            lake_path.relative_to(self.datalake_dir.resolve())
        except ValueError as exc:
            raise InvalidDataLakeName(f"Invalid data lake name: {name!r}") from exc

        if not lake_path.is_dir():
            raise DataLakeNotFound(f"Unknown data lake: {name}")

        return lake_path

    def _table_summary(self, csv_path: Path, sample_limit: int) -> dict[str, Any]:
        columns: list[str] = []
        sample_rows: list[dict[str, str]] = []
        row_count = 0

        with csv_path.open("r", encoding="utf-8-sig", newline="") as handle:
            reader = csv.DictReader(handle)
            columns = list(reader.fieldnames or [])
            for row in reader:
                row_count += 1
                if len(sample_rows) < sample_limit:
                    sample_rows.append({column: row.get(column, "") for column in columns})

        return {
            "name": csv_path.stem,
            "file_name": csv_path.name,
            "columns": columns,
            "row_count": row_count,
            "sample_rows": sample_rows,
            "file_hash": sha256_file(csv_path),
        }

    def _table_profile(self, csv_path: Path, sample_limit: int, value_limit: int) -> dict[str, Any]:
        columns: list[str] = []
        sample_rows: list[dict[str, str]] = []
        counters: dict[str, Counter[str]] = {}
        row_count = 0

        with csv_path.open("r", encoding="utf-8-sig", newline="") as handle:
            reader = csv.DictReader(handle)
            columns = list(reader.fieldnames or [])
            counters = {column: Counter() for column in columns}
            for row in reader:
                row_count += 1
                if len(sample_rows) < sample_limit:
                    sample_rows.append({column: row.get(column, "") for column in columns})
                for column in columns:
                    value = str(row.get(column, "")).strip()
                    if value:
                        counters[column][value] += 1

        top_values = {
            column: [value for value, _count in counters[column].most_common(value_limit)]
            for column in columns
        }

        return {
            "name": csv_path.stem,
            "file_name": csv_path.name,
            "columns": columns,
            "row_count": row_count,
            "sample_rows": sample_rows,
            "top_values": top_values,
            "file_hash": sha256_file(csv_path),
        }


def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()
