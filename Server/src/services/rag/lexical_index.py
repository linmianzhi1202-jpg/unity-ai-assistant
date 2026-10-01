"""Dependency-free lexical retrieval shared by the Unity and game-code RAGs.

SQLite FTS5 supplies an inverted index and BM25 scoring. C# identifiers and
Chinese text are expanded before indexing because unicode61 does not split
camelCase or Chinese phrases by itself.
"""
from __future__ import annotations

import json
import logging
import re
import sqlite3
import threading
from pathlib import Path
from typing import Any, Iterable, Mapping

logger = logging.getLogger(__name__)
_CAMEL_RE = re.compile(r"(?<=[a-z0-9])(?=[A-Z])|(?<=[A-Z])(?=[A-Z][a-z])")
_TOKEN_RE = re.compile(r"[a-z0-9_]+")
_CJK_RE = re.compile(r"[\u4e00-\u9fff]+")


def _identifier_terms(value: str) -> list[str]:
    output: list[str] = []
    for part in re.split(r"[^A-Za-z0-9\u4e00-\u9fff]+", str(value or "")):
        if not part:
            continue
        split = _CAMEL_RE.sub(" ", part) if re.search(r"[A-Z]", part) else part
        for item in split.split():
            item = item.lower()
            if item:
                output.extend((item, part.lower()) if item != part.lower() else (item,))
    return output


def _cjk_terms(value: str) -> list[str]:
    output: list[str] = []
    for run in _CJK_RE.findall(str(value or "")):
        output.append(run)
        output.extend(run[i:i + 2] for i in range(len(run) - 1))
    return output


def searchable_text(document: str, metadata: Mapping[str, Any] | None = None) -> str:
    """Expand identifiers/CJK and return safe whitespace-separated FTS tokens."""
    metadata = metadata or {}
    fields = [metadata.get(k, "") for k in (
        "class_name", "method_name", "namespace", "full_name", "file_path",
        "source_path", "type", "code_type", "game_name",
    )]
    values = [*map(str, fields), str(document or "")]
    terms: list[str] = []
    for value in values:
        terms.extend(_identifier_terms(value))
        terms.extend(_cjk_terms(value))
        terms.extend(_TOKEN_RE.findall(value.lower()))
    return " ".join(term for term in terms if term)


def query_terms(query: str) -> list[str]:
    terms: list[str] = []
    for value in re.findall(r"[A-Za-z0-9_.$]+|[\u4e00-\u9fff]+", str(query or "")):
        terms.extend(_identifier_terms(value))
        terms.extend(_cjk_terms(value))
        terms.extend(_TOKEN_RE.findall(value.lower()))
    stop = {"unity", "script", "code", "class", "method", "如何", "怎么", "实现", "一个", "相关"}
    return list(dict.fromkeys(term for term in terms if term not in stop))


def _match_query(query: str) -> str:
    return " OR ".join('"' + term.replace('"', '""') + '"' for term in query_terms(query))


