# app.py
from flask import Flask, jsonify, request, render_template
from datetime import datetime, timedelta
from db import init_db, get_conn

app = Flask(__name__)


# ----------------- Helpers -----------------
DAY_TO_OFFSET = {
    "Mon": 0,
    "Tue": 1,
    "Wed": 2,
    "Thu": 3,
    "Fri": 4,
    "Sat": 5,
    "Sun": 6,
}


def add_days(iso_date: str, days: int) -> str:
    d = datetime.strptime(iso_date, "%Y-%m-%d") + timedelta(days=days)
    return d.strftime("%Y-%m-%d")


def week_dates(week_monday: str):
    start = datetime.strptime(week_monday, "%Y-%m-%d")
    return [(start + timedelta(days=i)).strftime("%Y-%m-%d") for i in range(7)]


def slot_date_from_week_and_day(week_monday: str, day_key: str) -> str:
    offset = DAY_TO_OFFSET.get(day_key, 0)
    return add_days(week_monday, offset)


@app.get("/")
def home():
    return render_template("index.html")


# ----------------- TASKS -----------------
@app.get("/api/tasks")
def list_tasks():
    conn = get_conn()
    rows = conn.execute("""
        SELECT id, name, moment, days, people, type, prio, active, rule
        FROM tasks
        ORDER BY active DESC, prio ASC, name ASC
    """).fetchall()
    conn.close()
    return jsonify([dict(r) for r in rows])


@app.post("/api/tasks")
def create_task():
    data = request.get_json(force=True)

    conn = get_conn()
    cur = conn.execute("""
        INSERT INTO tasks(name, moment, days, people, type, prio, active, rule)
        VALUES (?, ?, ?, ?, ?, ?, ?, ?)
    """, (
        data.get("name", "").strip(),
        data.get("moment", "AM"),
        ",".join(data.get("days", [])),
        int(data.get("people", 1)),
        data.get("type", "Fixe"),
        int(data.get("prio", 2)),
        1 if data.get("active", True) else 0,
        data.get("rule", "").strip(),
    ))
    task_id = cur.lastrowid

    # La nouvelle tâche devient autorisée par défaut pour toutes les sœurs existantes
    sisters = conn.execute("SELECT id FROM sisters").fetchall()
    for s in sisters:
        conn.execute("""
            INSERT OR IGNORE INTO eligibility (sister_id, task_id, allowed)
            VALUES (?, ?, 1)
        """, (s["id"], task_id))

    conn.commit()
    conn.close()
    return jsonify({"id": task_id}), 201


@app.put("/api/tasks/<int:task_id>")
def update_task(task_id: int):
    data = request.get_json(force=True)

    conn = get_conn()
    conn.execute("""
        UPDATE tasks
        SET name=?, moment=?, days=?, people=?, type=?, prio=?, active=?, rule=?
        WHERE id=?
    """, (
        data.get("name", "").strip(),
        data.get("moment", "AM"),
        ",".join(data.get("days", [])),
        int(data.get("people", 1)),
        data.get("type", "Fixe"),
        int(data.get("prio", 2)),
        1 if data.get("active", True) else 0,
        data.get("rule", "").strip(),
        task_id
    ))
    conn.commit()
    conn.close()
    return jsonify({"ok": True})


@app.delete("/api/tasks/<int:task_id>")
def delete_task(task_id: int):
    conn = get_conn()
    conn.execute("DELETE FROM tasks WHERE id=?", (task_id,))
    conn.execute("DELETE FROM fixed_assignments WHERE task_id=?", (task_id,))
    conn.execute("DELETE FROM eligibility WHERE task_id=?", (task_id,))
    conn.commit()
    conn.close()
    return jsonify({"ok": True})


# ----------------- SISTERS -----------------
@app.get("/api/sisters")
def list_sisters():
    conn = get_conn()
    rows = conn.execute("""
        SELECT id, name, active, restr
        FROM sisters
        ORDER BY active DESC, name ASC
    """).fetchall()
    conn.close()
    return jsonify([dict(r) for r in rows])


