# db.py
import os
import sqlite3
from pathlib import Path

DB_PATH = Path(
    os.environ.get(
        "DB_PATH",
        "/var/data/planning.db" if os.getenv("RENDER") else Path(__file__).with_name("planning.db")
    )
)


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
      id                INTEGER PRIMARY KEY AUTOINCREMENT,
      name              TEXT NOT NULL,
      moment            TEXT NOT NULL,          -- AM, PM, AM+PM
      days              TEXT NOT NULL,          -- "Mon,Tue,Wed"
      people            INTEGER NOT NULL DEFAULT 1,
      type              TEXT NOT NULL DEFAULT 'Fixe',
      prio              INTEGER NOT NULL DEFAULT 2,
      active            INTEGER NOT NULL DEFAULT 1,
      rule              TEXT NOT NULL DEFAULT '',
      time_label        TEXT NOT NULL DEFAULT '',     -- ex: "09:30", "11:00", "Flexible"
      duration_minutes  INTEGER NOT NULL DEFAULT 60  -- durée estimée
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

    CREATE INDEX IF NOT EXISTS idx_tasks_active
      ON tasks(active);

    CREATE INDEX IF NOT EXISTS idx_tasks_moment
      ON tasks(moment);
    """)

    # ---------------- MIGRATIONS SÛRES ----------------
    _ensure_column(conn, "tasks", "people", "INTEGER NOT NULL DEFAULT 1")
    _ensure_column(conn, "tasks", "type", "TEXT NOT NULL DEFAULT 'Fixe'")
    _ensure_column(conn, "tasks", "prio", "INTEGER NOT NULL DEFAULT 2")
    _ensure_column(conn, "tasks", "active", "INTEGER NOT NULL DEFAULT 1")
    _ensure_column(conn, "tasks", "rule", "TEXT NOT NULL DEFAULT ''")
    _ensure_column(conn, "tasks", "time_label", "TEXT NOT NULL DEFAULT ''")
    _ensure_column(conn, "tasks", "duration_minutes", "INTEGER NOT NULL DEFAULT 60")
    _ensure_column(conn, "sisters", "restr", "TEXT NOT NULL DEFAULT '—'")

    # ---------------- NORMALISATION DES DONNÉES EXISTANTES ----------------
    # Si anciennes tâches sans heure, on met un repère simple selon le nom / moment
    task_rows = conn.execute("""
        SELECT id, name, moment, time_label, duration_minutes
        FROM tasks
    """).fetchall()

    for t in task_rows:
        task_id = int(t["id"])
        name = (t["name"] or "").strip().lower()
        moment = (t["moment"] or "AM").strip()
        time_label = (t["time_label"] or "").strip()
        duration = int(t["duration_minutes"] or 0)

        # heure par défaut si vide
        if not time_label:
            guessed_time = "Flexible"

            if "9h30" in name or "09:30" in name:
                guessed_time = "09:30"
            elif "11h" in name or "11:00" in name:
                guessed_time = "11:00"
            elif "11h50" in name or "11:50" in name:
                guessed_time = "11:50"
            elif "14h30" in name or "14:30" in name:
                guessed_time = "14:30"
            elif "16h50" in name or "16:50" in name:
                guessed_time = "16:50"
            else:
                if moment == "AM":
                    guessed_time = "09:30"
                elif moment == "PM":
                    guessed_time = "14:30"
                elif moment == "AM+PM":
                    guessed_time = "Flexible"

            conn.execute("""
                UPDATE tasks
                SET time_label=?
                WHERE id=?
            """, (guessed_time, task_id))

        # durée par défaut si vide / nulle
        if duration <= 0:
            guessed_duration = 60

            if "vaisselle" in name:
                guessed_duration = 30
            elif "réfectoire" in name or "refectoire" in name:
                guessed_duration = 60
            elif "légumes" in name or "legumes" in name:
                guessed_duration = 120
            elif "plats" in name:
                guessed_duration = 45
            elif "écoute" in name or "ecoute" in name:
                guessed_duration = 120
            elif "tables" in name:
                guessed_duration = 120
            elif "buanderie" in name or "repassage" in name or "pliage" in name:
                guessed_duration = 90
            elif "tunique" in name:
                guessed_duration = 120
            elif "pain" in name:
                guessed_duration = 45
            elif "humidification" in name:
                guessed_duration = 30
            elif "cuisson" in name or "cuisinière" in name or "cuisiniere" in name:
                guessed_duration = 120
            elif "coupe pain" in name:
                guessed_duration = 45

            conn.execute("""
                UPDATE tasks
                SET duration_minutes=?
                WHERE id=?
            """, (guessed_duration, task_id))

    # ---------------- AUTO-RÉPARATION ELIGIBILITY ----------------
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