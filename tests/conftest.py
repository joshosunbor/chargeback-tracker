import pytest

from app import create_app


@pytest.fixture
def app(tmp_path):
    app = create_app(data_dir=tmp_path)
    # Most tests register several accounts; open signup so they can. Closed
    # signup has its own dedicated test in test_auth.py.
    app.config["ALLOW_SIGNUP"] = True
    return app


@pytest.fixture
def anon_client(app):
    """Test client with no session — for exercising the auth guard."""
    return app.test_client()


@pytest.fixture
def client(app):
    """Test client logged in as 'alice'."""
    c = app.test_client()
    res = c.post("/api/auth/register", json={"username": "alice", "password": "secret"})
    assert res.status_code == 201
    return c


@pytest.fixture
def case(client):
    """A freshly created case, returned as its JSON dict."""
    res = client.post("/api/cases", json={
        "case_number": "CB-1001",
        "merchant": "Acme Corp",
        "customer": "Jane Roe",
        "amount_cents": 4599,
        "reason_code": "10.4",
        "received_date": "2026-07-01",
        "due_date": "2026-07-30",
    })
    assert res.status_code == 201
    return res.get_json()