@app.post("/api/sisters")
def create_sister():
    data = request.get_json(force=True)

    conn = get_conn()
    cur = conn.execute("""
        INSERT INTO sisters(name, active, restr)
        VALUES (?, ?, ?)
    """, (
        data.get("name", "").strip(),
        1 if data.get("active", True) else 0,
        data.get("restr", "").strip() or "—"
    ))
    sid = cur.lastrowid

    # Toutes les tâches existantes sont autorisées par défaut pour la nouvelle sœur
    task_rows = conn.execute("SELECT id FROM tasks").fetchall()
    for tr in task_rows:
        conn.execute("""
            INSERT OR IGNORE INTO eligibility(sister_id, task_id, allowed)
            VALUES (?, ?, 1)
        """, (sid, tr["id"]))

    conn.commit()
    conn.close()
    return jsonify({"id": sid}), 201


@app.put("/api/sisters/<int:sister_id>")
def update_sister(sister_id: int):
    data = request.get_json(force=True)

    conn = get_conn()
    conn.execute("""
        UPDATE sisters
        SET name=?, active=?, restr=?
        WHERE id=?
    """, (
        data.get("name", "").strip(),
        1 if data.get("active", True) else 0,
        data.get("restr", "").strip() or "—",
        sister_id
    ))
    conn.commit()
    conn.close()
    return jsonify({"ok": True})


@app.delete("/api/sisters/<int:sister_id>")
def delete_sister(sister_id: int):
    conn = get_conn()
    conn.execute("DELETE FROM sisters WHERE id=?", (sister_id,))
    conn.execute("DELETE FROM absences WHERE sister_id=?", (sister_id,))
    conn.execute("DELETE FROM fixed_assignments WHERE sister_id=?", (sister_id,))
    conn.execute("DELETE FROM eligibility WHERE sister_id=?", (sister_id,))
    conn.commit()
    conn.close()
    return jsonify({"ok": True})


# ----------------- ELIGIBILITY -----------------
@app.get("/api/eligibility/<int:sister_id>")
def get_eligibility(sister_id: int):
    conn = get_conn()
    rows = conn.execute("""
        SELECT task_id, allowed
        FROM eligibility
        WHERE sister_id=?
    """, (sister_id,)).fetchall()
    conn.close()

    out = {int(r["task_id"]): bool(r["allowed"]) for r in rows}
    return jsonify(out)


@app.post("/api/eligibility/<int:sister_id>")
def set_eligibility(sister_id: int):
    data = request.get_json(force=True)
    conn = get_conn()

    all_tasks = conn.execute("SELECT id FROM tasks").fetchall()
    for tr in all_tasks:
        conn.execute("""
            INSERT OR IGNORE INTO eligibility(sister_id, task_id, allowed)
            VALUES (?, ?, 1)
        """, (sister_id, tr["id"]))

    if "allowedTaskIds" in data:
        allowed = set(int(x) for x in (data.get("allowedTaskIds") or []))
        for tr in all_tasks:
            conn.execute("""
                UPDATE eligibility
                SET allowed=?
                WHERE sister_id=? AND task_id=?
            """, (1 if tr["id"] in allowed else 0, sister_id, tr["id"]))
    else:
        m = data.get("map") or {}
        for k, v in m.items():
            try:
                task_id = int(k)
            except Exception:
                continue
            conn.execute("""
                INSERT INTO eligibility(sister_id, task_id, allowed)
                VALUES (?, ?, ?)
                ON CONFLICT(sister_id, task_id) DO UPDATE SET allowed=excluded.allowed
            """, (sister_id, task_id, 1 if bool(v) else 0))

    conn.commit()
    conn.close()
    return jsonify({"ok": True})


# ----------------- ABSENCES -----------------
@app.get("/api/absences")
def list_absences():
    date = request.args.get("date", "").strip()

    conn = get_conn()
    if date:
        rows = conn.execute("""
            SELECT id, sister_id, date, moment, reason
            FROM absences
            WHERE date=?
            ORDER BY date ASC, sister_id ASC
        """, (date,)).fetchall()
    else:
        rows = conn.execute("""
            SELECT id, sister_id, date, moment, reason
            FROM absences
            ORDER BY date DESC, sister_id ASC
            LIMIT 500
        """).fetchall()
    conn.close()

    return jsonify([dict(r) for r in rows])


