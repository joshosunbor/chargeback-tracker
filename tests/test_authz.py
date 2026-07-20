"""Deny-by-default authorization for mutating API endpoints.

Every mutating /api route is admin-only UNLESS its endpoint is explicitly listed
in app.USER_WRITABLE_ENDPOINTS (the contributor writes: create case, add note,
upload attachment). This locks the write matrix down so that a newly added write
endpoint is admin-only until it is deliberately opened. Guest (read-only) and
unauthenticated behaviour is covered in test_guest.py / test_auth.py.
"""
import io


def _import(c):
    return c.post(
        "/api/cases/import",
        data={"file": (io.BytesIO(b"case_number,merchant,amount\nA,B,1"), "c.csv")},
        content_type="multipart/form-data")


def _upload(c, case_id):
    return c.post(
        f"/api/cases/{case_id}/attachments",
        data={"file": (io.BytesIO(b"x"), "a.txt")},
        content_type="multipart/form-data")


# ---------- opened to any authenticated (non-admin) user ----------

def test_non_admin_can_create_note_and_attach(client, case):
    # The three contributor writes: create a case, note it, attach evidence.
    assert client.post("/api/cases", json={
        "case_number": "AUTHZ-1", "merchant": "X", "amount_cents": 1}).status_code == 201
    assert client.post(f"/api/cases/{case['id']}/notes",
                       json={"body": "hi"}).status_code == 201
    assert _upload(client, case["id"]).status_code == 201


def test_non_admin_can_download_attachment(client, case):
    # Any authenticated user may upload and read; only deleting it is admin-gated.
    att = _upload(client, case["id"]).get_json()
    assert client.get(f"/api/attachments/{att['id']}").status_code == 200


# ---------- admin-only by deny-by-default ----------

def test_non_admin_blocked_from_admin_only_writes(client, admin_client, case):
    cid = case["id"]
    # A user attaches evidence (now open to contributors), so there is an
    # attachment for the admin-only delete attempt below to target.
    att = _upload(client, cid).get_json()

    attempts = [
        client.patch(f"/api/cases/{cid}", json={"status": "won"}),   # edit case
        client.delete(f"/api/cases/{cid}"),                          # delete case
        client.delete(f"/api/attachments/{att['id']}"),             # delete attachment
        _import(client),                                             # bulk import
    ]
    assert [r.status_code for r in attempts] == [403, 403, 403, 403]
    assert attempts[0].get_json()["error"] == "admin access required"
    # None of the rejected writes took effect.
    detail = admin_client.get(f"/api/cases/{cid}").get_json()
    assert detail["status"] == "new"
    assert [a["id"] for a in detail["attachments"]] == [att["id"]]


def test_admin_can_perform_all_writes(admin_client, case):
    cid = case["id"]
    assert admin_client.patch(f"/api/cases/{cid}", json={"status": "won"}).status_code == 200
    att = _upload(admin_client, cid)
    assert att.status_code == 201
    assert admin_client.delete(
        f"/api/attachments/{att.get_json()['id']}").status_code == 204
    assert admin_client.delete(f"/api/cases/{cid}").status_code == 204


# ---------- the allowlist is the single source of truth ----------

def test_allowlist_contents_are_locked_down():
    """Guards against a future write endpoint being opened by accident: the
    allowlist must contain exactly the three deliberately-opened contributor
    endpoints."""
    from app import USER_WRITABLE_ENDPOINTS

    assert USER_WRITABLE_ENDPOINTS == frozenset({
        "cases.create_case", "notes.add_note", "attachments.upload"})
