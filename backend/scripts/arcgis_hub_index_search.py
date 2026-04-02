#!/usr/bin/env python3
"""Index and search ArcGIS Hub ZIP datasets.

Examples:
  uv run --project backend python backend/scripts/arcgis_hub_index_search.py load
  uv run --project backend python backend/scripts/arcgis_hub_index_search.py search --query "oil field"
"""

from __future__ import annotations

import argparse
import csv
import io
import json
import sqlite3
import textwrap
import zipfile
from datetime import datetime, timezone
from pathlib import Path
from typing import Iterable

DEFAULT_DATA_DIR = Path("data/ArcGIS_Hub")
DEFAULT_DB = Path("backend/output/arcgis_hub_index.sqlite")


def utc_now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


def ensure_schema(conn: sqlite3.Connection) -> None:
    conn.executescript(
        """
        PRAGMA journal_mode = WAL;

        CREATE TABLE IF NOT EXISTS sources (
          id INTEGER PRIMARY KEY AUTOINCREMENT,
          zip_path TEXT NOT NULL UNIQUE,
          indexed_at_utc TEXT NOT NULL
        );

        CREATE TABLE IF NOT EXISTS records (
          id INTEGER PRIMARY KEY AUTOINCREMENT,
          source_id INTEGER NOT NULL,
          record_type TEXT NOT NULL,
          dataset TEXT,
          entry_path TEXT,
          row_json TEXT,
          text_content TEXT NOT NULL,
          FOREIGN KEY (source_id) REFERENCES sources(id)
        );
        """
    )

    # FTS5 is optional depending on SQLite build.
    try:
        conn.executescript(
            """
            CREATE VIRTUAL TABLE IF NOT EXISTS records_fts USING fts5(
              text_content,
              dataset,
              content='records',
              content_rowid='id'
            );

            CREATE TRIGGER IF NOT EXISTS records_ai AFTER INSERT ON records BEGIN
              INSERT INTO records_fts(rowid, text_content, dataset)
              VALUES (new.id, new.text_content, coalesce(new.dataset, ''));
            END;

            CREATE TRIGGER IF NOT EXISTS records_ad AFTER DELETE ON records BEGIN
              INSERT INTO records_fts(records_fts, rowid, text_content, dataset)
              VALUES ('delete', old.id, old.text_content, coalesce(old.dataset, ''));
            END;

            CREATE TRIGGER IF NOT EXISTS records_au AFTER UPDATE ON records BEGIN
              INSERT INTO records_fts(records_fts, rowid, text_content, dataset)
              VALUES ('delete', old.id, old.text_content, coalesce(old.dataset, ''));
              INSERT INTO records_fts(rowid, text_content, dataset)
              VALUES (new.id, new.text_content, coalesce(new.dataset, ''));
            END;
            """
        )
    except sqlite3.OperationalError:
        pass


def has_fts(conn: sqlite3.Connection) -> bool:
    row = conn.execute(
        "SELECT 1 FROM sqlite_master WHERE type='table' AND name='records_fts' LIMIT 1"
    ).fetchone()
    return bool(row)


def infer_dataset_name(entry_path: str) -> str:
    name = Path(entry_path).name
    stem = Path(name).stem
    return stem


def insert_record(
    conn: sqlite3.Connection,
    source_id: int,
    record_type: str,
    dataset: str | None,
    entry_path: str,
    row_json: dict | None,
    text_content: str,
) -> None:
    conn.execute(
        """
        INSERT INTO records (source_id, record_type, dataset, entry_path, row_json, text_content)
        VALUES (?, ?, ?, ?, ?, ?)
        """,
        (
            source_id,
            record_type,
            dataset,
            entry_path,
            json.dumps(row_json, ensure_ascii=False) if row_json is not None else None,
            text_content,
        ),
    )


def read_text_stream(raw: bytes) -> str:
    for enc in ("utf-8", "latin-1"):
        try:
            return raw.decode(enc)
        except UnicodeDecodeError:
            continue
    return raw.decode("utf-8", errors="replace")


def iter_zip_paths(data_dir: Path) -> Iterable[Path]:
    if not data_dir.exists() or not data_dir.is_dir():
        return []
    return sorted(p for p in data_dir.glob("*.zip") if p.is_file())


def index_zip(conn: sqlite3.Connection, zip_path: Path) -> None:
    zip_abs = str(zip_path.resolve())
    conn.execute(
        "INSERT OR REPLACE INTO sources(zip_path, indexed_at_utc) VALUES (?, ?)",
        (zip_abs, utc_now_iso()),
    )
    source_id = conn.execute("SELECT id FROM sources WHERE zip_path = ?", (zip_abs,)).fetchone()[0]

    conn.execute("DELETE FROM records WHERE source_id = ?", (source_id,))

    with zipfile.ZipFile(zip_path, "r") as zf:
        names = zf.namelist()

        # Index every file path for broad discovery.
        for entry in names:
            if entry.endswith("/"):
                continue
            dataset = infer_dataset_name(entry)
            insert_record(
                conn,
                source_id=source_id,
                record_type="file",
                dataset=dataset,
                entry_path=entry,
                row_json=None,
                text_content=f"{dataset} {entry}",
            )

        # Index shapefile layer names.
        for entry in names:
            if entry.lower().endswith(".shp"):
                dataset = infer_dataset_name(entry)
                insert_record(
                    conn,
                    source_id=source_id,
                    record_type="layer",
                    dataset=dataset,
                    entry_path=entry,
                    row_json=None,
                    text_content=f"layer {dataset} {entry}",
                )

        # Index CSV rows (best source for searchable content).
        for entry in names:
            if not entry.lower().endswith(".csv"):
                continue

            dataset = infer_dataset_name(entry)
            with zf.open(entry, "r") as f:
                text = read_text_stream(f.read())

            reader = csv.DictReader(io.StringIO(text))
            for row in reader:
                row = {k: (v or "").strip() for k, v in row.items() if k is not None}
                values = [v for v in row.values() if v]
                if not values:
                    continue
                content = f"{dataset} {' '.join(values)}"
                insert_record(
                    conn,
                    source_id=source_id,
                    record_type="csv_row",
                    dataset=dataset,
                    entry_path=entry,
                    row_json=row,
                    text_content=content,
                )


