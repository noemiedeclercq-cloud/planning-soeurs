import os
import sqlite3
from pathlib import Path

DB_PATH = Path(os.environ.get("DB_PATH", Path(__file__).with_name("planning.db")))


def get_conn() -> sqlite3.Connection:
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    return conn


def _column_exists(conn: sqlite3.Connection, table_name: str, column_name: str) -> bool:
    rows = conn.execute(f"PRAGMA table_info({table_name})").fetchall()
    return any(r["name"] == column_name for r in rows)


def _ensure_column(conn: sqlite3.Connection, table_name: str, column_name: str, ddl: str) -> None:
    if not _column_exists(conn, table_name, column_name):
        conn.execute(f"ALTER TABLE {table_name} ADD COLUMN {column_name} {ddl}")


def init_db() -> None:
    conn = get_conn()

    conn.executescript("""
    PRAGMA journal_mode=WAL;
    PRAGMA foreign_keys=ON;

    -- ---------------- TASKS ----------------
    CREATE TABLE IF NOT EXISTS tasks (
      id      INTEGER PRIMARY KEY AUTOINCREMENT,
      name    TEXT NOT NULL,
      moment  TEXT NOT NULL,          -- AM, PM, AM+PM
      days    TEXT NOT NULL,          -- "Mon,Tue,Wed"
      people  INTEGER NOT NULL DEFAULT 1,
      type    TEXT NOT NULL DEFAULT 'Fixe',
      prio    INTEGER NOT NULL DEFAULT 2,
      active  INTEGER NOT NULL DEFAULT 1,
      rule    TEXT NOT NULL DEFAULT ''
    );

    -- ---------------- SISTERS ----------------
    CREATE TABLE IF NOT EXISTS sisters (
      id      INTEGER PRIMARY KEY AUTOINCREMENT,
      name    TEXT NOT NULL,
      active  INTEGER NOT NULL DEFAULT 1,
      restr   TEXT NOT NULL DEFAULT '—'
    );

    -- ---------------- ABSENCES ----------------
    CREATE TABLE IF NOT EXISTS absences (
      id        INTEGER PRIMARY KEY AUTOINCREMENT,
      sister_id INTEGER NOT NULL,
      date      TEXT NOT NULL,        -- YYYY-MM-DD
      moment    TEXT NOT NULL,        -- AM, PM, Journée
      reason    TEXT NOT NULL DEFAULT 'Autre',
      FOREIGN KEY(sister_id) REFERENCES sisters(id) ON DELETE CASCADE
    );

    -- ---------------- FIXED ASSIGNMENTS ----------------
    CREATE TABLE IF NOT EXISTS fixed_assignments (
      id        INTEGER PRIMARY KEY AUTOINCREMENT,
      sister_id INTEGER NOT NULL,
      task_id   INTEGER NOT NULL,
      days      TEXT NOT NULL,        -- "Tue,Thu"
      moment    TEXT NOT NULL,        -- AM, PM
      start     TEXT NOT NULL,        -- YYYY-MM-DD
      end       TEXT NOT NULL,        -- YYYY-MM-DD
      type      TEXT NOT NULL DEFAULT 'Bloquant', -- Bloquant, Préféré
      FOREIGN KEY(sister_id) REFERENCES sisters(id) ON DELETE CASCADE,
      FOREIGN KEY(task_id) REFERENCES tasks(id) ON DELETE CASCADE
    );

    -- ---------------- PLANS ----------------
    CREATE TABLE IF NOT EXISTS plans (
      id         INTEGER PRIMARY KEY AUTOINCREMENT,
      week       TEXT NOT NULL,        -- lundi ISO YYYY-MM-DD
      locked     INTEGER NOT NULL DEFAULT 0,
      created_at TEXT NOT NULL DEFAULT (datetime('now'))
    );

    CREATE TABLE IF NOT EXISTS plan_items (
      id         INTEGER PRIMARY KEY AUTOINCREMENT,
      plan_id    INTEGER NOT NULL,
      day        TEXT NOT NULL,        -- Mon..Sun
      moment     TEXT NOT NULL,        -- AM/PM
      task_id    INTEGER NOT NULL,
      sister_ids TEXT NOT NULL DEFAULT '',  -- "1,7,9"
      FOREIGN KEY(plan_id) REFERENCES plans(id) ON DELETE CASCADE,
      FOREIGN KEY(task_id) REFERENCES tasks(id) ON DELETE CASCADE
    );

    -- ---------------- ELIGIBILITY ----------------
    CREATE TABLE IF NOT EXISTS eligibility (
      sister_id INTEGER NOT NULL,
      task_id   INTEGER NOT NULL,
      allowed   INTEGER NOT NULL DEFAULT 1,
      PRIMARY KEY (sister_id, task_id),
      FOREIGN KEY(sister_id) REFERENCES sisters(id) ON DELETE CASCADE,
      FOREIGN KEY(task_id) REFERENCES tasks(id) ON DELETE CASCADE
    );

    -- ---------------- INDEXES ----------------
    CREATE UNIQUE INDEX IF NOT EXISTS idx_plan_week
      ON plans(week);

    CREATE UNIQUE INDEX IF NOT EXISTS idx_plan_item_unique
      ON plan_items(plan_id, day, moment, task_id);

    CREATE INDEX IF NOT EXISTS idx_absences_date
      ON absences(date);

    CREATE INDEX IF NOT EXISTS idx_absences_sister_date
      ON absences(sister_id, date);

    CREATE INDEX IF NOT EXISTS idx_fixed_assignments_sister
      ON fixed_assignments(sister_id);

    CREATE INDEX IF NOT EXISTS idx_fixed_assignments_task
      ON fixed_assignments(task_id);

    CREATE INDEX IF NOT EXISTS idx_eligibility_sister
      ON eligibility(sister_id);

    CREATE INDEX IF NOT EXISTS idx_eligibility_task
      ON eligibility(task_id);
    """)

    # ---------------- MIGRATIONS SÛRES ----------------
    # Pour les anciennes bases qui n'auraient pas toutes les colonnes
    _ensure_column(conn, "tasks", "people", "INTEGER NOT NULL DEFAULT 1")
    _ensure_column(conn, "tasks", "type", "TEXT NOT NULL DEFAULT 'Fixe'")
    _ensure_column(conn, "tasks", "prio", "INTEGER NOT NULL DEFAULT 2")
    _ensure_column(conn, "tasks", "active", "INTEGER NOT NULL DEFAULT 1")
    _ensure_column(conn, "tasks", "rule", "TEXT NOT NULL DEFAULT ''")
    _ensure_column(conn, "sisters", "restr", "TEXT NOT NULL DEFAULT '—'")

    # ---------------- AUTO-RÉPARATION ELIGIBILITY ----------------
    # 1) chaque sœur doit avoir une ligne par tâche
    sisters = conn.execute("SELECT id FROM sisters").fetchall()
    tasks = conn.execute("SELECT id FROM tasks").fetchall()

    for s in sisters:
        for t in tasks:
            conn.execute("""
                INSERT OR IGNORE INTO eligibility (sister_id, task_id, allowed)
                VALUES (?, ?, 1)
            """, (s["id"], t["id"]))

    conn.commit()
    conn.close()