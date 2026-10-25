"""Small SQLite repository for persisted pathway results."""

from __future__ import annotations

import json
import sqlite3
from pathlib import Path
from typing import Any


class PathwayRepository:
    """Persist pathway JSON and generation metadata in a local SQLite database."""

    def __init__(self, database_path: str | Path) -> None:
        self.database_path = Path(database_path)
        if str(database_path) != ":memory:":
            self.database_path.parent.mkdir(parents=True, exist_ok=True)
        self._initialize()

    def _connect(self) -> sqlite3.Connection:
        return sqlite3.connect(str(self.database_path))

    def _initialize(self) -> None:
        with self._connect() as connection:
            connection.execute(
                """CREATE TABLE IF NOT EXISTS pathways (
                    id TEXT PRIMARY KEY,
                    pathway_json TEXT NOT NULL,
                    metadata_json TEXT NOT NULL,
                    created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP
                )"""
            )

    def save(self, pathway_id: str, pathway: dict[str, Any], metadata: dict[str, Any]) -> None:
        """Insert or replace a pathway with its provenance metadata."""
        with self._connect() as connection:
            connection.execute(
                """INSERT OR REPLACE INTO pathways(id, pathway_json, metadata_json)
                   VALUES (?, ?, ?)""",
                (
                    pathway_id,
                    json.dumps(pathway, separators=(",", ":")),
                    json.dumps(metadata, separators=(",", ":")),
                ),
            )

    def get(self, pathway_id: str) -> dict[str, Any] | None:
        """Read one pathway record, returning None when its ID does not exist."""
        with self._connect() as connection:
            row = connection.execute(
                "SELECT pathway_json, metadata_json FROM pathways WHERE id = ?",
                (pathway_id,),
            ).fetchone()
        if row is None:
            return None
        return {"pathway": json.loads(row[0]), "metadata": json.loads(row[1])}

    def is_healthy(self) -> bool:
        """Check whether SQLite can execute a lightweight read query."""
        try:
            with self._connect() as connection:
                connection.execute("SELECT 1").fetchone()
        except sqlite3.Error:
            return False
        return True
