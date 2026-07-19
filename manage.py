#!/usr/bin/env python3
"""Admin CLI for user management — the way accounts are created once public
signup is closed (ALLOW_SIGNUP unset).

Usage:
    .venv/bin/python manage.py create-user <username> [--password PW]
    .venv/bin/python manage.py set-password <username> [--password PW]
    .venv/bin/python manage.py list-users

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
            "INSERT INTO users (username, password_hash, created_at) VALUES (?, ?, ?)",
            (args.username, generate_password_hash(password), utcnow()),
        )
        con.commit()
    except sqlite3.IntegrityError:
        sys.exit(f"error: username '{args.username}' already exists")
    finally:
        con.close()
    print(f"created user '{args.username}'")


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
    rows = con.execute("SELECT id, username, created_at FROM users ORDER BY id").fetchall()
    con.close()
    if not rows:
        print("(no users yet)")
        return
    for r in rows:
        print(f"  {r['id']:>3}  {r['username']:<20}  {r['created_at']}")


def main():
    parser = argparse.ArgumentParser(description="Chargeback Tracker admin CLI")
    sub = parser.add_subparsers(dest="command", required=True)

    p_create = sub.add_parser("create-user", help="create a login account")
    p_create.add_argument("username")
    p_create.add_argument("--password", help="set non-interactively (else prompted)")
    p_create.set_defaults(func=create_user)

    p_set = sub.add_parser("set-password", help="reset an account's password")
    p_set.add_argument("username")
    p_set.add_argument("--password", help="set non-interactively (else prompted)")
    p_set.set_defaults(func=set_password)

    p_list = sub.add_parser("list-users", help="list existing accounts")
    p_list.set_defaults(func=list_users)

    args = parser.parse_args()
    args.func(args)


if __name__ == "__main__":
    main()