@app.post("/api/absences")
def create_absence():
    data = request.get_json(force=True)

    conn = get_conn()
    cur = conn.execute("""
        INSERT INTO absences(sister_id, date, moment, reason)
        VALUES (?, ?, ?, ?)
    """, (
        int(data["sister_id"]),
        data["date"],
        data.get("moment", "AM"),
        data.get("reason", "Autre")
    ))
    conn.commit()
    aid = cur.lastrowid
    conn.close()

    return jsonify({"id": aid}), 201


@app.delete("/api/absences/<int:absence_id>")
def delete_absence(absence_id: int):
    conn = get_conn()
    conn.execute("DELETE FROM absences WHERE id=?", (absence_id,))
    conn.commit()
    conn.close()
    return jsonify({"ok": True})


# ----------------- FIXED ASSIGNMENTS -----------------
@app.get("/api/fixed_assignments")
def list_fixed_assignments():
    conn = get_conn()
    rows = conn.execute("""
        SELECT id, sister_id, task_id, days, moment, start, end, type
        FROM fixed_assignments
        ORDER BY start DESC, type ASC, sister_id ASC
    """).fetchall()
    conn.close()
    return jsonify([dict(r) for r in rows])


@app.post("/api/fixed_assignments")
def create_fixed_assignment():
    data = request.get_json(force=True)

    conn = get_conn()
    cur = conn.execute("""
        INSERT INTO fixed_assignments(sister_id, task_id, days, moment, start, end, type)
        VALUES (?, ?, ?, ?, ?, ?, ?)
    """, (
        int(data["sister_id"]),
        int(data["task_id"]),
        ",".join(data.get("days", [])),
        data.get("moment", "AM"),
        data.get("start"),
        data.get("end"),
        data.get("type", "Bloquant")
    ))
    conn.commit()
    fid = cur.lastrowid
    conn.close()
    return jsonify({"id": fid}), 201


@app.delete("/api/fixed_assignments/<int:fa_id>")
def delete_fixed_assignment(fa_id: int):
    conn = get_conn()
    conn.execute("DELETE FROM fixed_assignments WHERE id=?", (fa_id,))
    conn.commit()
    conn.close()
    return jsonify({"ok": True})


# ----------------- PLANS -----------------
@app.get("/api/plans/<week>")
def get_plan(week: str):
    conn = get_conn()

    plan = conn.execute("""
        SELECT id, week, locked
        FROM plans
        WHERE week=?
    """, (week,)).fetchone()

    if not plan:
        conn.close()
        return jsonify({"exists": False})

    items = conn.execute("""
        SELECT day, moment, task_id, sister_ids
        FROM plan_items
        WHERE plan_id=?
        ORDER BY day ASC, moment ASC, task_id ASC
    """, (plan["id"],)).fetchall()

    conn.close()

    planning = {}
    for r in items:
        key = f'{r["day"]}-{r["moment"]}'
        if key not in planning:
            planning[key] = []
        sister_ids = [int(x) for x in (r["sister_ids"] or "").split(",") if x.strip().isdigit()]
        planning[key].append({"taskId": r["task_id"], "assigned": sister_ids})

    return jsonify({
        "exists": True,
        "week": plan["week"],
        "locked": bool(plan["locked"]),
        "planning": planning
    })


