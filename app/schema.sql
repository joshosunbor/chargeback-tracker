CREATE TABLE IF NOT EXISTS users (
    id            INTEGER PRIMARY KEY AUTOINCREMENT,
    username      TEXT NOT NULL UNIQUE,
    password_hash TEXT NOT NULL,
    created_at    TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS cases (
    id            INTEGER PRIMARY KEY AUTOINCREMENT,
    case_number   TEXT NOT NULL UNIQUE,
    merchant      TEXT NOT NULL,
    customer      TEXT,
    amount_cents  INTEGER NOT NULL,
    currency      TEXT NOT NULL DEFAULT 'USD',
    reason_code   TEXT,
    status        TEXT NOT NULL DEFAULT 'new',
    received_date TEXT,
    due_date      TEXT,
    resolved_date TEXT,
    created_at    TEXT NOT NULL,
    updated_at    TEXT NOT NULL,
    created_by    INTEGER REFERENCES users(id)
);

CREATE TABLE IF NOT EXISTS case_history (
    id         INTEGER PRIMARY KEY AUTOINCREMENT,
    case_id    INTEGER NOT NULL REFERENCES cases(id) ON DELETE CASCADE,
    old_status TEXT,
    new_status TEXT NOT NULL,
    note       TEXT,
    created_at TEXT NOT NULL,
    user_id    INTEGER REFERENCES users(id)
);

CREATE TABLE IF NOT EXISTS notes (
    id         INTEGER PRIMARY KEY AUTOINCREMENT,
    case_id    INTEGER NOT NULL REFERENCES cases(id) ON DELETE CASCADE,
    body       TEXT NOT NULL,
    created_at TEXT NOT NULL,
    user_id    INTEGER REFERENCES users(id)
);

CREATE TABLE IF NOT EXISTS attachments (
    id           INTEGER PRIMARY KEY AUTOINCREMENT,
    case_id      INTEGER NOT NULL REFERENCES cases(id) ON DELETE CASCADE,
    filename     TEXT NOT NULL,
    stored_name  TEXT NOT NULL UNIQUE,
    content_type TEXT,
    size_bytes   INTEGER NOT NULL,
    created_at   TEXT NOT NULL,
    user_id      INTEGER REFERENCES users(id)
);

CREATE INDEX IF NOT EXISTS idx_history_case ON case_history(case_id);
CREATE INDEX IF NOT EXISTS idx_notes_case ON notes(case_id);
CREATE INDEX IF NOT EXISTS idx_attachments_case ON attachments(case_id);
CREATE INDEX IF NOT EXISTS idx_cases_status ON cases(status);
