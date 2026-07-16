#!/usr/bin/env python3
"""Populate the database with synthetic chargeback cases for local testing.

Re-runnable: every seeded case number is prefixed ``SEED-``, and each run first
deletes those rows (history/notes cascade) before inserting a fresh batch — so
running it repeatedly refreshes the sample data instead of piling up duplicates.
Cases created for real through the app are never touched.

The random generator is seeded with a fixed value, so the shape of the dataset
is stable across runs (only the absolute dates shift, since they're relative to
today).

Usage:
    .venv/bin/python seed.py [count]     # default 50
"""
import random
import sqlite3
import sys
from datetime import datetime, timedelta, timezone

from werkzeug.security import generate_password_hash

from app import create_app

SEED_PREFIX = "SEED-"
RANDOM_SEED = 1234

# Seed users actions are attributed to. Idempotent on username (UNIQUE).
SEED_USERS = [("alice", "password"), ("bob", "password"), ("carol", "password")]

MERCHANTS = [
    "Acme Corp", "Globex", "Initech", "Umbrella Retail", "Stark Industries",
    "Wayne Goods", "Soylent Foods", "Hooli", "Pied Piper", "Vandelay Imports",
    "Wonka Confections", "Cyberdyne Systems", "Tyrell Supply", "Gekko & Co",
    "Duff Beverages", "Oscorp", "Nakatomi Trading", "Bluth Company",
]

CUSTOMERS = [
    "Jane Roe", "John Doe", "Priya Patel", "Marcus Chen", "Sofia Alvarez",
    "Liam O'Brien", "Amara Okafor", "Noah Kim", "Emma Rossi", "Yuki Tanaka",
    "Omar Haddad", "Grace Nguyen", "Lucas Silva", "Fatima Zahra", "Ben Carter",
    None,  # some cards have no captured cardholder name
]

# (code, description) — a mix of Visa and Mastercard dispute reason codes.
REASON_CODES = [
    ("10.4", "Fraud – Card-Absent Environment"),
    ("11.3", "No Authorization"),
    ("12.5", "Incorrect Amount"),
    ("13.1", "Merchandise/Services Not Received"),
    ("13.2", "Cancelled Recurring Transaction"),
    ("13.3", "Not as Described or Defective"),
    ("13.6", "Credit Not Processed"),
    ("13.7", "Cancelled Merchandise/Services"),
    ("4853", "Cardholder Dispute (Mastercard)"),
    ("4837", "No Cardholder Authorization (Mastercard)"),
    ("4855", "Goods or Services Not Provided (Mastercard)"),
    ("4834", "Duplicate Processing (Mastercard)"),
]

CURRENCIES = ["USD"] * 6 + ["EUR", "GBP", "CAD"]

# Weighted so every status is well represented in ~50 rows.
STATUS_WEIGHTS = {
    "new": 8, "under_review": 10, "represented": 8, "won": 10, "lost": 8, "accepted": 6,
}
STATUS_PATHS = {
    "new": ["new"],
    "under_review": ["new", "under_review"],
    "represented": ["new", "under_review", "represented"],
    "won": ["new", "under_review", "represented", "won"],
    "lost": ["new", "under_review", "represented", "lost"],
    "accepted": ["new", "accepted"],
}
TRANSITION_NOTES = {
    ("new", "under_review"): "Assigned for review; gathering transaction evidence",
    ("under_review", "represented"): "Representment submitted with compelling evidence",
    ("represented", "won"): "Issuer ruled in our favor; funds recovered",
    ("represented", "lost"): "Issuer upheld the chargeback; funds forfeited",
    ("new", "accepted"): "Liability accepted; representment not pursued",
}
NOTE_TEMPLATES = [
    "Customer contacted regarding the disputed transaction.",
    "Order confirmation and shipping tracking attached to the case file.",
    "AVS and CVV both matched at authorization.",
    "Customer claims the item never arrived; carrier shows delivered.",
    "Appears to duplicate an earlier authorization that was voided.",
    "Refund had already been issued before the dispute was filed.",
    "Device fingerprint matches the cardholder's prior legitimate orders.",
]

TERMINAL = {"won", "lost", "accepted"}


def iso(dt):
    return dt.isoformat(timespec="seconds")