@app.post("/api/plans/<week>")
def save_plan(week: str):
    data = request.get_json(force=True)
    planning = data.get("planning", {})
    locked = 1 if data.get("locked", False) else 0

    conn = get_conn()

    plan = conn.execute("SELECT id FROM plans WHERE week=?", (week,)).fetchone()
    if not plan:
        cur = conn.execute("INSERT INTO plans(week, locked) VALUES(?, ?)", (week, locked))
        plan_id = cur.lastrowid
    else:
        plan_id = plan["id"]
        conn.execute("UPDATE plans SET locked=? WHERE id=?", (locked, plan_id))

    conn.execute("DELETE FROM plan_items WHERE plan_id=?", (plan_id,))

    for slot_key, items in planning.items():
        try:
            day, moment = slot_key.split("-")
        except ValueError:
            continue

        for it in items:
            task_id = int(it.get("taskId"))
            assigned = it.get("assigned", []) or []
            sister_ids = ",".join(str(int(x)) for x in assigned)

            conn.execute("""
                INSERT INTO plan_items(plan_id, day, moment, task_id, sister_ids)
                VALUES (?, ?, ?, ?, ?)
            """, (plan_id, day, moment, task_id, sister_ids))

    conn.commit()
    conn.close()

    return jsonify({"ok": True, "week": week})


@app.post("/api/plans/<week>/lock")
def lock_plan(week: str):
    conn = get_conn()
    conn.execute("INSERT OR IGNORE INTO plans(week, locked) VALUES(?, 0)", (week,))
    conn.execute("UPDATE plans SET locked=1 WHERE week=?", (week,))
    conn.commit()
    conn.close()
    return jsonify({"ok": True, "week": week, "locked": True})


@app.post("/api/plans/<week>/unlock")
def unlock_plan(week: str):
    conn = get_conn()
    conn.execute("INSERT OR IGNORE INTO plans(week, locked) VALUES(?, 0)", (week,))
    conn.execute("UPDATE plans SET locked=0 WHERE week=?", (week,))
    conn.commit()
    conn.close()
    return jsonify({"ok": True, "week": week, "locked": False})


@app.post("/api/plans/<week>/clone_next")
def clone_plan_next(week: str):
    conn = get_conn()

    src = conn.execute("SELECT id FROM plans WHERE week=?", (week,)).fetchone()
    if not src:
        conn.close()
        return jsonify({"ok": False, "error": "source plan not found"}), 404

    src_plan_id = src["id"]
    target_week = add_days(week, 7)

    tgt = conn.execute("SELECT id FROM plans WHERE week=?", (target_week,)).fetchone()
    if not tgt:
        cur = conn.execute("INSERT INTO plans(week, locked) VALUES(?, 0)", (target_week,))
        tgt_plan_id = cur.lastrowid
    else:
        tgt_plan_id = tgt["id"]
        conn.execute("UPDATE plans SET locked=0 WHERE id=?", (tgt_plan_id,))

    conn.execute("DELETE FROM plan_items WHERE plan_id=?", (tgt_plan_id,))

    rows = conn.execute("""
        SELECT day, moment, task_id, sister_ids
        FROM plan_items
        WHERE plan_id=?
    """, (src_plan_id,)).fetchall()

    for r in rows:
        conn.execute("""
            INSERT INTO plan_items(plan_id, day, moment, task_id, sister_ids)
            VALUES (?, ?, ?, ?, ?)
        """, (tgt_plan_id, r["day"], r["moment"], r["task_id"], r["sister_ids"]))

    conn.commit()
    conn.close()

    return jsonify({
        "ok": True,
        "from": week,
        "to": target_week,
        "copied": len(rows)
    })


