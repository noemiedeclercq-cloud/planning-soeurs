# db.py
import os
import sqlite3
import tempfile
from pathlib import Path


def get_database_path() -> Path:
    configured_path = os.getenv("DATABASE_PATH") or os.getenv("PLANNING_DB_PATH")
    if configured_path:
        return Path(configured_path)

    if os.getenv("RENDER"):
        return Path("/var/data/planning.db")

    if os.getenv("VERCEL"):
        return Path(tempfile.gettempdir()) / "planning-soeurs" / "planning.db"

    return Path(__file__).with_name("planning.db")


DB_PATH = get_database_path()


def get_conn():
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    return conn


def _database_file_info(path: Path):
    exists = path.exists()
    if not exists:
        return {
            "exists": False,
            "size": None,
            "inode": None,
        }

    stat = path.stat()
    return {
        "exists": True,
        "size": stat.st_size,
        "inode": getattr(stat, "st_ino", None),
    }


def _read_table_count(path: Path, table_name: str):
    if not path.exists():
        return "unavailable: database file does not exist"

    try:
        conn = sqlite3.connect(f"file:{path}?mode=ro", uri=True)
        count = conn.execute(f"SELECT COUNT(*) FROM {table_name}").fetchone()[0]
        conn.close()
        return count
    except Exception as exc:
        return f"error: {exc}"


def _table_exists(path: Path, table_name: str):
    if not path.exists():
        return False

    try:
        conn = sqlite3.connect(f"file:{path}?mode=ro", uri=True)
        row = conn.execute(
            "SELECT 1 FROM sqlite_master WHERE type='table' AND name=?",
            (table_name,),
        ).fetchone()
        conn.close()
        return row is not None
    except Exception:
        return "unknown"


def log_database_diagnostics(label: str):
    path = get_database_path()
    info = _database_file_info(path)

    print(f"[planning-soeurs] SQLite runtime diagnostic: {label}", flush=True)
    print(f"[planning-soeurs] os.getcwd={os.getcwd()}", flush=True)
    print(f"[planning-soeurs] env.DATABASE_PATH={os.getenv('DATABASE_PATH')}", flush=True)
    print(f"[planning-soeurs] env.PLANNING_DB_PATH={os.getenv('PLANNING_DB_PATH')}", flush=True)
    print(f"[planning-soeurs] env.RENDER={os.getenv('RENDER')}", flush=True)
    print(f"[planning-soeurs] env.VERCEL={os.getenv('VERCEL')}", flush=True)
    print(f"[planning-soeurs] get_database_path={path}", flush=True)
    print(f"[planning-soeurs] database_exists={info['exists']}", flush=True)
    print(f"[planning-soeurs] database_size_bytes={info['size']}", flush=True)
    print(f"[planning-soeurs] database_inode={info['inode']}", flush=True)
    print(f"[planning-soeurs] table_exists.sisters={_table_exists(path, 'sisters')}", flush=True)
    print(f"[planning-soeurs] table_exists.tasks={_table_exists(path, 'tasks')}", flush=True)
    print(f"[planning-soeurs] table_exists.plans={_table_exists(path, 'plans')}", flush=True)
    print(f"[planning-soeurs] count.sisters={_read_table_count(path, 'sisters')}", flush=True)
    print(f"[planning-soeurs] count.tasks={_read_table_count(path, 'tasks')}", flush=True)
    print(f"[planning-soeurs] count.plans={_read_table_count(path, 'plans')}", flush=True)


def column_exists(conn, table_name, column_name):
    rows = conn.execute(f"PRAGMA table_info({table_name})").fetchall()
    return any(r["name"] == column_name for r in rows)


def ensure_column(conn, table_name, column_name, ddl):
    if not column_exists(conn, table_name, column_name):
        conn.execute(f"ALTER TABLE {table_name} ADD COLUMN {column_name} {ddl}")


def init_db():
    print("[planning-soeurs] init_db: starting", flush=True)
    log_database_diagnostics("before init_db")

    DB_PATH.parent.mkdir(parents=True, exist_ok=True)

    conn = get_conn()

    conn.executescript("""
    PRAGMA journal_mode=WAL;

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

    print("[planning-soeurs] init_db: finished", flush=True)
    log_database_diagnostics("after init_db")
