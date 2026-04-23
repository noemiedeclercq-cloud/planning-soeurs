import os
import sqlite3
from pathlib import Path

# 👉 Choix du chemin de la base
if os.getenv("RENDER"):
    DB_PATH = Path("/var/data/planning.db")
else:
    DB_PATH = Path(__file__).with_name("planning.db")


def get_conn():
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    return conn


def init_db():
    # 👉 IMPORTANT : crée le dossier si besoin (sinon crash sur Render)
    DB_PATH.parent.mkdir(parents=True, exist_ok=True)

    conn = get_conn()
    cursor = conn.cursor()

    # =====================
    # TABLE SOEURS
    # =====================
    cursor.execute("""
        CREATE TABLE IF NOT EXISTS soeurs (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            nom TEXT NOT NULL
        )
    """)

    # =====================
    # TABLE TACHES
    # =====================
    cursor.execute("""
        CREATE TABLE IF NOT EXISTS taches (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            nom TEXT NOT NULL,
            priorite INTEGER DEFAULT 0
        )
    """)

    # =====================
    # TABLE PLANNING
    # =====================
    cursor.execute("""
        CREATE TABLE IF NOT EXISTS planning (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            date TEXT,
            jour TEXT,
            creneau TEXT,
            tache_id INTEGER,
            soeur_id INTEGER,
            FOREIGN KEY (tache_id) REFERENCES taches(id),
            FOREIGN KEY (soeur_id) REFERENCES soeurs(id)
        )
    """)

    # =====================
    # TABLE ABSENCES
    # =====================
    cursor.execute("""
        CREATE TABLE IF NOT EXISTS absences (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            soeur_id INTEGER,
            date TEXT,
            FOREIGN KEY (soeur_id) REFERENCES soeurs(id)
        )
    """)

    conn.commit()
    conn.close()