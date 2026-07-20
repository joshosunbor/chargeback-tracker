from werkzeug.security import generate_password_hash

from app import create_app


def test_api_requires_login(anon_client):
    assert anon_client.get("/api/cases").status_code == 401
    assert anon_client.post("/api/cases", json={}).status_code == 401


def test_signup_closed_by_default(tmp_path):
    """Production default: signup is closed with no first-user bootstrap, so a
    public URL can't be hijacked by whoever registers first."""
    app = create_app(data_dir=tmp_path)  # ALLOW_SIGNUP defaults False
    c = app.test_client()

    assert c.get("/api/auth/config").get_json()["signup_open"] is False
    res = c.post("/api/auth/register", json={"username": "whoever", "password": "secret"})
    assert res.status_code == 403


def test_admin_seeded_from_env(tmp_path, monkeypatch):
    """The admin is provisioned from env vars (username + password hash), can
    log in, and re-seeding on a later boot is idempotent."""
    monkeypatch.setenv("ADMIN_USERNAME", "root")
    monkeypatch.setenv("ADMIN_PASSWORD_HASH", generate_password_hash("hunter2"))

    app = create_app(data_dir=tmp_path)
    c = app.test_client()
    login = c.post("/api/auth/login", json={"username": "root", "password": "hunter2"})
    assert login.status_code == 200
    assert login.get_json()["is_admin"] is True  # the seeded admin is an admin
    assert c.post("/api/auth/login",
                  json={"username": "root", "password": "wrong"}).status_code == 401
    assert c.get("/api/auth/config").get_json()["signup_open"] is False

    # Rebuilding the app (e.g. a redeploy) must not duplicate or error.
    c2 = create_app(data_dir=tmp_path).test_client()
    assert c2.post("/api/auth/login",
                   json={"username": "root", "password": "hunter2"}).status_code == 200


def test_register_logs_in(client):
    me = client.get("/api/auth/me")
    assert me.status_code == 200
    assert me.get_json()["username"] == "alice"
    assert me.get_json()["is_admin"] is False  # registered users are not admins


def test_register_validates(anon_client):
    assert anon_client.post("/api/auth/register", json={"password": "secret"}).status_code == 400
    assert anon_client.post("/api/auth/register",
                            json={"username": "bob", "password": "abc"}).status_code == 400


def test_duplicate_username_conflicts(client, anon_client):
    res = anon_client.post("/api/auth/register", json={"username": "alice", "password": "other"})
    assert res.status_code == 409


def test_login_logout_cycle(client, anon_client):
    assert anon_client.post("/api/auth/login",
                            json={"username": "alice", "password": "wrong"}).status_code == 401

    res = anon_client.post("/api/auth/login", json={"username": "alice", "password": "secret"})
    assert res.status_code == 200
    assert anon_client.get("/api/cases").status_code == 200

    assert anon_client.post("/api/auth/logout").status_code == 204
    assert anon_client.get("/api/cases").status_code == 401


def test_actions_are_attributed(client, admin_client, case):
    # Case created by alice (non-admin); the admin-only status change is driven
    # by the admin; the note is added by alice. Each action is attributed to its
    # actor.
    admin_client.patch(f"/api/cases/{case['id']}", json={"status": "under_review"})
    note = client.post(f"/api/cases/{case['id']}/notes", json={"body": "checking"}).get_json()
    assert note["username"] == "alice"

    detail = client.get(f"/api/cases/{case['id']}").get_json()
    assert detail["created_by_username"] == "alice"
    assert [h["username"] for h in detail["history"]] == ["alice", "admin"]


def test_migration_adds_columns_to_existing_db(tmp_path):
    """A pre-auth database gains the attribution columns on next startup."""
    import sqlite3

    from app import create_app

    db_path = tmp_path / "app.db"
    con = sqlite3.connect(db_path)
    con.execute("""CREATE TABLE cases (
        id INTEGER PRIMARY KEY AUTOINCREMENT, case_number TEXT NOT NULL UNIQUE,
        merchant TEXT NOT NULL, customer TEXT, amount_cents INTEGER NOT NULL,
        currency TEXT NOT NULL DEFAULT 'USD', reason_code TEXT,
        status TEXT NOT NULL DEFAULT 'new', received_date TEXT, due_date TEXT,
        resolved_date TEXT, created_at TEXT NOT NULL, updated_at TEXT NOT NULL)""")
    con.execute("""INSERT INTO cases (case_number, merchant, amount_cents, created_at, updated_at)
                   VALUES ('CB-OLD', 'Legacy Inc', 100, '2026-01-01', '2026-01-01')""")
    con.commit()
    con.close()

    app = create_app(data_dir=tmp_path)
    app.config["ALLOW_SIGNUP"] = True  # need an account to read the API
    c = app.test_client()
    c.post("/api/auth/register", json={"username": "bob", "password": "secret"})
    cases = c.get("/api/cases").get_json()
    assert [x["case_number"] for x in cases] == ["CB-OLD"]
    assert cases[0]["created_by"] is None  # pre-auth rows stay unattributed
