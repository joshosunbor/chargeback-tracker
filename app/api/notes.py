from flask import Blueprint, jsonify, request

from ..db import get_db, utcnow
from .auth import current_user

bp = Blueprint("notes", __name__, url_prefix="/api/cases/<int:case_id>/notes")


@bp.post("")
def add_note(case_id):
    db = get_db()
    if db.execute("SELECT 1 FROM cases WHERE id = ?", (case_id,)).fetchone() is None:
        return jsonify({"error": "case not found"}), 404
    data = request.get_json(silent=True) or {}
    body = (data.get("body") or "").strip()
    if not body:
        return jsonify({"error": "'body' is required"}), 400
    cur = db.execute(
        "INSERT INTO notes (case_id, body, created_at, user_id) VALUES (?, ?, ?, ?)",
        (case_id, body, utcnow(), current_user()["id"]),
    )
    db.commit()
    row = db.execute(
        "SELECT n.*, u.username FROM notes n LEFT JOIN users u ON u.id = n.user_id WHERE n.id = ?",
        (cur.lastrowid,),
    ).fetchone()
    return jsonify(dict(row)), 201
