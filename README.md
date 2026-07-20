# Chargeback Tracker

A demo app for tracking chargeback cases from first dispute through to resolution. Built as a personal project for testing product and engineering ideas, using synthetic data throughout.

**Live demo:** https://chargeback-tracker.fly.dev — click "Try the demo" for read-only guest access, no account needed.

## What it does

- Record chargeback cases with merchant, customer, amount, currency, reason code, and key dates
- Move cases through a status workflow (new → under review → represented → won / lost / accepted) with a full audit history of every change
- Bulk-import cases from CSV, with a per-row summary of what was created, skipped, or rejected
- Role-based access: admin accounts unlock privileged actions like importing; a read-only guest role powers the public demo

## Design decisions

**Locked signup, env-seeded admin.** The original design made the first registered user the admin. That's fine on localhost, where I'm the only one who can reach it. On a public URL it's a race: between the deploy finishing and me opening the site, anyone who hits it first becomes admin. So I removed the bootstrap entirely — signup starts locked, and the admin account is created at startup from ADMIN_USERNAME and ADMIN_PASSWORD_HASH environment variables. The seeding is idempotent, so redeploys don't clobber the account, and the password never exists anywhere in the repo — only its hash, only in Fly's secrets.

**Server-side read-only, not hidden buttons.** Hiding buttons is presentation, not access control. Anyone can open dev tools and call the API directly, so a demo that's only read-only in the UI isn't read-only at all. The guest role is rejected at the endpoint — any write returns 403 regardless of what the interface shows, and the tests cover it. Same principle as the admin-only import: the check lives where the data is, not where the buttons are.

**Synthetic data only.** It's a public demo. Real chargeback records carry customer names, amounts, and dispute details — data that has no business sitting in a personal side project on a public host, whatever the auth model. All 50 cases are generated: invented merchants, fake customers, realistic reason codes. That's also what makes the open read-only demo safe to leave running.