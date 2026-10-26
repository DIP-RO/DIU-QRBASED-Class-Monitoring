# DIU QR Class Monitoring System

A production-oriented single-host P0 implementation for teacher class check-in: FastAPI, SQLAlchemy/Alembic, SQLite, React/TypeScript, room QR codes, campus-network enforcement, a durable worker, reports, corrections and audit.

## Local run

```bash
python3 -m venv .venv
.venv/bin/pip install -e '.[test]'
cp .env.example .env
.venv/bin/alembic upgrade head
.venv/bin/python -m backend.worker
cd frontend && npm install && npm run build && cd ..
.venv/bin/uvicorn backend.main:app --reload
```

The first real administrator is created through the verified Google identity configured by `BOOTSTRAP_ADMIN_EMAIL`. Production rejects development authentication. Import an authorized timetable CSV or connect the approved read-only live source before generating class sessions. API documentation is at `/api/docs`.

## Universal QR lifecycle

Generate and print one universal QR code for the system. The same code works for every classroom and teacher: institutional identity, the current server time and the active routine dynamically resolve the eligible subject and room. Creating or refreshing class sessions does not generate a new QR. Use **Replace compromised QR** only when necessary because replacement immediately invalidates the previous universal code. Campus-network enforcement remains active, but global QR mode does not independently prove physical presence in a particular room.

Run verification with `.venv/bin/pytest`, `cd frontend && npm run build`, and `.venv/bin/python scripts/load_test.py`. Run `python scripts/backup.py source.db restored.db` to exercise SQLite's online backup API and integrity check.

See [architecture](docs/ARCHITECTURE.md), [administrator guide](docs/ADMIN_GUIDE.md), and [integration setup](docs/INTEGRATION.md). Deployment-specific OIDC credentials, administrator identity, campus CIDRs, trusted proxies, HTTPS hostname and routine-source authorization are intentionally not invented. Live source status remains unconnected until verified.
