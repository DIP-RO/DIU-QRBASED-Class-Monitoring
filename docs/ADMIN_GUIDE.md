# Administrator guide

## First deployment

1. Copy `.env.example` to `.env`. Set a random session secret, HTTPS hostname, Google OIDC client values, approved institutional domains and a bootstrap administrator email.
2. Obtain actual campus IPv4/IPv6 egress CIDRs and trusted reverse-proxy CIDRs from campus IT. Never substitute private ranges as proof of DIU connectivity.
3. Set `ENVIRONMENT=production`, `DEV_AUTH_ENABLED=false`, and `COOKIE_SECURE=true`.
4. Run `docker compose run --rm app alembic upgrade head`, then `docker compose up -d`.
5. Bootstrap the first administrator through a controlled database/operator procedure, then manage later roles through an existing authorized administrator.

Set `BOOTSTRAP_ADMIN_EMAIL` to the exact verified institutional email of the first system administrator. If no system administrator exists, that identity is created during its first successful Google OIDC callback and the action is audited. The bootstrap setting cannot create a second administrator; all later role grants must be performed by an existing authorized administrator.

The edge must be the only path to port 8000 and must replace untrusted forwarded headers. Keep the SQLite volume on local disk. Teachers require outbound access to Google sign-in; the worker requires authorized Firestore access only when live sync is configured.

## Routine and QR operations

Use CSV mode until a real authorized Firestore read succeeds. Invalid rows must be corrected from the import report; do not guess aliases or time values. Confirm source freshness before relying on automated absence. The same initials may belong to different departments; ambiguity inside one department requires resolution.

Rotate each room QR from the room administration endpoint, download SVG for printing or PNG for ordinary use, and invalidate the old token. A printed QR can be photographed and shared; the campus-network rule is supporting evidence, not proof of physical presence.

## Daily review

Watch source and worker health next to dashboard counts. Combine teacher/initials, date, room, course and result filters, then export the exact scoped result. `REVIEW_REQUIRED` is uncertainty, not absence. Correction actions need a reason and retain the original result.

## Backup, restore and lockout recovery

Create a consistent online backup with `python scripts/backup.py data/diu_monitor.db backups/diu-YYYYMMDD.db`. Restore only during a maintenance window to a new path, run `PRAGMA integrity_check`, compare critical record counts, apply `alembic upgrade head`, then change the configured database path. Do not copy only the main database file during active WAL writes.

For network-policy lockout, stop public attendance traffic, use console access on the host, back up the database, insert a corrected versioned policy with an identified administrator actor, record an audit event, test the detected edge address, and restart. Never expose an unauthenticated bypass.
