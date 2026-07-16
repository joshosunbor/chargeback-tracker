import secrets
from pathlib import Path

from flask import Blueprint, current_app, jsonify, request, send_from_directory
from werkzeug.utils import secure_filename

from ..db import get_db, utcnow
from .auth import current_user

bp = Blueprint("attachments", __name__, url_prefix="/api")


@bp.post("/cases/<int:case_id>/attachments")
def upload(case_id):
    db = get_db()
    if db.execute("SELECT 1 FROM cases WHERE id = ?", (case_id,)).fetchone() is None:
        return jsonify({"error": "case not found"}), 404

    file = request.files.get("file")
    if file is None or not file.filename:
        return jsonify({"error": "multipart field 'file' is required"}), 400

    filename = secure_filename(file.filename) or "attachment"
    stored_name = secrets.token_hex(16)
    dest = Path(current_app.config["ATTACHMENTS_DIR"]) / stored_name
    file.save(dest)

    cur = db.execute(
        """INSERT INTO attachments (case_id, filename, stored_name, content_type, size_bytes, created_at, user_id)
           VALUES (?, ?, ?, ?, ?, ?, ?)""",
        (case_id, filename, stored_name, file.mimetype, dest.stat().st_size, utcnow(), current_user()["id"]),
    )
    db.commit()
    row = db.execute(
        """SELECT a.id, a.case_id, a.filename, a.content_type, a.size_bytes, a.created_at, u.username
           FROM attachments a LEFT JOIN users u ON u.id = a.user_id WHERE a.id = ?""",
        (cur.lastrowid,),
    ).fetchone()
    return jsonify(dict(row)), 201


@bp.get("/attachments/<int:attachment_id>")
def download(attachment_id):
    db = get_db()
    row = db.execute("SELECT * FROM attachments WHERE id = ?", (attachment_id,)).fetchone()
    if row is None:
        return jsonify({"error": "attachment not found"}), 404
    return send_from_directory(
        current_app.config["ATTACHMENTS_DIR"],
        row["stored_name"],
        as_attachment=True,
        download_name=row["filename"],
        mimetype=row["content_type"],
    )


@bp.delete("/attachments/<int:attachment_id>")
def delete(attachment_id):
    db = get_db()
    row = db.execute("SELECT * FROM attachments WHERE id = ?", (attachment_id,)).fetchone()
    if row is None:
        return jsonify({"error": "attachment not found"}), 404
    (Path(current_app.config["ATTACHMENTS_DIR"]) / row["stored_name"]).unlink(missing_ok=True)
    db.execute("DELETE FROM attachments WHERE id = ?", (attachment_id,))
    db.commit()
    return "", 204