# ----------------- PLAN CHECK / SUMMARY -----------------
@app.get("/api/plans/<week>/check")
def check_plan(week: str):
    """
    Retourne:
    - issues par case (Mon-AM etc.)
    - résumé global en haut
    - distinction entre:
      * impossible
      * conflict
      * empty
      * partial
    """
    conn = get_conn()

    plan = conn.execute("SELECT id FROM plans WHERE week=?", (week,)).fetchone()
    if not plan:
        conn.close()
        return jsonify({
            "exists": False,
            "issues": {},
            "summary": {
                "impossible": 0,
                "conflict": 0,
                "empty": 0,
                "partial": 0,
                "to_complete": 0,
                "weekly_absences": 0,
                "total_problems": 0,
            }
        })

    plan_id = plan["id"]

    # tâches
    task_rows = conn.execute("""
        SELECT id, people, active
        FROM tasks
    """).fetchall()
    people_by_task = {int(r["id"]): int(r["people"]) for r in task_rows}
    active_task_ids = {int(r["id"]) for r in task_rows if int(r["active"]) == 1}

    # items du plan
    items = conn.execute("""
        SELECT day, moment, task_id, sister_ids
        FROM plan_items
        WHERE plan_id=?
    """, (plan_id,)).fetchall()

    # absences de la semaine
    week_start = week
    week_end = add_days(week, 6)

    abs_rows = conn.execute("""
        SELECT sister_id, date, moment
        FROM absences
        WHERE date >= ? AND date <= ?
    """, (week_start, week_end)).fetchall()

    absent = {(r["date"], r["moment"], int(r["sister_id"])) for r in abs_rows}
    weekly_absence_count = len(abs_rows)

    # eligibility
    elig_rows = conn.execute("""
        SELECT sister_id, task_id, allowed
        FROM eligibility
    """).fetchall()

    allowed_map = {}
    for r in elig_rows:
        sid = int(r["sister_id"])
        tid = int(r["task_id"])
        allowed_map[(sid, tid)] = int(r["allowed"]) == 1

    # sœurs actives
    sister_rows = conn.execute("""
        SELECT id, active
        FROM sisters
    """).fetchall()
    active_sisters = {int(r["id"]) for r in sister_rows if int(r["active"]) == 1}

    issues = {}
    summary = {
        "impossible": 0,
        "conflict": 0,
        "empty": 0,
        "partial": 0,
        "to_complete": 0,
        "weekly_absences": weekly_absence_count,
        "total_problems": 0,
    }

    # Pour savoir si une tâche est "impossible", on regarde si le réservoir maximal
    # de sœurs possibles pour ce créneau est inférieur au nombre attendu.
    for r in items:
        day = r["day"]
        moment = r["moment"]
        task_id = int(r["task_id"])

        if task_id not in active_task_ids:
            continue

        expected = people_by_task.get(task_id, 1)
        assigned = [int(x) for x in (r["sister_ids"] or "").split(",") if x.strip().isdigit()]
        assigned_n = len(assigned)

        slot_date = slot_date_from_week_and_day(week, day)

        # sœurs potentiellement possibles pour CETTE tâche et CE créneau
        possible_candidates = []
        for sid in active_sisters:
            is_allowed = allowed_map.get((sid, task_id), True)
            if not is_allowed:
                continue

            absent_for_slot = ((slot_date, moment, sid) in absent) or ((slot_date, "Journée", sid) in absent)
            if absent_for_slot:
                continue

            possible_candidates.append(sid)

        max_possible = len(possible_candidates)

        # conflit = affectation incohérente
        has_conflict = False
        for sid in assigned:
            if sid not in active_sisters:
                has_conflict = True
                break

            is_allowed = allowed_map.get((sid, task_id), True)
            if not is_allowed:
                has_conflict = True
                break

            absent_for_slot = ((slot_date, moment, sid) in absent) or ((slot_date, "Journée", sid) in absent)
            if absent_for_slot:
                has_conflict = True
                break

        status = None

        # ordre d'importance
        if max_possible < expected:
            status = "impossible"
        elif has_conflict:
            status = "conflict"
        elif assigned_n == 0:
            status = "empty"
        elif assigned_n < expected:
            status = "partial"

        if status:
            slot_key = f"{day}-{moment}"
            if slot_key not in issues:
                issues[slot_key] = []

            issues[slot_key].append({
                "taskId": task_id,
                "status": status,
                "expected": expected,
                "assigned": assigned_n,
                "max_possible": max_possible,
            })

            summary[status] += 1
            if status in ("empty", "partial"):
                summary["to_complete"] += 1

    summary["total_problems"] = (
        summary["impossible"] +
        summary["conflict"] +
        summary["empty"] +
        summary["partial"]
    )

    conn.close()
    return jsonify({
        "exists": True,
        "week": week,
        "issues": issues,
        "summary": summary
    })


# ----------------- HEALTH -----------------
@app.get("/api/health")
def health():
    return jsonify({"ok": True})


if __name__ == "__main__":
    init_db()
    app.run(host="127.0.0.1", port=5000, debug=True)