#!/usr/bin/env python3
"""Admin CLI for user management — the way accounts are created once public
signup is closed (ALLOW_SIGNUP unset).

Usage:
    .venv/bin/python manage.py create-user <username> [--password PW]
    .venv/bin/python manage.py set-password <username> [--password PW]
    .venv/bin/python manage.py list-users
    .venv/bin/python manage.py import-csv <path>       # bulk-load cases

With no --password, you're prompted for one (input hidden). On a PaaS,
run this as a one-off command in the service shell after deploy to create
the first account.
"""
import argparse
import getpass
import sqlite3
import sys

from werkzeug.security import generate_password_hash

from app import create_app
from app.db import utcnow


def _connect():
    app = create_app()  # ensures the db exists and migrations are applied
    con = sqlite3.connect(app.config["DATABASE"])
    con.row_factory = sqlite3.Row
    return con


def create_user(args):
    password = args.password or getpass.getpass("Password: ")
    if len(password) < 4:
        sys.exit("error: password must be at least 4 characters")
    con = _connect()
    try:
        con.execute(
            "INSERT INTO users (username, password_hash, created_at, is_admin) VALUES (?, ?, ?, ?)",
            (args.username, generate_password_hash(password), utcnow(), 1 if args.admin else 0),
        )
        con.commit()
    except sqlite3.IntegrityError:
        sys.exit(f"error: username '{args.username}' already exists")
    finally:
        con.close()
    print(f"created {'admin' if args.admin else 'user'} '{args.username}'")


def set_password(args):
    password = args.password or getpass.getpass("New password: ")
    if len(password) < 4:
        sys.exit("error: password must be at least 4 characters")
    con = _connect()
    try:
        cur = con.execute(
            "UPDATE users SET password_hash = ? WHERE username = ?",
            (generate_password_hash(password), args.username),
        )
        con.commit()
    finally:
        con.close()
    if cur.rowcount == 0:
        sys.exit(f"error: no user named '{args.username}'")
    print(f"updated password for '{args.username}'")


def list_users(args):
    con = _connect()
    rows = con.execute(
        "SELECT id, username, created_at, is_admin FROM users ORDER BY id").fetchall()
    con.close()
    if not rows:
        print("(no users yet)")
        return
    for r in rows:
        tag = "admin" if r["is_admin"] else ""
        print(f"  {r['id']:>3}  {r['username']:<20}  {r['created_at']}  {tag}")


def import_csv(args):
    """Bulk-import cases from a CSV file, reusing the same row parsing and
    insert logic as the web importer. Skips duplicate case numbers, reports
    per-row errors, and attributes rows to an admin account if one exists."""
    import csv

    from app.api.cases import _row_to_fields, insert_case

    con = _connect()
    con.execute("PRAGMA foreign_keys = ON")
    admin = con.execute(
        "SELECT id FROM users WHERE is_admin = 1 ORDER BY id LIMIT 1").fetchone()
    user_id = admin["id"] if admin else None
    now = utcnow()

    created = skipped = 0
    errors = []
    try:
        with open(args.path, newline="", encoding="utf-8-sig") as f:
            reader = csv.DictReader(f)
            headers = {(h or "").strip().lower() for h in (reader.fieldnames or [])}
            missing = {"case_number", "merchant", "amount"} - headers
            if missing:
                sys.exit(f"error: CSV missing required column(s): {', '.join(sorted(missing))}")
            for line_no, raw in enumerate(reader, start=2):
                row = {(k or "").strip().lower(): v for k, v in raw.items()}
                try:
                    fields, status = _row_to_fields(row)
                except ValueError as e:
                    errors.append((line_no, str(e)))
                    continue
                if con.execute("SELECT 1 FROM cases WHERE case_number = ?",
                               (fields["case_number"],)).fetchone():
                    skipped += 1
                    continue
                try:
                    insert_case(con, fields, status, user_id, now, "Imported from CSV (CLI)")
                    created += 1
                except sqlite3.IntegrityError:
                    skipped += 1
        con.commit()
    except FileNotFoundError:
        sys.exit(f"error: no such file: {args.path}")
    finally:
        con.close()

    print(f"imported {created}, skipped {skipped} (duplicates), {len(errors)} error(s)")
    for line_no, msg in errors:
        print(f"  row {line_no}: {msg}")


def main():
    parser = argparse.ArgumentParser(description="Chargeback Tracker admin CLI")
    sub = parser.add_subparsers(dest="command", required=True)

    p_create = sub.add_parser("create-user", help="create a login account")
    p_create.add_argument("username")
    p_create.add_argument("--password", help="set non-interactively (else prompted)")
    p_create.add_argument("--admin", action="store_true", help="grant admin rights")
    p_create.set_defaults(func=create_user)

    p_set = sub.add_parser("set-password", help="reset an account's password")
    p_set.add_argument("username")
    p_set.add_argument("--password", help="set non-interactively (else prompted)")
    p_set.set_defaults(func=set_password)

    p_list = sub.add_parser("list-users", help="list existing accounts")
    p_list.set_defaults(func=list_users)

    p_import = sub.add_parser("import-csv", help="bulk-import cases from a CSV file")
    p_import.add_argument("path")
    p_import.set_defaults(func=import_csv)

    args = parser.parse_args()
    args.func(args)


if __name__ == "__main__":
    main()
