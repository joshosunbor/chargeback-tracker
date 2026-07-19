import io
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent


def _upload(client, csv_text, filename="import.csv"):
    return client.post(
        "/api/cases/import",
        data={"file": (io.BytesIO(csv_text.encode("utf-8")), filename)},
        content_type="multipart/form-data",
    )


HEADER = "case_number,merchant,customer,amount,currency,reason_code,status,received_date,due_date,resolved_date"


def test_import_creates_cases(client):
    csv_text = "\n".join([
        HEADER,
        "CB-100,Acme,Jane Roe,45.99,USD,10.4,new,2026-07-01,2026-07-30,",
        "CB-101,Globex,,1234.50,EUR,13.1,won,2026-05-01,2026-06-01,2026-06-15",
    ])
    res = _upload(client, csv_text)
    assert res.status_code == 200
    body = res.get_json()
    assert (body["created"], body["skipped"], body["errors"]) == (2, 0, [])

    # Dollars are converted to integer cents.
    cases = {c["case_number"]: c for c in client.get("/api/cases").get_json()}
    assert cases["CB-100"]["amount_cents"] == 4599
    assert cases["CB-101"]["amount_cents"] == 123450
    assert cases["CB-101"]["currency"] == "EUR"
    assert cases["CB-101"]["resolved_date"] == "2026-06-15"
    assert cases["CB-100"]["customer"] == "Jane Roe"
    assert cases["CB-101"]["customer"] is None  # blank -> NULL

    # Imported cases get an attributed history row.
    detail = client.get(f"/api/cases/{cases['CB-100']['id']}").get_json()
    assert detail["history"][0]["new_status"] == "new"
    assert detail["history"][0]["note"] == "Imported from CSV"
    assert detail["history"][0]["username"] == "alice"


def test_import_skips_duplicates(client):
    csv_text = f"{HEADER}\nCB-200,Acme,,10.00,USD,10.4,new,,,"
    assert _upload(client, csv_text).get_json()["created"] == 1
    # Re-importing the same case number skips rather than erroring.
    body = _upload(client, csv_text).get_json()
    assert (body["created"], body["skipped"]) == (0, 1)


def test_import_reports_row_errors_without_aborting(client):
    csv_text = "\n".join([
        HEADER,
        "CB-300,Acme,,10.00,USD,10.4,new,,,",           # ok
        "CB-301,,,10.00,USD,10.4,new,,,",               # missing merchant
        "CB-302,Acme,,not-a-number,USD,10.4,new,,,",    # bad amount
        "CB-303,Acme,,10.00,USD,10.4,bogus,,,",         # bad status
    ])
    body = _upload(client, csv_text).get_json()
    assert body["created"] == 1
    assert {e["row"] for e in body["errors"]} == {3, 4, 5}  # header is row 1
    msgs = " ".join(e["error"] for e in body["errors"])
    assert "merchant" in msgs and "amount" in msgs and "status" in msgs
    # The one valid row still landed.
    assert [c["case_number"] for c in client.get("/api/cases").get_json()] == ["CB-300"]


def test_import_rejects_missing_required_column(client):
    csv_text = "case_number,merchant\nCB-1,Acme"  # no amount column
    res = _upload(client, csv_text)
    assert res.status_code == 400
    assert "amount" in res.get_json()["error"]


def test_import_requires_login(anon_client):
    assert _upload(anon_client, f"{HEADER}\nCB-1,Acme,,1.00,USD,,,,,").status_code == 401


def test_import_sample_file(client):
    """The generated chargebacks.csv imports cleanly."""
    csv_text = (REPO_ROOT / "chargebacks.csv").read_text()
    body = _upload(client, csv_text, filename="chargebacks.csv").get_json()
    assert body["created"] == 50
    assert body["skipped"] == 0
    assert body["errors"] == []
    # Spot-check that all statuses show up and amounts converted sanely.
    cases = client.get("/api/cases").get_json()
    assert len(cases) == 50
    assert {c["status"] for c in cases} <= {
        "new", "under_review", "represented", "won", "lost", "accepted"}
    assert all(isinstance(c["amount_cents"], int) and c["amount_cents"] > 0 for c in cases)
