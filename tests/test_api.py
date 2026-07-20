import io


# ---------- cases ----------

def test_create_and_get_case(client, case):
    assert case["case_number"] == "CB-1001"
    assert case["status"] == "new"
    assert case["currency"] == "USD"

    res = client.get(f"/api/cases/{case['id']}")
    assert res.status_code == 200
    detail = res.get_json()
    assert detail["merchant"] == "Acme Corp"
    # Creation writes an initial history row
    assert len(detail["history"]) == 1
    assert detail["history"][0]["new_status"] == "new"
    assert detail["history"][0]["old_status"] is None


def test_create_requires_fields(client):
    res = client.post("/api/cases", json={"merchant": "Acme"})
    assert res.status_code == 400
    assert "case_number" in res.get_json()["error"]


def test_create_rejects_non_integer_amount(client):
    res = client.post("/api/cases", json={
        "case_number": "CB-X", "merchant": "Acme", "amount_cents": 45.99,
    })
    assert res.status_code == 400
    assert "amount_cents" in res.get_json()["error"]


def test_duplicate_case_number_conflicts(client, case):
    res = client.post("/api/cases", json={
        "case_number": "CB-1001", "merchant": "Other", "amount_cents": 100,
    })
    assert res.status_code == 409


def test_list_and_filter(client, admin_client, case):
    client.post("/api/cases", json={
        "case_number": "CB-1002", "merchant": "Globex", "amount_cents": 100,
    })

    assert len(client.get("/api/cases").get_json()) == 2
    assert len(client.get("/api/cases?q=Globex").get_json()) == 1
    assert len(client.get("/api/cases?q=nomatch").get_json()) == 0

    admin_client.patch(f"/api/cases/{case['id']}", json={"status": "won"})
    won = client.get("/api/cases?status=won").get_json()
    assert [c["case_number"] for c in won] == ["CB-1001"]


def test_status_change_writes_history_and_resolves(client, admin_client, case):
    res = admin_client.patch(f"/api/cases/{case['id']}", json={
        "status": "under_review", "status_note": "Gathering evidence",
    })
    assert res.status_code == 200

    res = admin_client.patch(f"/api/cases/{case['id']}", json={"status": "won"})
    updated = res.get_json()
    assert updated["status"] == "won"
    assert updated["resolved_date"]  # auto-stamped on terminal status

    history = client.get(f"/api/cases/{case['id']}").get_json()["history"]
    assert [h["new_status"] for h in history] == ["new", "under_review", "won"]
    assert history[1]["note"] == "Gathering evidence"


def test_invalid_status_rejected(admin_client, case):
    res = admin_client.patch(f"/api/cases/{case['id']}", json={"status": "bogus"})
    assert res.status_code == 400


def test_same_status_is_noop(admin_client, case):
    res = admin_client.patch(f"/api/cases/{case['id']}", json={"status": "new"})
    assert res.status_code == 200
    assert len(admin_client.get(f"/api/cases/{case['id']}").get_json()["history"]) == 1


def test_delete_cascades(client, admin_client, case):
    client.post(f"/api/cases/{case['id']}/notes", json={"body": "note"})
    assert admin_client.delete(f"/api/cases/{case['id']}").status_code == 204
    assert client.get(f"/api/cases/{case['id']}").status_code == 404


def test_missing_case_404s(admin_client):
    # 404 (not 403) requires reaching the view, so use an admin for the
    # admin-only PATCH/DELETE routes.
    assert admin_client.get("/api/cases/999").status_code == 404
    assert admin_client.patch("/api/cases/999", json={"status": "won"}).status_code == 404
    assert admin_client.delete("/api/cases/999").status_code == 404


# ---------- notes ----------

def test_add_note(client, case):
    res = client.post(f"/api/cases/{case['id']}/notes", json={"body": "Called the bank"})
    assert res.status_code == 201
    notes = client.get(f"/api/cases/{case['id']}").get_json()["notes"]
    assert [n["body"] for n in notes] == ["Called the bank"]


def test_empty_note_rejected(client, case):
    res = client.post(f"/api/cases/{case['id']}/notes", json={"body": "  "})
    assert res.status_code == 400


# ---------- attachments ----------

def upload(client, case_id, filename="receipt.pdf", content=b"%PDF-1.4 fake"):
    return client.post(
        f"/api/cases/{case_id}/attachments",
        data={"file": (io.BytesIO(content), filename)},
        content_type="multipart/form-data",
    )


def test_upload_download_roundtrip(client, case):
    res = upload(client, case["id"])  # attach is open to any authenticated user
    assert res.status_code == 201
    att = res.get_json()
    assert att["filename"] == "receipt.pdf"
    assert att["size_bytes"] == len(b"%PDF-1.4 fake")
    assert "stored_name" not in att  # internal detail not exposed

    # Download stays open to any authenticated user.
    res = client.get(f"/api/attachments/{att['id']}")
    assert res.status_code == 200
    assert res.data == b"%PDF-1.4 fake"
    assert "receipt.pdf" in res.headers["Content-Disposition"]


def test_upload_sanitizes_filename(client, case):
    res = upload(client, case["id"], filename="../../etc/passwd")
    assert res.status_code == 201
    assert "/" not in res.get_json()["filename"]
    assert ".." not in res.get_json()["filename"]


def test_upload_requires_file(client, case):
    res = client.post(f"/api/cases/{case['id']}/attachments", data={},
                      content_type="multipart/form-data")
    assert res.status_code == 400


def test_delete_attachment(client, admin_client, case, app):
    # A user attaches evidence (contribute); an admin deletes it (destroy).
    att = upload(client, case["id"]).get_json()
    assert admin_client.delete(f"/api/attachments/{att['id']}").status_code == 204
    assert admin_client.get(f"/api/attachments/{att['id']}").status_code == 404
    # File is gone from disk too
    from pathlib import Path
    assert list(Path(app.config["ATTACHMENTS_DIR"]).iterdir()) == []
