import io


def test_guest_session_reports_read_only(guest_client):
    me = guest_client.get("/api/auth/me")
    assert me.status_code == 200
    body = me.get_json()
    assert body["is_guest"] is True
    assert body["is_admin"] is False
    assert body["username"] == "guest"


def test_guest_can_read_cases_and_detail(guest_client, case):
    assert guest_client.get("/api/cases").status_code == 200
    detail = guest_client.get(f"/api/cases/{case['id']}")
    assert detail.status_code == 200
    assert detail.get_json()["case_number"] == case["case_number"]


def test_guest_write_endpoints_all_return_403(guest_client, case):
    """Every mutating endpoint is rejected server-side for a guest — even when
    called directly against the API, not just hidden in the UI."""
    cid = case["id"]
    attempts = [
        guest_client.post("/api/cases", json={
            "case_number": "GUEST-1", "merchant": "X", "amount_cents": 100}),
        guest_client.patch(f"/api/cases/{cid}", json={"status": "won"}),
        guest_client.delete(f"/api/cases/{cid}"),
        guest_client.post(f"/api/cases/{cid}/notes", json={"body": "hi"}),
        guest_client.post(f"/api/cases/{cid}/attachments",
                          data={"file": (io.BytesIO(b"x"), "a.txt")},
                          content_type="multipart/form-data"),
        guest_client.post("/api/cases/import",
                          data={"file": (io.BytesIO(b"case_number,merchant,amount\nA,B,1"), "c.csv")},
                          content_type="multipart/form-data"),
    ]
    assert [r.status_code for r in attempts] == [403, 403, 403, 403, 403, 403]


def test_guest_writes_do_not_change_data(guest_client, case):
    """Belt-and-suspenders: after rejected writes, the data is untouched."""
    cid = case["id"]
    guest_client.patch(f"/api/cases/{cid}", json={"status": "won"})
    guest_client.post(f"/api/cases/{cid}/notes", json={"body": "sneaky"})
    guest_client.delete(f"/api/cases/{cid}")

    detail = guest_client.get(f"/api/cases/{cid}").get_json()
    assert detail["status"] == "new"          # PATCH was rejected
    assert detail["notes"] == []              # note was rejected
    assert len(guest_client.get("/api/cases").get_json()) == 1  # DELETE was rejected


def test_guest_cannot_delete_attachment_but_can_download(client, guest_client, case):
    # A real user uploads evidence...
    att = client.post(f"/api/cases/{case['id']}/attachments",
                      data={"file": (io.BytesIO(b"evidence"), "e.txt")},
                      content_type="multipart/form-data").get_json()
    # ...the guest can read/download it, but cannot delete it.
    assert guest_client.get(f"/api/attachments/{att['id']}").status_code == 200
    assert guest_client.delete(f"/api/attachments/{att['id']}").status_code == 403


def test_guest_logout_ends_session(guest_client):
    assert guest_client.post("/api/auth/logout").status_code == 204
    # After exiting the demo, the API requires auth again.
    assert guest_client.get("/api/cases").status_code == 401


def test_guest_mode_does_not_open_signup(tmp_path):
    # The demo must not be a backdoor to account creation. Use a fresh app with
    # the production default (signup closed) rather than the test fixture that
    # forces signup open.
    from app import create_app

    c = create_app(data_dir=tmp_path).test_client()
    assert c.post("/api/auth/guest").status_code == 200
    assert c.get("/api/auth/config").get_json()["signup_open"] is False
    assert c.post("/api/auth/register",
                  json={"username": "sneak", "password": "secret"}).status_code == 403
