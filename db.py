# db.py
import os
import sqlite3
from pathlib import Path

if os.getenv("RENDER"):
    DB_PATH = Path("/var/data/planning.db")
else:
    DB_PATH = Path(__file__).with_name("planning.db")


def get_conn():
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    return conn


def column_exists(conn, table_name, column_name):
    rows = conn.execute(f"PRAGMA table_info({table_name})").fetchall()
    return any(r["name"] == column_name for r in rows)


def ensure_column(conn, table_name, column_name, ddl):
    if not column_exists(conn, table_name, column_name):
        conn.execute(f"ALTER TABLE {table_name} ADD COLUMN {column_name} {ddl}")


def init_db():
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
      id      INTEGER PRIMARY KEY AUTOINCREMENT,
      name    TEXT NOT NULL,
      active  INTEGER NOT NULL DEFAULT 1,
      restr   TEXT NOT NULL DEFAULT '—'
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

    conn.commit()
    conn.close()