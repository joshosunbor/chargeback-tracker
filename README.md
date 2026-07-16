# Chargeback Tracker

Small internal tool for tracking chargeback cases. Flask + SQLite backend
serving a JSON API, vanilla-JS single-page frontend. Simple username/password
login attributes every action (case creation, status changes, notes, uploads)
to a person; accounts are self-service via the login screen. Intended for an
internal network — this is attribution, not hardened security.

## Run

```sh
python3 -m venv .venv
.venv/bin/pip install -r requirements.txt
.venv/bin/python run.py
```

Open http://127.0.0.1:5000. The SQLite database and uploaded attachments live
under `data/` (gitignored, created on first start) — back up that one folder.

## Test

```sh
.venv/bin/pip install pytest
.venv/bin/python -m pytest tests/
```

## API

All `/api/*` routes except `/api/auth/*` require a logged-in session.

| Method | Path | Purpose |
|---|---|---|
| POST | `/api/auth/register` | Create account + log in (`{"username", "password"}`) |
| POST | `/api/auth/login` | Log in |
| POST | `/api/auth/logout` | Log out |
| GET | `/api/auth/me` | Current user |
| GET | `/api/cases?status=&q=` | List/filter cases |
| POST | `/api/cases` | Create case |
| GET | `/api/cases/<id>` | Case detail incl. history, notes, attachments |
| PATCH | `/api/cases/<id>` | Update fields; `status` change appends an audit row (`status_note` optional) |
| DELETE | `/api/cases/<id>` | Delete case (cascades) |
| POST | `/api/cases/<id>/notes` | Add note (`{"body": "..."}`) |
| POST | `/api/cases/<id>/attachments` | Upload file (multipart field `file`, 10 MB cap) |
| GET | `/api/attachments/<id>` | Download attachment |
| DELETE | `/api/attachments/<id>` | Remove attachment |

Amounts are integer cents (`amount_cents`). Statuses:
`new → under_review → represented → won | lost | accepted` — a case reaching a
terminal status gets `resolved_date` auto-stamped.
