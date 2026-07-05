"""Import a Render SQLite backup into Turso/libSQL.

Usage:
    python scripts/import_sqlite_to_libsql.py path/to/planning.db

Required environment:
    TURSO_DATABASE_URL or LIBSQL_URL
    TURSO_AUTH_TOKEN or LIBSQL_AUTH_TOKEN
"""

import os
import sqlite3
import sys
from pathlib import Path

from libsql_client import create_client_sync

ROOT_DIR = Path(__file__).resolve().parents[1]
if str(ROOT_DIR) not in sys.path:
    sys.path.insert(0, str(ROOT_DIR))

from db import init_db, libsql_auth_token, libsql_url


TABLES = [
    "tasks",
    "sisters",
    "absences",
    "fixed_assignments",
    "plans",
    "plan_items",
    "eligibility",
]


def quote_identifier(name):
    return '"' + name.replace('"', '""') + '"'


def main():
    if len(sys.argv) != 2:
        raise SystemExit("Usage: python scripts/import_sqlite_to_libsql.py path/to/planning.db")

    sqlite_path = Path(sys.argv[1])
    if not sqlite_path.exists():
        raise SystemExit(f"SQLite file not found: {sqlite_path}")

    url = libsql_url()
    token = libsql_auth_token()
    if not url:
        raise SystemExit("Set TURSO_DATABASE_URL or LIBSQL_URL before importing")

    init_db()

    source = sqlite3.connect(f"file:{sqlite_path}?mode=ro", uri=True)
    source.row_factory = sqlite3.Row

    kwargs = {"auth_token": token} if token else {}
    target = create_client_sync(url, **kwargs)
    tx = target.transaction()

    try:
        for table in reversed(TABLES):
            tx.execute(f"DELETE FROM {quote_identifier(table)}")

        for table in TABLES:
            columns = [
                row["name"]
                for row in source.execute(f"PRAGMA table_info({quote_identifier(table)})").fetchall()
            ]
            if not columns:
                continue

            quoted_columns = ", ".join(quote_identifier(column) for column in columns)
            placeholders = ", ".join("?" for _ in columns)
            insert_sql = (
                f"INSERT INTO {quote_identifier(table)} "
                f"({quoted_columns}) VALUES ({placeholders})"
            )

            rows = source.execute(f"SELECT {quoted_columns} FROM {quote_identifier(table)}").fetchall()
            for row in rows:
                tx.execute(insert_sql, tuple(row[column] for column in columns))

            print(f"imported {len(rows)} rows into {table}", flush=True)

        tx.commit()
    except Exception:
        tx.rollback()
        raise
    finally:
        source.close()
        target.close()


if __name__ == "__main__":
    main()
