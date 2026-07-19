import csv
import io
import sqlite3
from decimal import Decimal, InvalidOperation, ROUND_HALF_UP

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


def insert_case(db, fields, status, user_id, now, history_note):
    """Insert a case row plus its initial history row. Shared by the JSON
    create endpoint and the CSV importer. Raises sqlite3.IntegrityError on a
    duplicate case_number — callers decide whether that's an error or a skip."""
    cur = db.execute(
        """INSERT INTO cases (case_number, merchant, customer, amount_cents, currency,
                              reason_code, status, received_date, due_date, resolved_date,
                              created_at, updated_at, created_by)
           VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
        (fields["case_number"], fields["merchant"], fields.get("customer"),
         fields["amount_cents"], fields.get("currency") or "USD", fields.get("reason_code"),
         status, fields.get("received_date"), fields.get("due_date"),
         fields.get("resolved_date"), now, now, user_id),
    )
    case_id = cur.lastrowid
    db.execute(
        "INSERT INTO case_history (case_id, old_status, new_status, note, created_at, user_id) "
        "VALUES (?, NULL, ?, ?, ?, ?)",
        (case_id, status, history_note, now, user_id),
    )
    return case_id


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

    try:
        case_id = insert_case(db, fields, status, current_user()["id"], now, "Case created")
    except sqlite3.IntegrityError:
        db.rollback()
        return error(f"case_number '{fields['case_number']}' already exists", 409)

    db.commit()
    return jsonify(dict(case_or_none(db, case_id))), 201


# Columns accepted in an import CSV (header names, case-insensitive). amount is
# in dollars (e.g. 45.99) and converted to integer cents.
IMPORT_COLUMNS = [
    "case_number", "merchant", "customer", "amount", "currency",
    "reason_code", "status", "received_date", "due_date", "resolved_date",
]


def _parse_amount_to_cents(raw):
    s = (raw or "").strip().replace(",", "").lstrip("$").strip()
    if not s:
        raise ValueError("amount is required")
    try:
        return int((Decimal(s) * 100).to_integral_value(rounding=ROUND_HALF_UP))
    except InvalidOperation:
        raise ValueError(f"amount '{raw}' is not a valid number")


def _row_to_fields(row):
    """Validate one normalized CSV row and return (fields, status). Raises
    ValueError with a human-readable message on any problem."""
    case_number = (row.get("case_number") or "").strip()
    merchant = (row.get("merchant") or "").strip()
    if not case_number:
        raise ValueError("case_number is required")
    if not merchant:
        raise ValueError("merchant is required")

    status = (row.get("status") or "new").strip().lower()
    if status not in STATUSES:
        raise ValueError(f"invalid status '{status}' (expected one of {', '.join(STATUSES)})")

    fields = {
        "case_number": case_number,
        "merchant": merchant,
        "customer": (row.get("customer") or "").strip() or None,
        "amount_cents": _parse_amount_to_cents(row.get("amount")),
        "currency": (row.get("currency") or "USD").strip().upper() or "USD",
        "reason_code": (row.get("reason_code") or "").strip() or None,
        "received_date": (row.get("received_date") or "").strip() or None,
        "due_date": (row.get("due_date") or "").strip() or None,
        "resolved_date": (row.get("resolved_date") or "").strip() or None,
    }
    return fields, status


@bp.post("/import")
def import_cases():
    """Bulk-create cases from an uploaded CSV. Rows with a case_number that
    already exists are skipped; per-row problems are reported without aborting
    the whole import. Returns a summary: created / skipped / errors."""
    user = current_user()
    if not user["is_admin"]:
        return error("admin access required to import", 403)

    file = request.files.get("file")
    if file is None or not file.filename:
        return error("multipart field 'file' (a .csv) is required")

    try:
        text = file.read().decode("utf-8-sig")  # utf-8-sig strips a BOM if present
    except UnicodeDecodeError:
        return error("file must be UTF-8 encoded text")

    reader = csv.DictReader(io.StringIO(text))
    if not reader.fieldnames:
        return error("CSV has no header row")
    headers = {(h or "").strip().lower() for h in reader.fieldnames}
    missing = {"case_number", "merchant", "amount"} - headers
    if missing:
        return error(f"CSV is missing required column(s): {', '.join(sorted(missing))}")

    db = get_db()
    now = utcnow()
    user_id = user["id"]
    created, skipped, errors = 0, 0, []

    # Row 1 is the header, so the first data row is line 2.
    for line_no, raw_row in enumerate(reader, start=2):
        row = {(k or "").strip().lower(): v for k, v in raw_row.items()}
        try:
            fields, status = _row_to_fields(row)
        except ValueError as e:
            errors.append({"row": line_no, "error": str(e)})
            continue

        if db.execute("SELECT 1 FROM cases WHERE case_number = ?",
                      (fields["case_number"],)).fetchone():
            skipped += 1
            continue
        try:
            insert_case(db, fields, status, user_id, now, "Imported from CSV")
            created += 1
        except sqlite3.IntegrityError:
            # Duplicate within the same file (not yet committed) lands here.
            skipped += 1

    db.commit()
    return jsonify({
        "created": created,
        "skipped": skipped,
        "errors": errors,
        "total": created + skipped + len(errors),
    })


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
