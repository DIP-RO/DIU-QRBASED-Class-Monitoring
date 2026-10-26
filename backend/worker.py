import time
from datetime import datetime, timezone
from sqlalchemy import select
from backend.database import SessionLocal
from backend.models import JobState
from backend.services import DHAKA, finalize_absences, generate_sessions

def tick():
    now=datetime.now(timezone.utc)
    with SessionLocal() as db:
        state=db.get(JobState,"main") or JobState(name="main",status="STARTING")
        db.add(state); state.heartbeat_at=now; state.last_started_at=now; state.status="RUNNING"; db.commit()
        try:
            generate_sessions(db,now.astimezone(DHAKA).date(),14); result=finalize_absences(db,now)
            state=db.get(JobState,"main"); state.last_completed_at=datetime.now(timezone.utc); state.heartbeat_at=state.last_completed_at; state.status="HEALTHY"; state.detail=str(result); db.commit()
        except Exception as exc:
            db.rollback(); state=db.get(JobState,"main"); state.status="FAILED"; state.detail=str(exc)[:500]; state.heartbeat_at=datetime.now(timezone.utc); db.commit(); raise

def main():
    while True:
        try: tick()
        except Exception: pass
        time.sleep(60)
if __name__=="__main__": main()