class SQLiteLexicalIndex:
    """FTS5 index with atomic document upserts and simple metadata filters."""

    def __init__(self, path: str | Path):
        self.path = Path(path)
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self._lock = threading.RLock()
        self._conn = sqlite3.connect(str(self.path), check_same_thread=False)
        self._conn.row_factory = sqlite3.Row
        self._configure()

    def _configure(self) -> None:
        with self._conn:
            self._conn.execute("PRAGMA journal_mode=WAL")
            self._conn.execute("""
                CREATE TABLE IF NOT EXISTS lexical_documents (
                    id TEXT PRIMARY KEY,
                    document TEXT NOT NULL,
                    metadata_json TEXT NOT NULL,
                    game_name TEXT, class_name TEXT, method_name TEXT,
                    type TEXT, code_type TEXT
                )
            """)
            self._conn.execute("""
                CREATE VIRTUAL TABLE IF NOT EXISTS lexical_fts USING fts5(
                    id UNINDEXED, identifier, body,
                    tokenize='unicode61 remove_diacritics 2'
                )
            """)

    def close(self) -> None:
        with self._lock:
            self._conn.close()

    def count(self) -> int:
        with self._lock:
            return int(self._conn.execute("SELECT COUNT(*) FROM lexical_documents").fetchone()[0])

    def _upsert_docs_locked(self, rows: list[Mapping[str, Any]]) -> None:
        for row in rows:
            metadata = dict(row.get("metadata") or {})
            doc_id = str(row.get("id", ""))
            document = str(row.get("document", "") or "")
            identifier = " ".join(str(metadata.get(k, "") or "") for k in (
                "class_name", "method_name", "namespace", "full_name", "file_path", "source_path",
            ))
            self._conn.execute("""
                INSERT INTO lexical_documents
                (id, document, metadata_json, game_name, class_name, method_name, type, code_type)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?)
                ON CONFLICT(id) DO UPDATE SET
                  document=excluded.document, metadata_json=excluded.metadata_json,
                  game_name=excluded.game_name, class_name=excluded.class_name,
                  method_name=excluded.method_name, type=excluded.type,
                  code_type=excluded.code_type
            """, (doc_id, document, json.dumps(metadata, ensure_ascii=False),
                  str(metadata.get("game_name", "") or ""), str(metadata.get("class_name", "") or ""),
                  str(metadata.get("method_name", "") or ""), str(metadata.get("type", "") or ""),
                  str(metadata.get("code_type", "") or "")))

    def _rebuild_fts_locked(self) -> None:
        self._conn.execute("DELETE FROM lexical_fts")
        rows = self._conn.execute("SELECT id, document, metadata_json FROM lexical_documents").fetchall()
        self._conn.executemany(
            "INSERT INTO lexical_fts(id, identifier, body) VALUES (?, ?, ?)",
            ((row["id"], searchable_text("", json.loads(row["metadata_json"] or "{}")),
              searchable_text(row["document"], {})) for row in rows),
        )

    def replace_all(self, rows: Iterable[Mapping[str, Any]]) -> int:
        rows = list(rows)
        with self._lock, self._conn:
            self._conn.execute("DELETE FROM lexical_documents")
            self._upsert_docs_locked(rows)
            self._rebuild_fts_locked()
        return len(rows)

    def upsert(self, rows: Iterable[Mapping[str, Any]]) -> int:
        rows = list(rows)
        if not rows:
            return 0
        with self._lock, self._conn:
            self._upsert_docs_locked(rows)
            for row in rows:
                doc_id = str(row.get("id", ""))
                metadata = dict(row.get("metadata") or {})
                self._conn.execute("DELETE FROM lexical_fts WHERE id = ?", (doc_id,))
                self._conn.execute(
                    "INSERT INTO lexical_fts(id, identifier, body) VALUES (?, ?, ?)",
                    (doc_id, searchable_text("", metadata), searchable_text(str(row.get("document", "") or ""), {})),
                )
        return len(rows)

    def search(self, query: str, limit: int = 20, filters: Mapping[str, Any] | None = None) -> list[dict[str, Any]]:
        match = _match_query(query)
        if not match:
            return []
        clauses = ["lexical_fts MATCH ?"]
        args: list[Any] = [match]
        normalized_filters = dict(filters or {})
        if "$and" in normalized_filters:
            for clause in normalized_filters.get("$and") or []:
                if isinstance(clause, dict):
                    normalized_filters.update(clause)
        for key in ("game_name", "class_name", "method_name", "type", "code_type"):
            value = normalized_filters.get(key)
            if isinstance(value, dict) and "$in" in value:
                value = value.get("$in")
            if isinstance(value, str) and value:
                clauses.append(f"d.{key} = ?")
                args.append(value)
            elif isinstance(value, (list, tuple, set)) and value:
                placeholders = ",".join("?" for _ in value)
                clauses.append(f"d.{key} IN ({placeholders})")
                args.extend(value)
        sql = f"""
            SELECT lexical_fts.id, d.document, d.metadata_json,
                   bm25(lexical_fts, 8.0, 3.0) AS rank
            FROM lexical_fts JOIN lexical_documents d ON d.id = lexical_fts.id
            WHERE {' AND '.join(clauses)}
            ORDER BY rank ASC LIMIT ?
        """
        args.append(max(1, int(limit or 20)))
        with self._lock:
            rows = self._conn.execute(sql, args).fetchall()
        if not rows:
            return []
        ranks = [float(row["rank"]) for row in rows]
        best, worst = min(ranks), max(ranks)
        span = max(worst - best, 1e-9)
        return [{
            "id": row["id"], "document": row["document"],
            "metadata": json.loads(row["metadata_json"] or "{}"),
            "bm25": float(row["rank"]),
            "score": 1.0 - (float(row["rank"]) - best) / span if span > 1e-9 else 1.0,
        } for row in rows]
