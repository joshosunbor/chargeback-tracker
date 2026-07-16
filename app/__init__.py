import secrets
from pathlib import Path

from flask import Flask, jsonify, request, send_from_directory

ROOT = Path(__file__).resolve().parent.parent


def create_app(data_dir=None):
    data_dir = Path(data_dir) if data_dir else ROOT / "data"
    attachments_dir = data_dir / "attachments"
    attachments_dir.mkdir(parents=True, exist_ok=True)

    app = Flask(__name__, static_folder=str(ROOT / "static"), static_url_path="/static")
    app.config["DATABASE"] = str(data_dir / "app.db")
    app.config["ATTACHMENTS_DIR"] = str(attachments_dir)
    app.config["MAX_CONTENT_LENGTH"] = 10 * 1024 * 1024  # 10 MB upload cap

    # Session-signing key persisted under data/ so logins survive restarts
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