def cmd_load(args: argparse.Namespace) -> int:
    data_dir = Path(args.data_dir).expanduser().resolve()
    db_path = Path(args.db).expanduser().resolve()
    db_path.parent.mkdir(parents=True, exist_ok=True)

    conn = sqlite3.connect(db_path)
    try:
      ensure_schema(conn)
      zip_paths = list(iter_zip_paths(data_dir))
      if not zip_paths:
          print(f"No .zip files found in {data_dir}")
          return 1

      for zp in zip_paths:
          print(f"Indexing {zp.name} ...")
          index_zip(conn, zp)
          conn.commit()

      total = conn.execute("SELECT COUNT(*) FROM records").fetchone()[0]
      print(f"Index complete. Records: {total}. DB: {db_path}")
      return 0
    finally:
      conn.close()


def cmd_search(args: argparse.Namespace) -> int:
    db_path = Path(args.db).expanduser().resolve()
    if not db_path.exists():
        print(f"Index DB not found: {db_path}. Run `load` first.")
        return 1

    conn = sqlite3.connect(db_path)
    conn.row_factory = sqlite3.Row
    try:
      query = args.query.strip()
      if not query:
          print("--query is required")
          return 1

      def search_like() -> list[sqlite3.Row]:
          like_q = f"%{query}%"
          sql = textwrap.dedent(
              """
              SELECT
                r.record_type,
                r.dataset,
                r.entry_path,
                r.row_json,
                substr(r.text_content, 1, 240) AS snippet,
                s.zip_path
              FROM records r
              JOIN sources s ON s.id = r.source_id
              WHERE r.text_content LIKE ?
              ORDER BY r.id DESC
              LIMIT ?
              """
          )
          return conn.execute(sql, (like_q, args.limit)).fetchall()

      rows: list[sqlite3.Row] = []
      if has_fts(conn):
          try:
              sql = textwrap.dedent(
                  """
                  SELECT
                    r.record_type,
                    r.dataset,
                    r.entry_path,
                    r.row_json,
                    snippet(records_fts, 0, '[', ']', ' ... ', 16) AS snippet,
                    s.zip_path
                  FROM records_fts
                  JOIN records r ON r.id = records_fts.rowid
                  JOIN sources s ON s.id = r.source_id
                  WHERE records_fts MATCH ?
                  ORDER BY bm25(records_fts)
                  LIMIT ?
                  """
              )
              rows = conn.execute(sql, (query, args.limit)).fetchall()
          except sqlite3.OperationalError:
              rows = []

      if not rows:
          rows = search_like()

      if not rows:
          print(f"No results for: {query}")
          return 0

      for i, row in enumerate(rows, start=1):
          print(f"\n[{i}] {row['record_type']} | dataset={row['dataset']} | zip={Path(row['zip_path']).name}")
          print(f"    entry: {row['entry_path']}")
          print(f"    match: {row['snippet']}")
          if args.show_json and row["row_json"]:
              print(f"    row_json: {row['row_json']}")

      return 0
    finally:
      conn.close()


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Load and search ArcGIS Hub ZIP datasets.")
    parser.add_argument("--db", default=str(DEFAULT_DB), help=f"SQLite index path (default: {DEFAULT_DB})")

    sub = parser.add_subparsers(dest="command", required=True)

    p_load = sub.add_parser("load", help="Load/index ZIP files from ArcGIS_Hub directory")
    p_load.add_argument("--db", default=str(DEFAULT_DB), help=f"SQLite index path (default: {DEFAULT_DB})")
    p_load.add_argument("--data-dir", default=str(DEFAULT_DATA_DIR), help=f"Directory with .zip files (default: {DEFAULT_DATA_DIR})")
    p_load.set_defaults(func=cmd_load)

    p_search = sub.add_parser("search", help="Search indexed records")
    p_search.add_argument("--db", default=str(DEFAULT_DB), help=f"SQLite index path (default: {DEFAULT_DB})")
    p_search.add_argument("--query", required=True, help="FTS query")
    p_search.add_argument("--limit", type=int, default=25, help="Max results")
    p_search.add_argument("--show-json", action="store_true", help="Print row_json payload for csv_row matches")
    p_search.set_defaults(func=cmd_search)

    return parser


def main() -> int:
    parser = build_parser()
    args = parser.parse_args()
    return args.func(args)


if __name__ == "__main__":
    raise SystemExit(main())