def ensure_users(con):
    for username, password in SEED_USERS:
        con.execute(
            "INSERT OR IGNORE INTO users (username, password_hash, created_at) VALUES (?, ?, ?)",
            (username, generate_password_hash(password), iso(datetime.now(timezone.utc))),
        )
    rows = con.execute(
        "SELECT id FROM users WHERE username IN (%s)"
        % ",".join("?" * len(SEED_USERS)),
        [u for u, _ in SEED_USERS],
    ).fetchall()
    return [r[0] for r in rows]


def weighted_status():
    statuses = list(STATUS_WEIGHTS)
    return random.choices(statuses, weights=[STATUS_WEIGHTS[s] for s in statuses])[0]


def seed(count):
    app = create_app()  # ensures the DB exists and migrations are applied
    con = sqlite3.connect(app.config["DATABASE"])
    con.execute("PRAGMA foreign_keys = ON")

    random.seed(RANDOM_SEED)
    now = datetime.now(timezone.utc)

    user_ids = ensure_users(con)

    # Wipe any previously seeded cases (cascades to history/notes/attachments).
    con.execute("DELETE FROM cases WHERE case_number LIKE ?", (SEED_PREFIX + "%",))

    status_counts = {}
    for i in range(1, count + 1):
        case_number = f"{SEED_PREFIX}{i:04d}"
        merchant = random.choice(MERCHANTS)
        customer = random.choice(CUSTOMERS)
        amount_cents = random.randint(500, 250_000)
        currency = random.choice(CURRENCIES)
        code, _desc = random.choice(REASON_CODES)
        target = weighted_status()
        path = STATUS_PATHS[target]

        # Walk the status path forward in time, starting when the dispute landed.
        received = now - timedelta(days=random.randint(5, 200), hours=random.randint(0, 23))
        due = received + timedelta(days=random.choice([21, 30, 45]))
        owner = random.choice(user_ids)

        step_time = received
        resolved_date = None
        history = []  # (old, new, note, created_at)
        for idx, status in enumerate(path):
            if idx == 0:
                history.append((None, status, "Case created", step_time))
            else:
                prev = path[idx - 1]
                step_time = min(step_time + timedelta(days=random.randint(1, 14),
                                                      hours=random.randint(0, 23)), now)
                history.append((prev, status, TRANSITION_NOTES.get((prev, status)), step_time))
                if status in TERMINAL:
                    resolved_date = step_time.date().isoformat()

        cur = con.execute(
            """INSERT INTO cases (case_number, merchant, customer, amount_cents, currency,
                                  reason_code, status, received_date, due_date, resolved_date,
                                  created_at, updated_at, created_by)
               VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
            (case_number, merchant, customer, amount_cents, currency, code, target,
             received.date().isoformat(), due.date().isoformat(), resolved_date,
             iso(received), iso(step_time), owner),
        )
        case_id = cur.lastrowid

        for old, new, note, created_at in history:
            con.execute(
                """INSERT INTO case_history (case_id, old_status, new_status, note, created_at, user_id)
                   VALUES (?, ?, ?, ?, ?, ?)""",
                (case_id, old, new, note, iso(created_at), random.choice(user_ids)),
            )

        for _ in range(random.randint(0, 3)):
            note_time = received + timedelta(days=random.randint(0, 10))
            con.execute(
                "INSERT INTO notes (case_id, body, created_at, user_id) VALUES (?, ?, ?, ?)",
                (case_id, random.choice(NOTE_TEMPLATES),
                 iso(min(note_time, now)), random.choice(user_ids)),
            )

        status_counts[target] = status_counts.get(target, 0) + 1

    con.commit()

    total = con.execute(
        "SELECT COUNT(*) FROM cases WHERE case_number LIKE ?", (SEED_PREFIX + "%",)
    ).fetchone()[0]
    con.close()

    print(f"Seeded {total} synthetic cases into {app.config['DATABASE']}")
    for status in STATUS_WEIGHTS:
        print(f"  {status:<13} {status_counts.get(status, 0)}")
    print("\nLog in with any seed user (all password 'password'): "
          + ", ".join(u for u, _ in SEED_USERS))


if __name__ == "__main__":
    n = int(sys.argv[1]) if len(sys.argv) > 1 else 50
    seed(n)
