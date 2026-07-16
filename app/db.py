import sqlite3
from datetime import datetime, timezone
from pathlib import Path

from flask import current_app, g


def utcnow():
    """ISO-8601 UTC timestamp used for all created_at/updated_at columns."""
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


def get_db():
    if "db" not in g:
        g.db = sqlite3.connect(current_app.config["DATABASE"])
        g.db.row_factory = sqlite3.Row
        g.db.execute("PRAGMA foreign_keys = ON")
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
    con = sqlite3.connect(app.config["DATABASE"])
    con.execute("PRAGMA journal_mode = WAL")
    con.executescript(schema)
    for table, columns in _COLUMN_MIGRATIONS.items():
        existing = {row[1] for row in con.execute(f"PRAGMA table_info({table})")}
        for name, decl in columns.items():
            if name not in existing:
                con.execute(f"ALTER TABLE {table} ADD COLUMN {name} {decl}")
    con.commit()
    con.close()


def init_app(app):
    app.teardown_appcontext(close_db)
    init_db(app)
