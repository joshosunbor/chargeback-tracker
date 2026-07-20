import os
import secrets
from pathlib import Path

from flask import Flask, jsonify, request, send_from_directory

ROOT = Path(__file__).resolve().parent.parent

# Deny-by-default authorization allowlist (enforced in guard_api below). These
# are the ONLY /api endpoints whose mutating methods are open to any
# authenticated non-admin user; every other write under /api is admin-only. A
# newly added write endpoint is therefore admin-only until it is deliberately
# listed here. Names are "<blueprint>.<view_function>" as reported by
# request.endpoint.
# The line: authenticated users *contribute* (create a case, note it, attach
# evidence); admins *destroy or rewrite* (edit, delete, import). So the three
# contributor writes are listed here and everything else stays admin-only.
USER_WRITABLE_ENDPOINTS = frozenset({
    "cases.create_case",   # POST /api/cases                  — file a new dispute
    "notes.add_note",      # POST /api/cases/<id>/notes       — annotate a case
    "attachments.upload",  # POST /api/cases/<id>/attachments — attach evidence
})


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

    # Public registration is closed by default and gated solely on ALLOW_SIGNUP;
    # there is deliberately no first-user bootstrap (it would race on a public
    # URL). The admin account is provisioned instead from ADMIN_USERNAME /
    # ADMIN_PASSWORD_HASH at startup — see db.seed_admin_from_env.
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
    def guard_api():
        # Central access control for the API. /api/auth/* handles its own auth.
        path = request.path
        if not path.startswith("/api/") or path.startswith("/api/auth/"):
            return
        user = auth.current_user()
        guest = auth.is_guest()
        if user is None and not guest:
            return jsonify({"error": "authentication required"}), 401
        # Guests are strictly read-only: every mutating method is rejected here,
        # before any view runs, so it holds for every endpoint (present and
        # future) even when called directly against the API.
        if guest and request.method not in ("GET", "HEAD", "OPTIONS"):
            return jsonify({"error": "read-only demo: sign in to make changes"}), 403
        # Deny-by-default authorization for writes: an authenticated non-admin
        # may reach only the explicitly-opened endpoints (USER_WRITABLE_ENDPOINTS);
        # every other mutating /api route is admin-only. Enforced centrally so it
        # covers current and future endpoints without a per-view check. (Guests
        # already returned above, so `user` is a real row here.)
        if (request.method not in ("GET", "HEAD", "OPTIONS")
                and request.endpoint not in USER_WRITABLE_ENDPOINTS
                and not user["is_admin"]):
            return jsonify({"error": "admin access required"}), 403

    @app.route("/")
    def index():
        return send_from_directory(app.static_folder, "index.html")

    @app.route("/sample-chargebacks.csv")
    def sample_csv():
        # Public, read-only download so visitors can see the import format.
        # A GET only — it grants no upload/import capability.
        return send_from_directory(
            ROOT, "chargebacks.csv", mimetype="text/csv",
            as_attachment=True, download_name="chargebacks-sample.csv")

    return app
