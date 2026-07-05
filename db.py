# db.py
import os
import sqlite3
from pathlib import Path


def libsql_url():
    raw_url = os.getenv("TURSO_DATABASE_URL") or os.getenv("LIBSQL_URL")
    if raw_url and raw_url.startswith("libsql://"):
        return "https://" + raw_url[len("libsql://"):]
    return raw_url


def libsql_auth_token():
    return os.getenv("TURSO_AUTH_TOKEN") or os.getenv("LIBSQL_AUTH_TOKEN")


def use_libsql():
    return bool(libsql_url())


def log_libsql_environment():
    print(
        "[planning-soeurs] libSQL config: "
        f"TURSO_DATABASE_URL_present={bool(os.getenv('TURSO_DATABASE_URL'))} "
        f"LIBSQL_URL_present={bool(os.getenv('LIBSQL_URL'))} "
        f"TURSO_AUTH_TOKEN_present={bool(os.getenv('TURSO_AUTH_TOKEN'))} "
        f"LIBSQL_AUTH_TOKEN_present={bool(os.getenv('LIBSQL_AUTH_TOKEN'))}",
        flush=True,
    )


def get_database_path() -> Path:
    configured_path = os.getenv("DATABASE_PATH") or os.getenv("PLANNING_DB_PATH")
    if configured_path:
        return Path(configured_path)

    if os.getenv("RENDER"):
        return Path("/var/data/planning.db")

    if os.getenv("VERCEL"):
        raise RuntimeError(
            "Vercel requires a persistent database. Set TURSO_DATABASE_URL "
            "and TURSO_AUTH_TOKEN instead of using temporary SQLite storage."
        )

    return Path(__file__).with_name("planning.db")


DB_PATH = None if use_libsql() else get_database_path()


class LibsqlRow(dict):
    pass


class LibsqlCursor:
    def __init__(self, result):
        self.lastrowid = result.last_insert_rowid
        self.rowcount = result.rows_affected
        self._rows = [
            LibsqlRow(zip(result.columns, row))
            for row in result.rows
        ]

    def fetchall(self):
        return self._rows

    def fetchone(self):
        return self._rows[0] if self._rows else None


class LibsqlConnection:
    def __init__(self):
        from libsql_client import create_client_sync

        kwargs = {}
        token = libsql_auth_token()
        if token:
            kwargs["auth_token"] = token

        self._client = create_client_sync(libsql_url(), **kwargs)
        self._tx = self._client.transaction()
        self._closed = False
        self._completed = False

    def execute(self, sql, params=None):
        params = tuple(params or ())
        result = self._tx.execute(sql, params)
        return LibsqlCursor(result)

    def executescript(self, script):
        for statement in split_sql_script(script):
            self.execute(statement)

    def commit(self):
        if not self._completed:
            self._tx.commit()
            self._completed = True

    def rollback(self):
        if not self._completed:
            self._tx.rollback()
            self._completed = True

    def close(self):
        if self._closed:
            return
        try:
            if not self._completed:
                self._tx.rollback()
                self._completed = True
        finally:
            self._client.close()
            self._closed = True


def split_sql_script(script):
    statements = []
    current = []

    for line in script.splitlines():
        current.append(line)
        candidate = "\n".join(current).strip()
        if candidate and sqlite3.complete_statement(candidate):
            statements.append(candidate)
            current = []

    tail = "\n".join(current).strip()
    if tail:
        statements.append(tail)

    return statements


def get_conn():
    if use_libsql():
        return LibsqlConnection()

    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    return conn


def column_exists(conn, table_name, column_name):
    rows = conn.execute(f"PRAGMA table_info({table_name})").fetchall()
    return any(r["name"] == column_name for r in rows)


def ensure_column(conn, table_name, column_name, ddl):
    if not column_exists(conn, table_name, column_name):
        conn.execute(f"ALTER TABLE {table_name} ADD COLUMN {column_name} {ddl}")


def table_exists(conn, table_name):
    row = conn.execute(
        "SELECT 1 FROM sqlite_master WHERE type='table' AND name=?",
        (table_name,),
    ).fetchone()
    return row is not None


def core_schema_exists(conn):
    return all(table_exists(conn, table) for table in ("sisters", "tasks", "plans"))


