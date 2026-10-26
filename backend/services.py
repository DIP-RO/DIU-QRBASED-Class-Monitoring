import hashlib, json, secrets
from datetime import date, datetime, time, timedelta, timezone
from zoneinfo import ZoneInfo
from sqlalchemy import and_, func, or_, select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session
from backend.models import *
from backend.policy import classify_submission
from backend.security import token_hash

DHAKA=ZoneInfo("Asia/Dhaka")
def audit(db, actor, action, target, target_id, changes=None, reason=None, correlation_id=None):
    db.add(AuditEvent(actor_id=getattr(actor,"id",None),action=action,target_type=target,target_id=str(target_id),created_at=datetime.now(timezone.utc),changes=changes or {},reason=reason,correlation_id=correlation_id or secrets.token_hex(12)))

def generate_sessions(db: Session, start: date, days=14):
    policy=db.scalar(select(PolicyVersion).where(PolicyVersion.active).order_by(PolicyVersion.id.desc()))
    entries=db.scalars(select(RoutineEntry).join(RoutineVersion).where(RoutineVersion.active)).all(); made=0
    for offset in range(days):
        local_date=start+timedelta(days=offset)
        for e in entries:
            if e.weekday!=local_date.weekday() or not e.effective_from<=local_date<=e.effective_to: continue
            occurrence=f"{e.source_key}:{local_date.isoformat()}"
            if db.scalar(select(ClassSession.id).where(ClassSession.occurrence_key==occurrence)): continue
            sh,sm=map(int,e.start_time.split(":")); eh,em=map(int,e.end_time.split(":"))
            start_at=datetime.combine(local_date,time(sh,sm),DHAKA).astimezone(timezone.utc); end_at=datetime.combine(local_date,time(eh,em),DHAKA).astimezone(timezone.utc)
            rv=db.get(RoutineVersion,e.routine_version_id)
            db.add(ClassSession(occurrence_key=occurrence,routine_entry_id=e.id,teacher_id=e.teacher_id,department_id=e.department_id,room_id=e.room_id,policy_id=policy.id,teaching_date=local_date,start_at=start_at,end_at=end_at,course_code=e.course_code,course_title=e.course_title,batch=e.batch,section=e.section,source_version=rv.external_version,snapshot={"early_minutes":policy.early_minutes,"grace_minutes":policy.grace_minutes,"room_id":e.room_id,"teacher_id":e.teacher_id}))
            made+=1
    db.commit(); return made

def submit_checkin(db: Session, user: User, teacher: Teacher, session: ClassSession, qr: RoomQR, received: datetime, ip: str, key: str, payload: dict):
    digest=hashlib.sha256(json.dumps(payload,sort_keys=True).encode()).hexdigest()
    prior=db.scalar(select(AttendanceAttempt).where(AttendanceAttempt.actor_id==user.id,AttendanceAttempt.idempotency_key==key))
    if prior:
        if prior.payload_digest!=digest: raise ValueError("IDEMPOTENCY_CONFLICT")
        return db.get(AttendanceRecord,prior.attendance_id) if prior.attendance_id else prior
    request_id=secrets.token_hex(16); policy=db.get(PolicyVersion,session.policy_id)
    outcome=classify_submission(session.start_at,session.end_at,received,policy.early_minutes,policy.grace_minutes)
    if session.teacher_id!=teacher.id: outcome="WRONG_TEACHER"
    elif session.lifecycle!=Lifecycle.SCHEDULED: outcome="SESSION_UNAVAILABLE"
    attempt=AttendanceAttempt(request_id=request_id,idempotency_key=key,payload_digest=digest,actor_id=user.id,session_id=session.id,received_at=received,outcome=str(getattr(outcome,"value",outcome)))
    db.add(attempt)
    if not isinstance(outcome,AttendanceResult): db.commit(); return attempt
    existing=db.scalar(select(AttendanceRecord).where(AttendanceRecord.session_id==session.id,AttendanceRecord.teacher_id==teacher.id))
    if existing: attempt.outcome="ALREADY_SUBMITTED"; attempt.attendance_id=existing.id; db.commit(); return existing
    session_start=session.start_at.replace(tzinfo=timezone.utc) if session.start_at.tzinfo is None else session.start_at
    minutes=max(0,int((received-session_start).total_seconds()//60))
    record=AttendanceRecord(session_id=session.id,teacher_id=teacher.id,original_result=outcome,effective_result=outcome,submitted_at=received,minutes_late=minutes if outcome==AttendanceResult.LATE else 0,present_students=payload.get("present_students"),topic=payload.get("topic"),remarks=payload.get("remarks"),resolved_ip=ip,network_policy_id=policy.id)
    db.add(record); db.flush(); attempt.attendance_id=record.id; audit(db,user,"ATTENDANCE_ACCEPTED","attendance",record.id,{"result":outcome.value},correlation_id=request_id); db.commit(); return record

def finalize_absences(db: Session, now: datetime):
    sessions=db.scalars(select(ClassSession).where(ClassSession.end_at<=now,ClassSession.lifecycle==Lifecycle.SCHEDULED)).all(); counts={"absent":0,"review":0}
    source=db.scalar(select(SourceConfiguration).where(SourceConfiguration.active).order_by(SourceConfiguration.id.desc()))
    for s in sessions:
        if db.scalar(select(AttendanceRecord.id).where(AttendanceRecord.session_id==s.id)): continue
        incidents=db.scalar(select(func.count()).select_from(ServiceIncident).where(ServiceIncident.starts_at<s.end_at,or_(ServiceIncident.ends_at==None,ServiceIncident.ends_at>s.start_at))) or 0
        policy=db.get(PolicyVersion,s.policy_id)
        last_good=source.last_good_at.replace(tzinfo=timezone.utc) if source and source.last_good_at and source.last_good_at.tzinfo is None else (source.last_good_at if source else None)
        fresh=bool(last_good and (now-last_good)<=timedelta(minutes=policy.freshness_minutes))
        result=AttendanceResult.ABSENT_NO_CHECKIN if fresh and s.reliability_state=="RELIABLE" and not incidents else AttendanceResult.REVIEW_REQUIRED
        db.add(AttendanceRecord(session_id=s.id,teacher_id=s.teacher_id,original_result=result,effective_result=result,submitted_at=None,network_policy_id=policy.id)); s.lifecycle=Lifecycle.COMPLETED; counts["absent" if result==AttendanceResult.ABSENT_NO_CHECKIN else "review"]+=1
    db.commit(); return counts
