"""Print key planning-soeurs table counts for the configured database."""

import sys
from pathlib import Path

ROOT_DIR = Path(__file__).resolve().parents[1]
if str(ROOT_DIR) not in sys.path:
    sys.path.insert(0, str(ROOT_DIR))

from db import get_conn, init_db


def main():
    init_db()
    conn = get_conn()
    try:
        for table in ("sisters", "tasks", "plans", "plan_items"):
            count = conn.execute(f"SELECT COUNT(*) AS count FROM {table}").fetchone()["count"]
            print(f"{table}={count}", flush=True)
    finally:
        conn.close()


if __name__ == "__main__":
    main()
