# app.py
import hmac
import os
from datetime import datetime, timedelta

from flask import Flask, jsonify, redirect, request, render_template, session, url_for
from db import init_db, get_conn

app = Flask(__name__)
app.secret_key = os.getenv("SECRET_KEY") or os.getenv("PLANNING_PASSWORD") or "dev-secret-change-me"
init_db()


def auth_enabled():
    return bool(os.getenv("PLANNING_PASSWORD"))


def is_authenticated():
    return (not auth_enabled()) or bool(session.get("authenticated"))


@app.before_request
def require_auth():
    public_endpoints = {"login", "do_login", "logout", "health", "ping", "static"}
    if request.endpoint in public_endpoints:
        return None

    if is_authenticated():
        return None

    if request.path.startswith("/api/"):
        return jsonify({"ok": False, "error": "authentication required"}), 401

    return redirect(url_for("login", next=request.full_path))


@app.get("/login")
def login():
    if is_authenticated():
        return redirect(url_for("home"))
    return render_template("login.html", error="")


@app.post("/login")
def do_login():
    expected = os.getenv("PLANNING_PASSWORD", "")
    password = request.form.get("password", "")

    if expected and hmac.compare_digest(password, expected):
        session["authenticated"] = True
        next_path = request.args.get("next") or url_for("home")
        if not next_path.startswith("/") or next_path.startswith("//"):
            next_path = url_for("home")
        return redirect(next_path)

    return render_template("login.html", error="Mot de passe incorrect"), 401


@app.get("/logout")
def logout():
    session.clear()
    return redirect(url_for("login") if auth_enabled() else url_for("home"))

@app.get("/api/ping")
def ping():
    return {"ok": True}

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

REPETITION_START = 14 * 60 + 30
REPETITION_END = 15 * 60 + 30


def add_days(iso_date: str, days: int) -> str:
    d = datetime.strptime(iso_date, "%Y-%m-%d") + timedelta(days=days)
    return d.strftime("%Y-%m-%d")


def week_dates(week_monday: str):
    start = datetime.strptime(week_monday, "%Y-%m-%d")
    return [(start + timedelta(days=i)).strftime("%Y-%m-%d") for i in range(7)]


def slot_date_from_week_and_day(week_monday: str, day_key: str) -> str:
    offset = DAY_TO_OFFSET.get(day_key, 0)
    return add_days(week_monday, offset)


def parse_csv(s: str):
    return [x.strip() for x in (s or "").split(",") if x.strip()]


def normalize_time_label(label: str, moment: str) -> str:
    label = (label or "").strip()
    if not label:
        return "09:30" if moment == "AM" else "14:30" if moment == "PM" else "Flexible"
    return label


def time_label_to_minutes(label: str, moment: str) -> int:
    label = (label or "").strip().lower()

    if label in ("flex", "flexible", "souple", "libre"):
        return 100000 if moment == "PM" else 99999

    try:
        hh, mm = label.split(":")
        return int(hh) * 60 + int(mm)
    except Exception:
        if "11" in label:
            return 11 * 60
        if "14" in label:
            return 14 * 60 + 30
        if "9" in label:
            return 9 * 60 + 30
        return 100000 if moment == "PM" else 99999


def task_time_window(task_row):
    """
    Retourne (start_min, end_min, is_flexible)
    Flexible = placé en fin de demi-journée pour ne pas bloquer le reste.
    """
    moment = (task_row["moment"] or "AM").strip()
    label = normalize_time_label(task_row["time_label"], moment)
    duration = int(task_row["duration_minutes"] or 60)

    start = time_label_to_minutes(label, moment)
    is_flexible = start >= 99999

    if is_flexible:
        if moment == "AM":
            start = 11 * 60 + 50 - duration
        elif moment == "PM":
            start = 16 * 60 + 50 - duration
        else:
            start = 0

    end = start + duration
    return start, end, is_flexible


def intervals_overlap(a_start: int, a_end: int, b_start: int, b_end: int) -> bool:
    return max(a_start, b_start) < min(a_end, b_end)


