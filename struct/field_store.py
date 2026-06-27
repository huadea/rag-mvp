"""
SQLite 字段库：建表、写入、读取。
每次 build_index 前会清空当前文档的所有记录，重新写入。
"""

import sqlite3
from pathlib import Path

DB_PATH = Path(__file__).parent / "fields.db"

_CREATE_TABLE = """
CREATE TABLE IF NOT EXISTS fields (
    id                INTEGER PRIMARY KEY AUTOINCREMENT,
    doc_path          TEXT NOT NULL,
    field_name        TEXT NOT NULL,
    field_value       TEXT,
    source_section    TEXT,
    source_text       TEXT,
    confidence        TEXT,
    human_confirmed   INTEGER DEFAULT 0,
    extraction_method TEXT,
    group_name        TEXT
)
"""


def _connect() -> sqlite3.Connection:
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    conn.execute(_CREATE_TABLE)
    conn.commit()
    return conn


def clear(doc_path: str) -> None:
    with _connect() as conn:
        conn.execute("DELETE FROM fields WHERE doc_path = ?", (doc_path,))


def save(doc_path: str, records: list[dict]) -> None:
    with _connect() as conn:
        conn.executemany(
            """
            INSERT INTO fields
                (doc_path, field_name, field_value, source_section,
                 source_text, confidence, human_confirmed, extraction_method, group_name)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            [
                (
                    doc_path,
                    r["field_name"],
                    r.get("field_value"),
                    r.get("source_section"),
                    r.get("source_text"),
                    r.get("confidence", "低"),
                    0,
                    r.get("extraction_method", "rule"),
                    r.get("group_name", ""),
                )
                for r in records
            ],
        )


def get_by_names(doc_path: str, field_names: list[str]) -> list[dict]:
    if not field_names:
        return []
    placeholders = ",".join("?" * len(field_names))
    with _connect() as conn:
        rows = conn.execute(
            f"SELECT * FROM fields WHERE doc_path = ? AND field_name IN ({placeholders})",
            [doc_path] + list(field_names),
        ).fetchall()
    return [dict(r) for r in rows]


def get_all(doc_path: str) -> list[dict]:
    with _connect() as conn:
        rows = conn.execute(
            "SELECT * FROM fields WHERE doc_path = ?", (doc_path,)
        ).fetchall()
    return [dict(r) for r in rows]