def init_db():
    if DB_PATH is not None:
        DB_PATH.parent.mkdir(parents=True, exist_ok=True)

    conn = get_conn()
    if use_libsql():
        log_libsql_environment()
        if core_schema_exists(conn):
            conn.commit()
            conn.close()
            return

    if not use_libsql():
        conn.execute("PRAGMA journal_mode=WAL")

    conn.executescript("""
    CREATE TABLE IF NOT EXISTS tasks (
      id                INTEGER PRIMARY KEY AUTOINCREMENT,
      name              TEXT NOT NULL,
      moment            TEXT NOT NULL,
      days              TEXT NOT NULL,
      people            INTEGER NOT NULL DEFAULT 1,
      type              TEXT NOT NULL DEFAULT 'Fixe',
      prio              INTEGER NOT NULL DEFAULT 2,
      active            INTEGER NOT NULL DEFAULT 1,
      rule              TEXT NOT NULL DEFAULT '',
      time_label        TEXT NOT NULL DEFAULT '',
      duration_minutes  INTEGER NOT NULL DEFAULT 60
    );

    CREATE TABLE IF NOT EXISTS sisters (
      id              INTEGER PRIMARY KEY AUTOINCREMENT,
      name            TEXT NOT NULL,
      active          INTEGER NOT NULL DEFAULT 1,
      restr           TEXT NOT NULL DEFAULT '—',
      repetition_days TEXT NOT NULL DEFAULT ''
    );

    CREATE TABLE IF NOT EXISTS absences (
      id        INTEGER PRIMARY KEY AUTOINCREMENT,
      sister_id INTEGER NOT NULL,
      date      TEXT NOT NULL,
      moment    TEXT NOT NULL,
      reason    TEXT NOT NULL DEFAULT 'Autre'
    );

    CREATE TABLE IF NOT EXISTS fixed_assignments (
      id        INTEGER PRIMARY KEY AUTOINCREMENT,
      sister_id INTEGER NOT NULL,
      task_id   INTEGER NOT NULL,
      days      TEXT NOT NULL,
      moment    TEXT NOT NULL,
      start     TEXT NOT NULL,
      end       TEXT NOT NULL,
      type      TEXT NOT NULL DEFAULT 'Bloquant'
    );

    CREATE TABLE IF NOT EXISTS plans (
      id         INTEGER PRIMARY KEY AUTOINCREMENT,
      week       TEXT NOT NULL UNIQUE,
      locked     INTEGER NOT NULL DEFAULT 0,
      created_at TEXT NOT NULL DEFAULT (datetime('now'))
    );

    CREATE TABLE IF NOT EXISTS plan_items (
      id         INTEGER PRIMARY KEY AUTOINCREMENT,
      plan_id    INTEGER NOT NULL,
      day        TEXT NOT NULL,
      moment     TEXT NOT NULL,
      task_id    INTEGER NOT NULL,
      sister_ids TEXT NOT NULL DEFAULT ''
    );

    CREATE TABLE IF NOT EXISTS eligibility (
      sister_id INTEGER NOT NULL,
      task_id   INTEGER NOT NULL,
      allowed   INTEGER NOT NULL DEFAULT 1,
      PRIMARY KEY (sister_id, task_id)
    );
    """)

    # migrations sûres
    ensure_column(conn, "tasks", "people", "INTEGER NOT NULL DEFAULT 1")
    ensure_column(conn, "tasks", "type", "TEXT NOT NULL DEFAULT 'Fixe'")
    ensure_column(conn, "tasks", "prio", "INTEGER NOT NULL DEFAULT 2")
    ensure_column(conn, "tasks", "active", "INTEGER NOT NULL DEFAULT 1")
    ensure_column(conn, "tasks", "rule", "TEXT NOT NULL DEFAULT ''")
    ensure_column(conn, "tasks", "time_label", "TEXT NOT NULL DEFAULT ''")
    ensure_column(conn, "tasks", "duration_minutes", "INTEGER NOT NULL DEFAULT 60")

    ensure_column(conn, "sisters", "restr", "TEXT NOT NULL DEFAULT '—'")
    ensure_column(conn, "sisters", "repetition_days", "TEXT NOT NULL DEFAULT ''")

    conn.commit()
    conn.close()
