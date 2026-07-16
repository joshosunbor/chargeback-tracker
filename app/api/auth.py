import sqlite3

from flask import Blueprint, jsonify, request, session
from werkzeug.security import check_password_hash, generate_password_hash

from ..db import get_db, utcnow

bp = Blueprint("auth", __name__, url_prefix="/api/auth")


def current_user():
    """The logged-in user's row, or None. Usable from any request context."""
    user_id = session.get("user_id")
    if user_id is None:
        return None
    return get_db().execute("SELECT * FROM users WHERE id = ?", (user_id,)).fetchone()


def public_user(row):
    return {"id": row["id"], "username": row["username"]}


@bp.post("/register")
def register():
    data = request.get_json(silent=True) or {}
    username = (data.get("username") or "").strip()
    password = data.get("password") or ""
    if not username:
        return jsonify({"error": "'username' is required"}), 400
    if len(password) < 4:
        return jsonify({"error": "password must be at least 4 characters"}), 400

    db = get_db()
    try:
        cur = db.execute(
            "INSERT INTO users (username, password_hash, created_at) VALUES (?, ?, ?)",
            (username, generate_password_hash(password), utcnow()),
        )
    except sqlite3.IntegrityError:
        return jsonify({"error": f"username '{username}' is already taken"}), 409
    db.commit()
    session["user_id"] = cur.lastrowid
    return jsonify({"id": cur.lastrowid, "username": username}), 201


@bp.post("/login")
def login():
    data = request.get_json(silent=True) or {}
    username = (data.get("username") or "").strip()
    password = data.get("password") or ""
    row = get_db().execute("SELECT * FROM users WHERE username = ?", (username,)).fetchone()
    if row is None or not check_password_hash(row["password_hash"], password):
        return jsonify({"error": "invalid username or password"}), 401
    session["user_id"] = row["id"]
    return jsonify(public_user(row))


@bp.post("/logout")
def logout():
    session.pop("user_id", None)
    return "", 204


@bp.get("/me")
def me():
    row = current_user()
    if row is None:
        return jsonify({"error": "not logged in"}), 401
    return jsonify(public_user(row))
