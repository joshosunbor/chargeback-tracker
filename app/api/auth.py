import sqlite3

from flask import Blueprint, current_app, jsonify, request, session
from werkzeug.security import check_password_hash, generate_password_hash

from ..db import get_db, utcnow

bp = Blueprint("auth", __name__, url_prefix="/api/auth")


def current_user():
    """The logged-in user's row, or None. Usable from any request context.
    Note: a guest (demo) session has no user row — use is_guest() for that."""
    user_id = session.get("user_id")
    if user_id is None:
        return None
    return get_db().execute("SELECT * FROM users WHERE id = ?", (user_id,)).fetchone()


def is_guest():
    """True when the session is a shared read-only demo (guest) session."""
    return bool(session.get("guest"))


def public_user(row):
    return {"id": row["id"], "username": row["username"],
            "is_admin": bool(row["is_admin"]), "is_guest": False}


def guest_principal():
    return {"id": None, "username": "guest", "is_admin": False, "is_guest": True}


def signup_open():
    """Public registration is allowed only when ALLOW_SIGNUP is enabled. There
    is deliberately no first-user bootstrap (that would be a race on a public
    URL); the admin account is seeded from ADMIN_USERNAME / ADMIN_PASSWORD_HASH
    at startup instead — see app.create_app / db.seed_admin_from_env."""
    return bool(current_app.config["ALLOW_SIGNUP"])


@bp.get("/config")
def config():
    """Public: lets the login screen decide whether to offer signup."""
    return jsonify({"signup_open": signup_open()})


@bp.post("/register")
def register():
    if not signup_open():
        return jsonify({"error": "registration is closed; ask an admin for an account"}), 403

    db = get_db()
    data = request.get_json(silent=True) or {}
    username = (data.get("username") or "").strip()
    password = data.get("password") or ""
    if not username:
        return jsonify({"error": "'username' is required"}), 400
    if len(password) < 4:
        return jsonify({"error": "password must be at least 4 characters"}), 400

    try:
        cur = db.execute(
            "INSERT INTO users (username, password_hash, created_at) VALUES (?, ?, ?)",
            (username, generate_password_hash(password), utcnow()),
        )
    except sqlite3.IntegrityError:
        return jsonify({"error": f"username '{username}' is already taken"}), 409
    db.commit()
    session["user_id"] = cur.lastrowid
    return jsonify({"id": cur.lastrowid, "username": username, "is_admin": False}), 201


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


@bp.post("/guest")
def guest_login():
    """Start a shared read-only demo session. Guests can view synthetic data
    but every mutating request is rejected by the API guard (see create_app)."""
    session.clear()
    session["guest"] = True
    return jsonify(guest_principal())


@bp.post("/logout")
def logout():
    session.clear()
    return "", 204


@bp.get("/me")
def me():
    row = current_user()
    if row is not None:
        return jsonify(public_user(row))
    if is_guest():
        return jsonify(guest_principal())
    return jsonify({"error": "not logged in"}), 401