def sister_absent(abs_rows, date_iso: str, moment: str, sister_id: int) -> bool:
    return ((date_iso, moment, sister_id) in abs_rows) or ((date_iso, "Journée", sister_id) in abs_rows)


def sister_in_repetition(repetition_days: str, day_key: str, moment: str, start: int, end: int) -> bool:
    if moment != "PM":
        return False
    if day_key not in parse_csv(repetition_days):
        return False
    return intervals_overlap(start, end, REPETITION_START, REPETITION_END)


@app.get("/")
def home():
    return render_template("index.html")


# ----------------- TASKS -----------------
@app.get("/api/tasks")
def list_tasks():
    conn = get_conn()
    rows = conn.execute("""
        SELECT id, name, moment, days, people, type, prio, active, rule,
               time_label, duration_minutes
        FROM tasks
        ORDER BY active DESC, prio ASC, name ASC
    """).fetchall()
    conn.close()
    return jsonify([dict(r) for r in rows])


@app.post("/api/tasks")
def create_task():
    data = request.get_json(force=True)

    name = data.get("name", "").strip()
    moment = data.get("moment", "AM")
    days = ",".join(data.get("days", []))
    people = int(data.get("people", 1))
    task_type = data.get("type", "Fixe")
    prio = int(data.get("prio", 2))
    active = 1 if data.get("active", True) else 0
    rule = data.get("rule", "").strip()
    time_label = normalize_time_label(data.get("time_label", ""), moment)
    duration_minutes = max(1, int(data.get("duration_minutes", 60)))

    conn = get_conn()
    cur = conn.execute("""
        INSERT INTO tasks(
            name, moment, days, people, type, prio, active, rule,
            time_label, duration_minutes
        )
        VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
    """, (
        name, moment, days, people, task_type, prio, active, rule,
        time_label, duration_minutes
    ))
    task_id = cur.lastrowid

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

    name = data.get("name", "").strip()
    moment = data.get("moment", "AM")
    days = ",".join(data.get("days", []))
    people = int(data.get("people", 1))
    task_type = data.get("type", "Fixe")
    prio = int(data.get("prio", 2))
    active = 1 if data.get("active", True) else 0
    rule = data.get("rule", "").strip()
    time_label = normalize_time_label(data.get("time_label", ""), moment)
    duration_minutes = max(1, int(data.get("duration_minutes", 60)))

    conn = get_conn()
    conn.execute("""
        UPDATE tasks
        SET name=?, moment=?, days=?, people=?, type=?, prio=?, active=?, rule=?,
            time_label=?, duration_minutes=?
        WHERE id=?
    """, (
        name, moment, days, people, task_type, prio, active, rule,
        time_label, duration_minutes, task_id
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
        SELECT id, name, active, restr, repetition_days
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
        INSERT INTO sisters(name, active, restr, repetition_days)
        VALUES (?, ?, ?, ?)
    """, (
        data.get("name", "").strip(),
        1 if data.get("active", True) else 0,
        data.get("restr", "").strip() or "—",
        ",".join(data.get("repetition_days", []))
    ))
    sid = cur.lastrowid

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
        SET name=?, active=?, restr=?, repetition_days=?
        WHERE id=?
    """, (
        data.get("name", "").strip(),
        1 if data.get("active", True) else 0,
        data.get("restr", "").strip() or "—",
        ",".join(data.get("repetition_days", [])),
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
    start = request.args.get("start", "").strip()
    end = request.args.get("end", "").strip()

    conn = get_conn()
    if start and end:
        rows = conn.execute("""
            SELECT id, sister_id, date, moment, reason
            FROM absences
            WHERE date >= ? AND date <= ?
            ORDER BY date ASC, sister_id ASC
        """, (start, end)).fetchall()
    elif date:
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

    plan = conn.execute("SELECT id, locked FROM plans WHERE week=?", (week,)).fetchone()
    if not plan:
        cur = conn.execute("INSERT INTO plans(week, locked) VALUES(?, ?)", (week, locked))
        plan_id = cur.lastrowid
    else:
        if int(plan["locked"]) == 1:
            conn.close()
            return jsonify({"ok": False, "error": "plan is locked"}), 423
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

    tgt = conn.execute("SELECT id, locked FROM plans WHERE week=?", (target_week,)).fetchone()
    if not tgt:
        cur = conn.execute("INSERT INTO plans(week, locked) VALUES(?, 0)", (target_week,))
        tgt_plan_id = cur.lastrowid
    else:
        if int(tgt["locked"]) == 1:
            conn.close()
            return jsonify({"ok": False, "error": "target plan is locked"}), 423
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
    Distinctions:
    - impossible: structurellement infaisable (pas assez de soeurs possibles)
    - conflict: affectation incohérente (absence / incompétence / chevauchement)
    - empty: aucune sœur affectée
    - partial: pas assez de sœurs affectées
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

    task_rows = conn.execute("""
        SELECT id, name, people, active, moment, time_label, duration_minutes
        FROM tasks
    """).fetchall()
    tasks_by_id = {int(r["id"]): r for r in task_rows}
    active_task_ids = {int(r["id"]) for r in task_rows if int(r["active"]) == 1}

    items = conn.execute("""
        SELECT day, moment, task_id, sister_ids
        FROM plan_items
        WHERE plan_id=?
    """, (plan_id,)).fetchall()

    week_start = week
    week_end = add_days(week, 6)

    abs_rows_raw = conn.execute("""
        SELECT sister_id, date, moment
        FROM absences
        WHERE date >= ? AND date <= ?
    """, (week_start, week_end)).fetchall()

    abs_rows = {(r["date"], r["moment"], int(r["sister_id"])) for r in abs_rows_raw}
    weekly_absence_count = len(abs_rows_raw)

    elig_rows = conn.execute("""
        SELECT sister_id, task_id, allowed
        FROM eligibility
    """).fetchall()
    allowed_map = {}
    for r in elig_rows:
        sid = int(r["sister_id"])
        tid = int(r["task_id"])
        allowed_map[(sid, tid)] = int(r["allowed"]) == 1

    sister_rows = conn.execute("""
        SELECT id, active, repetition_days
        FROM sisters
    """).fetchall()
    active_sisters = {int(r["id"]) for r in sister_rows if int(r["active"]) == 1}
    repetition_by_sister = {int(r["id"]): r["repetition_days"] or "" for r in sister_rows}

    # occupation d’une sœur par slot pour détecter les chevauchements
    occupancy = {}  # (day, moment, sister_id) -> list[(task_id, start, end)]
    for r in items:
        day = r["day"]
        moment = r["moment"]
        task_id = int(r["task_id"])
        task = tasks_by_id.get(task_id)
        if not task:
            continue
        start, end, _ = task_time_window(task)
        assigned = [int(x) for x in (r["sister_ids"] or "").split(",") if x.strip().isdigit()]
        for sid in assigned:
            key = (day, moment, sid)
            occupancy.setdefault(key, []).append((task_id, start, end))

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

    for r in items:
        day = r["day"]
        moment = r["moment"]
        task_id = int(r["task_id"])
        if task_id not in active_task_ids:
            continue

        task = tasks_by_id[task_id]
        expected = int(task["people"] or 1)
        start, end, _ = task_time_window(task)
        assigned = [int(x) for x in (r["sister_ids"] or "").split(",") if x.strip().isdigit()]
        assigned_n = len(assigned)

        slot_date = slot_date_from_week_and_day(week, day)

        possible_candidates = []
        for sid in active_sisters:
            is_allowed = allowed_map.get((sid, task_id), True)
            if not is_allowed:
                continue

            if sister_absent(abs_rows, slot_date, moment, sid):
                continue

            if sister_in_repetition(repetition_by_sister.get(sid, ""), day, moment, start, end):
                continue

            # vérifier chevauchement avec tâches déjà affectées à cette sœur dans ce créneau
            overlaps = False
            for other_task_id, o_start, o_end in occupancy.get((day, moment, sid), []):
                if other_task_id == task_id:
                    continue
                if intervals_overlap(start, end, o_start, o_end):
                    overlaps = True
                    break

            if not overlaps:
                possible_candidates.append(sid)

        max_possible = len(possible_candidates)

        has_conflict = False
        for sid in assigned:
            if sid not in active_sisters:
                has_conflict = True
                break

            is_allowed = allowed_map.get((sid, task_id), True)
            if not is_allowed:
                has_conflict = True
                break

            if sister_absent(abs_rows, slot_date, moment, sid):
                has_conflict = True
                break

            if sister_in_repetition(repetition_by_sister.get(sid, ""), day, moment, start, end):
                has_conflict = True
                break

            # chevauchement réel
            for other_task_id, o_start, o_end in occupancy.get((day, moment, sid), []):
                if other_task_id == task_id:
                    continue
                if intervals_overlap(start, end, o_start, o_end):
                    has_conflict = True
                    break
            if has_conflict:
                break

        status = None
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
            issues.setdefault(slot_key, []).append({
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


# ----------------- ABBESS DAILY VIEW -----------------
@app.get("/api/abbess/<date_iso>")
def abbess_daily_view(date_iso: str):
    """
    Donne une vue "par soeur" pour un jour donné:
    [
      {
        sister_id: 1,
        sister_name: "Sr Pascale",
        tasks: [
          {"name":"Réfectoire", "moment":"AM", "time_label":"09:30"},
          {"name":"Vaisselle", "moment":"AM", "time_label":"11:00"}
        ]
      }
    ]
    """
    dt = datetime.strptime(date_iso, "%Y-%m-%d")
    monday = dt - timedelta(days=dt.weekday())
    week = monday.strftime("%Y-%m-%d")
    day_key = list(DAY_TO_OFFSET.keys())[dt.weekday()]

    conn = get_conn()

    plan = conn.execute("SELECT id FROM plans WHERE week=?", (week,)).fetchone()
    if not plan:
        conn.close()
        return jsonify({
            "date": date_iso,
            "week": week,
            "day": day_key,
            "rows": []
        })

    items = conn.execute("""
        SELECT pi.moment, pi.task_id, pi.sister_ids,
               t.name, t.time_label, t.duration_minutes, t.type, t.prio
        FROM plan_items pi
        JOIN tasks t ON t.id = pi.task_id
        WHERE pi.plan_id=? AND pi.day=?
        ORDER BY pi.moment ASC, t.prio ASC, t.name ASC
    """, (plan["id"], day_key)).fetchall()

    sisters = conn.execute("""
        SELECT id, name
        FROM sisters
        WHERE active=1
        ORDER BY name ASC
    """).fetchall()
    sister_name = {int(s["id"]): s["name"] for s in sisters}

    rows_by_sister = {}

    for r in items:
        sister_ids = [int(x) for x in (r["sister_ids"] or "").split(",") if x.strip().isdigit()]
        for sid in sister_ids:
            rows_by_sister.setdefault(sid, [])
            rows_by_sister[sid].append({
                "name": r["name"],
                "moment": r["moment"],
                "time_label": r["time_label"],
                "duration_minutes": int(r["duration_minutes"] or 60),
                "type": r["type"],
                "prio": int(r["prio"] or 2),
            })

    out_rows = []
    for sid in sorted(rows_by_sister.keys(), key=lambda x: sister_name.get(x, "").lower()):
        tasks_for_sister = rows_by_sister[sid]
        tasks_for_sister.sort(key=lambda x: (
            x["moment"],
            time_label_to_minutes(x["time_label"], x["moment"]),
            x["prio"],
            x["name"].lower(),
        ))
        out_rows.append({
            "sister_id": sid,
            "sister_name": sister_name.get(sid, f"Sœur {sid}"),
            "tasks": tasks_for_sister
        })

    conn.close()
    return jsonify({
        "date": date_iso,
        "week": week,
        "day": day_key,
        "rows": out_rows
    })


# ----------------- HEALTH -----------------
@app.get("/api/health")
def health():
    return jsonify({"ok": True})


if __name__ == "__main__":
    app.run(host="127.0.0.1", port=5000, debug=True)
