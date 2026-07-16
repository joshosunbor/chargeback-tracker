import sqlite3

from flask import Blueprint, jsonify, request

from ..db import get_db, utcnow
from .auth import current_user

bp = Blueprint("cases", __name__, url_prefix="/api/cases")

STATUSES = ["new", "under_review", "represented", "won", "lost", "accepted"]
TERMINAL_STATUSES = {"won", "lost", "accepted"}

# Fields the client may set on create/update
EDITABLE_FIELDS = [
    "case_number", "merchant", "customer", "amount_cents", "currency",
    "reason_code", "received_date", "due_date", "resolved_date",
]


def error(message, code=400):
    return jsonify({"error": message}), code


def validate(data, creating):
    if creating:
        for field in ("case_number", "merchant", "amount_cents"):
            if not data.get(field) and data.get(field) != 0:
                return f"'{field}' is required"
    if "amount_cents" in data and not isinstance(data["amount_cents"], int):
        return "'amount_cents' must be an integer (cents)"
    if "status" in data and data["status"] not in STATUSES:
        return f"'status' must be one of: {', '.join(STATUSES)}"
    return None


def case_or_none(db, case_id):
    return db.execute("SELECT * FROM cases WHERE id = ?", (case_id,)).fetchone()


@bp.get("")
def list_cases():
    db = get_db()
    sql = "SELECT * FROM cases"
    clauses, params = [], []
    status = request.args.get("status")
    if status:
        clauses.append("status = ?")
        params.append(status)
    q = request.args.get("q")
    if q:
        like = f"%{q}%"
        clauses.append("(case_number LIKE ? OR merchant LIKE ? OR customer LIKE ?)")
        params.extend([like, like, like])
    if clauses:
        sql += " WHERE " + " AND ".join(clauses)
    sql += " ORDER BY created_at DESC"
    rows = db.execute(sql, params).fetchall()
    return jsonify([dict(r) for r in rows])


@bp.post("")
def create_case():
    data = request.get_json(silent=True) or {}
    msg = validate(data, creating=True)
    if msg:
        return error(msg)

    db = get_db()
    now = utcnow()
    status = data.get("status", "new")
    fields = {f: data.get(f) for f in EDITABLE_FIELDS}
    fields.setdefault("currency", None)
    if not fields["currency"]:
        fields["currency"] = "USD"

    user_id = current_user()["id"]
    try:
        cur = db.execute(
            """INSERT INTO cases (case_number, merchant, customer, amount_cents, currency,
                                  reason_code, status, received_date, due_date, resolved_date,
                                  created_at, updated_at, created_by)
               VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
            (fields["case_number"], fields["merchant"], fields["customer"],
             fields["amount_cents"], fields["currency"], fields["reason_code"],
             status, fields["received_date"], fields["due_date"],
             fields["resolved_date"], now, now, user_id),
        )
    except sqlite3.IntegrityError:
        db.rollback()
        return error(f"case_number '{fields['case_number']}' already exists", 409)

    case_id = cur.lastrowid
    db.execute(
        "INSERT INTO case_history (case_id, old_status, new_status, note, created_at, user_id) VALUES (?, NULL, ?, 'Case created', ?, ?)",
        (case_id, status, now, user_id),
    )
    db.commit()
    return jsonify(dict(case_or_none(db, case_id))), 201


@bp.get("/<int:case_id>")
def get_case(case_id):
    db = get_db()
    case = case_or_none(db, case_id)
    if case is None:
        return error("case not found", 404)
    result = dict(case)
    creator = db.execute(
        "SELECT username FROM users WHERE id = ?", (case["created_by"],)).fetchone()
    result["created_by_username"] = creator["username"] if creator else None
    result["history"] = [dict(r) for r in db.execute(
        """SELECT h.*, u.username FROM case_history h
           LEFT JOIN users u ON u.id = h.user_id
           WHERE h.case_id = ? ORDER BY h.created_at, h.id""", (case_id,))]
    result["notes"] = [dict(r) for r in db.execute(
        """SELECT n.*, u.username FROM notes n
           LEFT JOIN users u ON u.id = n.user_id
           WHERE n.case_id = ? ORDER BY n.created_at, n.id""", (case_id,))]
    result["attachments"] = [dict(r) for r in db.execute(
        """SELECT a.id, a.case_id, a.filename, a.content_type, a.size_bytes, a.created_at, u.username
           FROM attachments a LEFT JOIN users u ON u.id = a.user_id
           WHERE a.case_id = ? ORDER BY a.created_at, a.id""", (case_id,))]
    return jsonify(result)


@bp.patch("/<int:case_id>")
def update_case(case_id):
    db = get_db()
    case = case_or_none(db, case_id)
    if case is None:
        return error("case not found", 404)

    data = request.get_json(silent=True) or {}
    msg = validate(data, creating=False)
    if msg:
        return error(msg)

    now = utcnow()
    updates, params = [], []
    for field in EDITABLE_FIELDS:
        if field in data:
            updates.append(f"{field} = ?")
            params.append(data[field])

    new_status = data.get("status")
    if new_status and new_status != case["status"]:
        updates.append("status = ?")
        params.append(new_status)
        # Auto-stamp resolved_date when a case reaches a terminal status
        if new_status in TERMINAL_STATUSES and "resolved_date" not in data and not case["resolved_date"]:
            updates.append("resolved_date = ?")
            params.append(now[:10])
        db.execute(
            "INSERT INTO case_history (case_id, old_status, new_status, note, created_at, user_id) VALUES (?, ?, ?, ?, ?, ?)",
            (case_id, case["status"], new_status, data.get("status_note"), now, current_user()["id"]),
        )

    if not updates:
        if "status" in data:  # same-status re-submit: harmless no-op
            return jsonify(dict(case))
        return error("no updatable fields in request")

    updates.append("updated_at = ?")
    params.append(now)
    params.append(case_id)
    try:
        db.execute(f"UPDATE cases SET {', '.join(updates)} WHERE id = ?", params)
    except sqlite3.IntegrityError:
        db.rollback()
        return error("update failed (duplicate case_number?)", 409)
    db.commit()
    return jsonify(dict(case_or_none(db, case_id)))


@bp.delete("/<int:case_id>")
def delete_case(case_id):
    db = get_db()
    if case_or_none(db, case_id) is None:
        return error("case not found", 404)
    db.execute("DELETE FROM cases WHERE id = ?", (case_id,))
    db.commit()
    return "", 204
