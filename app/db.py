import os
import sqlite3
from datetime import datetime, timezone
from pathlib import Path

from flask import current_app, g


def utcnow():
    """ISO-8601 UTC timestamp used for all created_at/updated_at columns."""
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


def get_db():
    if "db" not in g:
        # busy timeout lets concurrent gunicorn workers wait out a brief write
        # lock instead of erroring immediately with "database is locked".
        g.db = sqlite3.connect(current_app.config["DATABASE"], timeout=5.0)
        g.db.row_factory = sqlite3.Row
        g.db.execute("PRAGMA foreign_keys = ON")
        g.db.execute("PRAGMA busy_timeout = 5000")
    return g.db


def close_db(e=None):
    db = g.pop("db", None)
    if db is not None:
        db.close()


# Columns added after the initial release. CREATE TABLE IF NOT EXISTS won't
# touch existing tables, so databases created before these columns existed
# get them via ALTER TABLE here.
_COLUMN_MIGRATIONS = {
    "cases": {"created_by": "INTEGER REFERENCES users(id)"},
    "case_history": {"user_id": "INTEGER REFERENCES users(id)"},
    "notes": {"user_id": "INTEGER REFERENCES users(id)"},
    "attachments": {"user_id": "INTEGER REFERENCES users(id)"},
}


def init_db(app):
    schema = (Path(__file__).parent / "schema.sql").read_text()
    con = sqlite3.connect(app.config["DATABASE"], timeout=5.0)
    con.execute("PRAGMA busy_timeout = 5000")
    # WAL mode is persisted in the database file, so only switch when needed.
    # Switching requires an exclusive lock; skipping the no-op switch avoids
    # racing another process that already set it. Run gunicorn with --preload
    # so this initialization happens once in the master, not per worker.
    if con.execute("PRAGMA journal_mode").fetchone()[0].lower() != "wal":
        con.execute("PRAGMA journal_mode = WAL")
    con.executescript(schema)
    for table, columns in _COLUMN_MIGRATIONS.items():
        existing = {row[1] for row in con.execute(f"PRAGMA table_info({table})")}
        for name, decl in columns.items():
            if name not in existing:
                con.execute(f"ALTER TABLE {table} ADD COLUMN {name} {decl}")
    con.commit()
    con.close()


def seed_admin_from_env(app):
    """Create the admin account from ADMIN_USERNAME + ADMIN_PASSWORD_HASH if set.

    ADMIN_PASSWORD_HASH must be a werkzeug password *hash*, not a plaintext
    password — generate it with:
        python -c "from werkzeug.security import generate_password_hash as g; print(g('YOUR_PASSWORD'))"

    Idempotent: only inserts when the username is absent, so redeploys don't
    clobber the account. To rotate the password later, use manage.py.
    """
    username = os.environ.get("ADMIN_USERNAME")
    password_hash = os.environ.get("ADMIN_PASSWORD_HASH")
    if not username or not password_hash:
        return
    con = sqlite3.connect(app.config["DATABASE"], timeout=5.0)
    con.execute("PRAGMA busy_timeout = 5000")
    try:
        exists = con.execute(
            "SELECT 1 FROM users WHERE username = ?", (username,)).fetchone()
        if not exists:
            con.execute(
                "INSERT INTO users (username, password_hash, created_at) VALUES (?, ?, ?)",
                (username, password_hash, utcnow()),
            )
            con.commit()
            app.logger.info("Seeded admin user %r from environment", username)
    finally:
        con.close()


def init_app(app):
    app.teardown_appcontext(close_db)
    init_db(app)
    seed_admin_from_env(app)
