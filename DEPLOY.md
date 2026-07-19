# Deploying to Fly.io

The app is containerized (`Dockerfile`) and configured for Fly (`fly.toml`).
It runs under gunicorn, stores its SQLite database and uploaded attachments on
a persistent Fly **volume** mounted at `/data`, and serves over HTTPS.

## One-time setup

1. **Install flyctl and log in** (do this yourself in a terminal):
   ```sh
   brew install flyctl
   fly auth login
   ```

2. **Create the app** (registers the name; skips deploying yet):
   ```sh
   fly launch --no-deploy --copy-config --name chargeback-tracker
   ```
   If `chargeback-tracker` is taken, pick another name — it updates `fly.toml`.

3. **Create the persistent volume** (SQLite db + uploads live here). Match the
   region in `fly.toml` (`iad`):
   ```sh
   fly volumes create data --region iad --size 1   # 1 GB
   ```

4. **Set the session secret** (required — without a stable key, every deploy
   logs everyone out):
   ```sh
   fly secrets set SECRET_KEY=$(python3 -c "import secrets; print(secrets.token_hex(32))")
   ```

5. **Seed the admin account.** Signup is closed with no first-user bootstrap,
   so the admin is provisioned from env vars — a username and a password
   **hash** (never a plaintext password). Generate the hash locally, then set
   both as secrets. **Single-quote the hash** — it contains `$` and `:`:
   ```sh
   # 1. Generate a hash from your chosen password (uses werkzeug from the venv):
   .venv/bin/python -c "from werkzeug.security import generate_password_hash as g; print(g('CHOOSE_A_STRONG_PASSWORD'))"
   # -> prints something like: scrypt:32768:8:1$Xbg...$9f2...

   # 2. Set the admin username + that hash as Fly secrets:
   fly secrets set ADMIN_USERNAME=admin ADMIN_PASSWORD_HASH='scrypt:32768:8:1$Xbg...$9f2...'
   ```
   On the next boot the app seeds this admin if it doesn't already exist. Then
   log in at the site with that username and the password you chose.

## Deploy

```sh
fly deploy
```

Then open the app and log in as the seeded admin:

```sh
fly open
```

## Managing users

Signup stays **closed** (`ALLOW_SIGNUP` unset). To add more users, either:

- Create them from the server shell:
  ```sh
  fly ssh console -C "python manage.py create-user <username>"
  ```
- Or temporarily open signup: `fly secrets set ALLOW_SIGNUP=true`, register in
  the UI, then `fly secrets unset ALLOW_SIGNUP`.

To **rotate the admin password**:
```sh
fly ssh console -C "python manage.py set-password admin --password 'NEW_PASSWORD'"
```
The `ADMIN_PASSWORD_HASH` secret only seeds a *missing* account; it won't
overwrite an existing one on redeploy.

## Notes & caveats

- **Single instance only.** A Fly volume attaches to one machine, and SQLite
  can't be shared across instances. Keep `min_machines_running = 1` and do not
  `fly scale count` above 1. If you outgrow one instance, migrate to Postgres.
- **Backups.** Everything durable is under `/data`. Snapshot the volume
  (`fly volumes snapshots list <vol-id>`) or copy the files out periodically.
- **Config via env** (all optional except `SECRET_KEY` in production):
  | Var | Purpose | Prod value |
  |---|---|---|
  | `SECRET_KEY` | Session signing key | set via `fly secrets` |
  | `DATA_DIR` | Where db + uploads live | `/data` (in `fly.toml`) |
  | `SESSION_COOKIE_SECURE` | HTTPS-only cookie | `true` (in `fly.toml`) |
  | `ALLOW_SIGNUP` | Open public registration | unset (closed) |

## Local development is unchanged

None of the above affects local use. With no env vars set, `python run.py`
still serves on http://127.0.0.1:5000 with a file-based secret key under
`data/`, an insecure cookie (fine for http), and closed signup (the first
account bootstraps, as above).
