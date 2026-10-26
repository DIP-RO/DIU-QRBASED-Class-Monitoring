# Architecture and policy model

The system is a single-host application. Caddy terminates HTTPS and replaces forwarding headers; FastAPI serves the versioned API and built React bundle; a separate worker performs sync, session materialization, health and finalization work; both use one SQLite database on a local persistent volume. SQLite connections enable foreign keys, WAL, FULL synchronous durability, a five-second busy timeout and short transactions.

## State model

`SCHEDULED` sessions derive `UPCOMING`, `CHECKIN_OPEN`, `IN_PROGRESS_NO_CHECKIN` and `ENDED_NO_CHECKIN` display states from server time. An accepted write records immutable `ON_TIME` or `LATE` evidence. At end, a missing record becomes `ABSENT_NO_CHECKIN` only when schedule freshness, mapping and service health are reliable; otherwise it becomes `REVIEW_REQUIRED`. `CANCELLED` and `SUPERSEDED` are session lifecycle states and never absences. Corrections retain `original_result` and change only `effective_result` with an audit event.

Time uses UTC storage and Asia/Dhaka teaching dates. Policy versions are snapshotted by each session. Check-in matching requires the authenticated mapped teacher, active QR room, eligible session, server receive time and server-resolved allowed network.

## Module map and backlog traceability

- E01 / US01–03: `auth.py`, `security.py`, users/roles/teachers/aliases.
- E02 / US04–06: `sources.py`, source configuration, sync and routine versions. Live mode remains `UNCONNECTED` until an authorized read succeeds.
- E03 / US07–09: `services.generate_sessions`, occurrence keys and immutable snapshots.
- E04 / US10–12: room QR routes and React `Checkin` flow.
- E05 / US13–15: `policy.py`, server matching, unique attendance and idempotent attempts.
- E06 / US16–18: versioned CIDRs, trusted-proxy resolution and fail-closed checks.
- E07 / US19–21: worker, durable heartbeat, incidents and reliability-aware finalizer.
- E08 / US22–25: admin/teacher dashboards, combined filters and formula-safe CSV.
- E09 / US26–28: correction requests, effective results and append-only application audit.
- E10 / US29–31: SQLite settings, backup script, migrations, containers and operations guide.
- E11 and E12 are explicitly deferred P1 enhancements: rotating display QR and separately specified checkout/duration monitoring.

The live Firestore adapter is read-only. It accepts an owner-provisioned access token through the environment and does not claim delegated renewal without an approved credential mechanism. CSV and clearly labeled demo operation remain usable when live access is unavailable.

