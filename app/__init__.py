import os
import secrets
from pathlib import Path

from flask import Flask, jsonify, request, send_from_directory

ROOT = Path(__file__).resolve().parent.parent


def _env_bool(name, default=False):
    val = os.environ.get(name)
    if val is None:
        return default
    return val.strip().lower() in ("1", "true", "yes", "on")


def create_app(data_dir=None):
    # DATA_DIR lets a PaaS point storage at a mounted persistent volume
    # (e.g. /data) so the SQLite db and uploads survive redeploys.
    data_dir = Path(data_dir or os.environ.get("DATA_DIR") or ROOT / "data")
    attachments_dir = data_dir / "attachments"
    attachments_dir.mkdir(parents=True, exist_ok=True)

    app = Flask(__name__, static_folder=str(ROOT / "static"), static_url_path="/static")
    app.config["DATABASE"] = str(data_dir / "app.db")
    app.config["ATTACHMENTS_DIR"] = str(attachments_dir)
    app.config["MAX_CONTENT_LENGTH"] = 10 * 1024 * 1024  # 10 MB upload cap

    # Public registration is closed by default; a fresh install with no users
    # yet is always allowed to create the first (bootstrap) account. See auth.py.
    app.config["ALLOW_SIGNUP"] = _env_bool("ALLOW_SIGNUP", default=False)

    # Harden the session cookie. SESSION_COOKIE_SECURE must be on in production
    # (HTTPS) so the login cookie is never sent over plain HTTP; keep it off for
    # local http:// dev. HttpOnly + SameSite=Lax are safe defaults everywhere.
    app.config["SESSION_COOKIE_HTTPONLY"] = True
    app.config["SESSION_COOKIE_SAMESITE"] = "Lax"
    app.config["SESSION_COOKIE_SECURE"] = _env_bool("SESSION_COOKIE_SECURE", default=False)

    # Prefer an injected SECRET_KEY (required on ephemeral PaaS filesystems, or
    # logins break on every redeploy). Fall back to a persisted key for local dev.
    secret = os.environ.get("SECRET_KEY")
    if secret:
        app.secret_key = secret.encode()
    else:
        secret_file = data_dir / "secret_key"
        if not secret_file.exists():
            secret_file.write_bytes(secrets.token_bytes(32))
        app.secret_key = secret_file.read_bytes()

    from . import db

    db.init_app(app)

    from .api import attachments, auth, cases, notes

    app.register_blueprint(auth.bp)
    app.register_blueprint(cases.bp)
    app.register_blueprint(notes.bp)
    app.register_blueprint(attachments.bp)

    @app.before_request
    def require_login():
        path = request.path
        if path.startswith("/api/") and not path.startswith("/api/auth/"):
            if auth.current_user() is None:
                return jsonify({"error": "authentication required"}), 401

    @app.route("/")
    def index():
        return send_from_directory(app.static_folder, "index.html")

    return app
