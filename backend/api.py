import csv, hashlib, io, ipaddress, json, secrets
from datetime import date, datetime, time, timedelta, timezone
from zoneinfo import ZoneInfo
import qrcode
import qrcode.image.svg
from fastapi import APIRouter, Depends, File, HTTPException, Query, Request, UploadFile
from fastapi.responses import Response, StreamingResponse
from sqlalchemy import func, or_, select
from sqlalchemy.orm import Session
from backend.config import get_settings
from backend.database import get_db
from backend.models import *
from backend.schemas import *
from backend.security import *
from backend.services import DHAKA, audit, submit_checkin
from backend.sources import normalize_batch

router=APIRouter(prefix="/api/v1"); settings=get_settings()
def teacher_for(db,user):
    teacher=db.scalar(select(Teacher).where(Teacher.user_id==user.id,Teacher.active))
    if not teacher: raise HTTPException(403,"Active teacher mapping required")
    return teacher
def scoped(query,user,model=ClassSession):
    return query.where(model.department_id==user.department_id) if user.role!=Role.SYSTEM_ADMIN and user.department_id else query
def active_rules(db):
    p=db.scalar(select(PolicyVersion).where(PolicyVersion.active).order_by(PolicyVersion.id.desc()))
    return p,db.scalars(select(NetworkRule).where(NetworkRule.policy_id==p.id)).all() if p else []
def serialize_session(db,s,attendance=None):
    t=db.get(Teacher,s.teacher_id); r=db.get(Room,s.room_id); a=attendance or db.scalar(select(AttendanceRecord).where(AttendanceRecord.session_id==s.id))
    return {"id":s.id,"teaching_date":s.teaching_date,"teacher_name":t.name,"teacher_initials":db.scalar(select(TeacherAlias.alias).where(TeacherAlias.teacher_id==t.id)) or "","department_id":s.department_id,"course_code":s.course_code,"course_title":s.course_title,"batch":s.batch,"section":s.section,"room":r.name,"start_at":s.start_at,"end_at":s.end_at,"submitted_at":a.submitted_at if a else None,"minutes_late":a.minutes_late if a else None,"result":a.effective_result.value if a else None,"original_result":a.original_result.value if a else None,"source_version":s.source_version,"exception":s.reliability_state!="RELIABLE","corrected":a.correction_indicator if a else False}

@router.get("/me")
def me(user:User=Depends(current_user),db:Session=Depends(get_db)):
    teacher=db.scalar(select(Teacher).where(Teacher.user_id==user.id)); return {"id":user.id,"name":user.name,"email":user.email,"role":user.role,"department_id":user.department_id,"teacher_id":teacher.id if teacher else None}
@router.get("/checkin/context")
def context(request:Request,token:str,user:User=Depends(current_user),db:Session=Depends(get_db)):
    qr=db.scalar(select(RoomQR).where(RoomQR.token_hash==token_hash(token),RoomQR.active));
    if not qr: raise HTTPException(404,"Inactive or invalid QR")
    policy,rules=active_rules(db); ip=resolve_client_ip(request,rules)
    if not rules or not network_allowed(ip,rules): raise HTTPException(403,"Network blocked: connect to an approved campus network and retry")
    teacher=teacher_for(db,user); now=datetime.now(timezone.utc)
    sessions=db.scalars(select(ClassSession).where(ClassSession.teacher_id==teacher.id,ClassSession.lifecycle==Lifecycle.SCHEDULED,ClassSession.start_at-timedelta(minutes=policy.early_minutes)<=now,ClassSession.end_at>now)).all()
    initials=db.scalar(select(TeacherAlias.alias).where(TeacherAlias.teacher_id==teacher.id)) or ""
    resolved_room=db.get(Room,sessions[0].room_id).name if len(sessions)==1 else "Resolved from current routine"
    return {"room":resolved_room,"teacher":f"{teacher.name} · {initials}" if initials else teacher.name,"teacher_initials":initials,"detected_ip":ip,"candidates":[serialize_session(db,s) for s in sessions],"state":"READY" if len(sessions)==1 else "CONFLICT" if sessions else "NO_CLASS_FOUND","qr_scope":"GLOBAL"}
@router.post("/attendance/check-ins")
def checkin(body:CheckinIn,request:Request,user:User=Depends(current_user),db:Session=Depends(get_db)):
    received=datetime.now(timezone.utc); qr=db.scalar(select(RoomQR).where(RoomQR.token_hash==token_hash(body.qr_token),RoomQR.active))
    if not qr: raise HTTPException(404,"Inactive or invalid QR")
    policy,rules=active_rules(db); ip=resolve_client_ip(request,rules)
    if not rules or not network_allowed(ip,rules): raise HTTPException(403,"NETWORK_BLOCKED")
    teacher=teacher_for(db,user); session=db.get(ClassSession,body.session_id)
    if not session: raise HTTPException(404,"Session not found")
    entry=db.get(RoutineEntry,session.routine_entry_id) if session.routine_entry_id else None
    if body.present_students is not None and entry and entry.enrolled_count is not None and body.present_students>entry.enrolled_count: raise HTTPException(422,"Present students exceeds enrolled count")
    payload=body.model_dump(exclude={"idempotency_key"}); result=submit_checkin(db,user,teacher,session,qr,received,ip,body.idempotency_key,payload)
    if isinstance(result,AttendanceAttempt): raise HTTPException(409,result.outcome)
    return {"receipt":serialize_session(db,session,result),"already_submitted":result.submitted_at!=received}
@router.get("/teacher/sessions")
def own_sessions(user:User=Depends(current_user),db:Session=Depends(get_db)):
    t=teacher_for(db,user); rows=db.scalars(select(ClassSession).where(ClassSession.teacher_id==t.id).order_by(ClassSession.start_at.desc()).limit(100)).all(); return [serialize_session(db,s) for s in rows]
@router.post("/correction-requests")
def correction(attendance_id:int,body:CorrectionIn,user:User=Depends(current_user),db:Session=Depends(get_db)):
    t=teacher_for(db,user); a=db.get(AttendanceRecord,attendance_id)
    if not a or a.teacher_id!=t.id: raise HTTPException(404)
    item=CorrectionRequest(attendance_id=a.id,requester_id=user.id,reason=body.reason,evidence=body.evidence,created_at=utcnow()); db.add(item); audit(db,user,"CORRECTION_REQUESTED","attendance",a.id,{"reason":body.reason}); db.commit(); return {"id":item.id,"status":item.status}

@router.get("/admin/dashboard")
def dashboard(user:User=Depends(require_roles(Role.DEPT_ADMIN,Role.SYSTEM_ADMIN,Role.VIEWER)),db:Session=Depends(get_db)):
    today=datetime.now(DHAKA).date(); q=scoped(select(ClassSession).where(ClassSession.teaching_date==today),user); rows=db.scalars(q).all(); results=[db.scalar(select(AttendanceRecord).where(AttendanceRecord.session_id==s.id)) for s in rows]; counts={k:0 for k in ["expected","on_time","late","absent","review","cancelled","upcoming"]}
    counts["expected"]=sum(s.lifecycle!=Lifecycle.CANCELLED for s in rows); counts["cancelled"]=sum(s.lifecycle==Lifecycle.CANCELLED for s in rows)
    for a in results:
        if not a: counts["upcoming"]+=1
        elif a.effective_result==AttendanceResult.ON_TIME: counts["on_time"]+=1
        elif a.effective_result==AttendanceResult.LATE: counts["late"]+=1
        elif a.effective_result==AttendanceResult.ABSENT_NO_CHECKIN: counts["absent"]+=1
        elif a.effective_result==AttendanceResult.REVIEW_REQUIRED: counts["review"]+=1
    source=db.scalar(select(SourceConfiguration).where(SourceConfiguration.active).order_by(SourceConfiguration.id.desc())); worker=db.get(JobState,"main")
    return {"counts":counts,"source":{"status":source.status if source else "UNCONNECTED","last_good_at":source.last_good_at if source else None},"worker":{"status":worker.status if worker else "NOT_STARTED","heartbeat_at":worker.heartbeat_at if worker else None}}
def filtered_sessions(db,user,teacher=None,date_from=None,date_to=None,department_id=None,room=None,course=None,status=None):
    q=scoped(select(ClassSession),user)
    if teacher: q=q.join(Teacher).outerjoin(TeacherAlias).where(or_(Teacher.name.ilike(f"%{teacher}%"),TeacherAlias.alias.ilike(f"%{teacher}%")))
    if date_from:q=q.where(ClassSession.teaching_date>=date_from)
    if date_to:q=q.where(ClassSession.teaching_date<=date_to)
    if department_id:q=q.where(ClassSession.department_id==department_id)
    if room:q=q.join(Room).where(Room.normalized_name.ilike(f"%{room.replace(' ','')}%"))
    if course:q=q.where(ClassSession.course_code.ilike(f"%{course}%"))
    if status:q=q.join(AttendanceRecord).where(AttendanceRecord.effective_result==status)
    return q.distinct()
@router.get("/admin/sessions")
def admin_sessions(user:User=Depends(require_roles(Role.DEPT_ADMIN,Role.SYSTEM_ADMIN,Role.VIEWER)),db:Session=Depends(get_db),teacher:str|None=None,date_from:date|None=None,date_to:date|None=None,department_id:int|None=None,room:str|None=None,course:str|None=None,status:AttendanceResult|None=None,page:int=Query(1,ge=1),page_size:int=Query(25,ge=1,le=200)):
    q=filtered_sessions(db,user,teacher,date_from,date_to,department_id,room,course,status).order_by(ClassSession.start_at.desc()).offset((page-1)*page_size).limit(page_size); return [serialize_session(db,s) for s in db.scalars(q).all()]
@router.get("/admin/exports/attendance.csv")
def export_csv(user:User=Depends(require_roles(Role.DEPT_ADMIN,Role.SYSTEM_ADMIN)),db:Session=Depends(get_db),teacher:str|None=None,date_from:date|None=None,date_to:date|None=None,room:str|None=None,course:str|None=None,status:AttendanceResult|None=None):
    rows=db.scalars(filtered_sessions(db,user,teacher,date_from,date_to,None,room,course,status).order_by(ClassSession.start_at)).all(); out=io.StringIO(); writer=csv.writer(out); writer.writerow(["timezone","date","teacher","initials","course","room","scheduled_start","scheduled_end","submitted_at","original_result","effective_result","corrected"])
    safe=lambda v: "'"+str(v) if str(v).startswith(("=","+","-","@")) else v
    for s in rows:
        x=serialize_session(db,s); writer.writerow(["Asia/Dhaka",x["teaching_date"],safe(x["teacher_name"]),safe(x["teacher_initials"]),safe(x["course_code"]),safe(x["room"]),s.start_at.astimezone(DHAKA).isoformat(),s.end_at.astimezone(DHAKA).isoformat(),x["submitted_at"],x["original_result"],x["result"],x["corrected"]])
    return Response(out.getvalue(),media_type="text/csv",headers={"Content-Disposition":"attachment; filename=attendance.csv","X-Report-Timezone":"Asia/Dhaka"})
@router.post("/admin/rooms/{room_id}/qr/rotate")
def rotate_qr(room_id:int,user:User=Depends(require_roles(Role.DEPT_ADMIN,Role.SYSTEM_ADMIN)),db:Session=Depends(get_db)):
    room=db.get(Room,room_id)
    if not room or (user.role!=Role.SYSTEM_ADMIN and room_id not in [x for x in db.scalars(select(ClassSession.room_id).where(ClassSession.department_id==user.department_id)).all()]): raise HTTPException(404)
    now=utcnow()
    for old in db.scalars(select(RoomQR).where(RoomQR.active)): old.active=False; old.revoked_at=now
    token=opaque_token(); qr=RoomQR(room_id=room_id,token_hash=token_hash(token),token_hint=token[:8],active=True,created_at=now); db.add(qr); db.flush(); audit(db,user,"QR_ROTATED","room",room_id,{"token_hint":qr.token_hint}); db.commit(); return {"url":f"{settings.effective_qr_base_url}/q/{token}","token":token}
@router.get("/admin/rooms/{room_id}/qr/{format}")
def qr_download(room_id:int,format:str,token:str,user:User=Depends(require_roles(Role.DEPT_ADMIN,Role.SYSTEM_ADMIN)),db:Session=Depends(get_db)):
    qr=db.scalar(select(RoomQR).where(RoomQR.token_hash==token_hash(token),RoomQR.active));
    if not qr: raise HTTPException(404)
    value=f"{settings.effective_qr_base_url}/q/{token}"; buf=io.BytesIO()
    if format=="svg": qrcode.make(value,image_factory=qrcode.image.svg.SvgPathImage).save(buf); media="image/svg+xml"
    elif format=="png": qrcode.make(value).save(buf,format="PNG"); media="image/png"
    else: raise HTTPException(404)
    return Response(buf.getvalue(),media_type=media,headers={"Content-Disposition":f"attachment; filename=room-{room_id}.{format}"})

@router.post("/admin/rooms/{room_id}/test-session")
def create_test_session(room_id:int,user:User=Depends(require_roles(Role.SYSTEM_ADMIN)),db:Session=Depends(get_db)):
    if settings.environment=="production" or not settings.dev_auth_enabled: raise HTTPException(404)
    room=db.get(Room,room_id)
    if not room: raise HTTPException(404,"Room not found")
    entry=db.scalar(select(RoutineEntry).where(RoutineEntry.room_id==room_id).order_by(RoutineEntry.id))
    if not entry: raise HTTPException(409,"No routine entry is mapped to this room")
    policy=db.scalar(select(PolicyVersion).where(PolicyVersion.active).order_by(PolicyVersion.id.desc()))
    now=utcnow(); teaching_date=now.astimezone(DHAKA).date()
    existing=db.scalar(select(ClassSession).where(ClassSession.room_id==room_id,ClassSession.teacher_id==entry.teacher_id,ClassSession.end_at>now,ClassSession.lifecycle==Lifecycle.SCHEDULED,ClassSession.source_version.in_(["DEVELOPMENT_TEST","LOCAL_TEST_CURRENT","LOCAL-TEST-CURRENT"])).order_by(ClassSession.start_at.desc()))
    if existing:
        existing.end_at=now+timedelta(minutes=60)
        db.commit();teacher=db.get(Teacher,entry.teacher_id)
        return {"session_id":existing.id,"teacher_user_id":teacher.user_id,"teacher_name":teacher.name,"starts_at":existing.start_at,"ends_at":existing.end_at,"already_active":True}
    key=f"development-live-test:{room_id}:{secrets.token_hex(8)}"
    session=ClassSession(occurrence_key=key,routine_entry_id=entry.id,teacher_id=entry.teacher_id,department_id=entry.department_id,room_id=room_id,policy_id=policy.id,teaching_date=teaching_date,start_at=now-timedelta(minutes=2),end_at=now+timedelta(minutes=60),course_code=entry.course_code,course_title=entry.course_title or "Live QR test class",batch=entry.batch,section=entry.section,source_version="DEVELOPMENT_TEST",reliability_state="RELIABLE",snapshot={"development_test":True,"early_minutes":policy.early_minutes,"grace_minutes":policy.grace_minutes})
    db.add(session);db.flush();audit(db,user,"DEVELOPMENT_TEST_SESSION_CREATED","class_session",session.id,{"room_id":room_id,"teacher_id":entry.teacher_id});db.commit()
    teacher=db.get(Teacher,entry.teacher_id)
    return {"session_id":session.id,"teacher_user_id":teacher.user_id,"teacher_name":teacher.name,"starts_at":session.start_at,"ends_at":session.end_at}
@router.get("/admin/policies")
def get_policy(user:User=Depends(require_roles(Role.SYSTEM_ADMIN)),db:Session=Depends(get_db)):
    p,r=active_rules(db); return {"id":p.id,"early_minutes":p.early_minutes,"grace_minutes":p.grace_minutes,"freshness_minutes":p.freshness_minutes,"rules":[{"cidr":x.cidr,"label":x.label,"trusted_proxy":x.is_trusted_proxy} for x in r]}
@router.patch("/admin/policies")
def patch_policy(body:PolicyIn,user:User=Depends(require_roles(Role.SYSTEM_ADMIN)),db:Session=Depends(get_db)):
    cidrs=[validate_cidr(x) for x in body.allowed_cidrs]; proxies=[validate_cidr(x) for x in body.trusted_proxy_cidrs]
    for p in db.scalars(select(PolicyVersion).where(PolicyVersion.active)): p.active=False
    p=PolicyVersion(early_minutes=body.early_minutes,grace_minutes=body.grace_minutes,freshness_minutes=body.freshness_minutes,effective_at=utcnow(),actor_id=user.id,active=True); db.add(p); db.flush()
    for x in cidrs: db.add(NetworkRule(policy_id=p.id,cidr=x,label="Campus network",campus="Configured",is_trusted_proxy=False,active_from=date.today()))
    for x in proxies: db.add(NetworkRule(policy_id=p.id,cidr=x,label="Trusted proxy",campus="Edge",is_trusted_proxy=True,active_from=date.today()))
    audit(db,user,"POLICY_CHANGED","policy",p.id,body.model_dump()); db.commit(); return {"id":p.id}
@router.post("/admin/network/test")
def network_test(body:NetworkTestIn,request:Request,user:User=Depends(require_roles(Role.SYSTEM_ADMIN)),db:Session=Depends(get_db)):
    p,r=active_rules(db); address=body.address or resolve_client_ip(request,r); return {"address":address,"allowed":network_allowed(address,r),"policy_id":p.id}
@router.post("/admin/attendance/{attendance_id}/corrections")
def decide_correction(attendance_id:int,body:CorrectionDecision,user:User=Depends(require_roles(Role.DEPT_ADMIN,Role.SYSTEM_ADMIN)),db:Session=Depends(get_db)):
    a=db.get(AttendanceRecord,attendance_id); s=db.get(ClassSession,a.session_id) if a else None
    if not a or (user.role!=Role.SYSTEM_ADMIN and s.department_id!=user.department_id): raise HTTPException(404)
    before=a.effective_result.value; a.effective_result=AttendanceResult(body.result); a.correction_indicator=True; audit(db,user,"ATTENDANCE_CORRECTED","attendance",a.id,{"before":before,"after":body.result},body.reason); db.commit(); return {"id":a.id,"original":a.original_result,"effective":a.effective_result}
@router.get("/admin/audit")
def audits(user:User=Depends(require_roles(Role.DEPT_ADMIN,Role.SYSTEM_ADMIN,Role.VIEWER)),db:Session=Depends(get_db)):
    rows=db.scalars(select(AuditEvent).order_by(AuditEvent.created_at.desc()).limit(200)).all(); return [{"id":x.id,"actor_id":x.actor_id,"action":x.action,"target":f"{x.target_type}:{x.target_id}","created_at":x.created_at,"changes":x.changes,"reason":x.reason} for x in rows]
@router.get("/admin/sync-runs")
def sync_runs(user:User=Depends(require_roles(Role.DEPT_ADMIN,Role.SYSTEM_ADMIN,Role.VIEWER)),db:Session=Depends(get_db)):
    return db.scalars(select(SyncRun).order_by(SyncRun.started_at.desc()).limit(100)).all()

@router.post("/admin/routines/import")
async def import_routine(file:UploadFile=File(...),user:User=Depends(require_roles(Role.DEPT_ADMIN,Role.SYSTEM_ADMIN)),db:Session=Depends(get_db)):
    if not file.filename.lower().endswith(".csv"): raise HTTPException(415,"CSV file required")
    try: content=(await file.read()).decode("utf-8-sig")
    except UnicodeDecodeError: raise HTTPException(422,"CSV must be UTF-8")
    rows=list(csv.DictReader(io.StringIO(content))); accepted,errors=normalize_batch(rows); resolved=[]
    for row in accepted:
        dept=db.scalar(select(Department).where(Department.code.ilike(row["department"]),Department.active))
        if not dept or (user.role!=Role.SYSTEM_ADMIN and dept.id!=user.department_id): errors.append({"source_key":row["source_key"],"error":"Unknown or unauthorized department"}); continue
        teachers=db.scalars(select(Teacher).join(TeacherAlias).where(Teacher.department_id==dept.id,TeacherAlias.alias==row["teacher_alias"],TeacherAlias.resolved)).all()
        room=db.scalar(select(Room).where(Room.normalized_name==row["room"],Room.active))
        if len(teachers)!=1: errors.append({"source_key":row["source_key"],"error":"Teacher alias is missing or ambiguous"}); continue
        if not room: errors.append({"source_key":row["source_key"],"error":"Room is not configured"}); continue
        resolved.append((row,dept,teachers[0],room))
    if not resolved: return {"accepted":0,"rejected":len(errors),"errors":errors,"committed":False}
    source=db.scalar(select(SourceConfiguration).where(SourceConfiguration.adapter_type=="CSV",SourceConfiguration.active))
    if not source: source=SourceConfiguration(adapter_type="CSV",label="Administrator CSV import",status="CONNECTED",active=True);db.add(source);db.flush()
    now=utcnow(); digest=hashlib.sha256(content.encode()).hexdigest(); version=f"csv-{now.strftime('%Y%m%d%H%M%S')}"
    for old in db.scalars(select(RoutineVersion).where(RoutineVersion.source_id==source.id,RoutineVersion.active)): old.active=False
    rv=RoutineVersion(source_id=source.id,external_version=version,digest=digest,imported_at=now,active=True,demonstration=False);db.add(rv);db.flush()
    for row,dept,teacher,room in resolved:
        db.add(RoutineEntry(routine_version_id=rv.id,source_key=row["source_key"],department_id=dept.id,teacher_id=teacher.id,room_id=room.id,course_code=row["course_code"],batch=row["batch"],section=row["section"],weekday=row["weekday"],start_time=row["start_time"],end_time=row["end_time"],semester=row["semester"],effective_from=date.fromisoformat(row["effective_from"]),effective_to=date.fromisoformat(row["effective_to"])))
    source.last_good_at=now; source.status="CONNECTED"; run=SyncRun(source_id=source.id,started_at=now,completed_at=now,status="SUCCESS",source_version=version,digest=digest,accepted_count=len(resolved),rejected_count=len(errors),errors=errors);db.add(run);audit(db,user,"ROUTINE_IMPORTED","routine_version",rv.id,{"accepted":len(resolved),"rejected":len(errors)});db.commit()
    return {"accepted":len(resolved),"rejected":len(errors),"errors":errors,"committed":True,"version":version}

@router.post("/admin/sources/sync")
def queue_sync(user:User=Depends(require_roles(Role.SYSTEM_ADMIN)),db:Session=Depends(get_db)):
    source=db.scalar(select(SourceConfiguration).where(SourceConfiguration.adapter_type=="LIVE",SourceConfiguration.active))
    if not source or source.status=="UNCONNECTED": raise HTTPException(409,"Live source is unconnected; configure authorized credentials first")
    state=db.get(JobState,"source_sync") or JobState(name="source_sync",status="QUEUED"); state.status="QUEUED"; state.detail=f"Requested by user {user.id}";db.add(state);audit(db,user,"SOURCE_SYNC_QUEUED","source",source.id);db.commit();return {"status":"QUEUED"}

@router.get("/admin/rooms")
def list_rooms(user:User=Depends(require_roles(Role.DEPT_ADMIN,Role.SYSTEM_ADMIN,Role.VIEWER)),db:Session=Depends(get_db)):
    qr=db.scalar(select(RoomQR).where(RoomQR.active).order_by(RoomQR.created_at.desc()))
    anchor=db.get(Room,qr.room_id) if qr else db.scalar(select(Room).where(Room.active).order_by(Room.id))
    if not anchor: return []
    return [{"id":anchor.id,"campus":"Daffodil International University","building":"System-wide access","name":"Universal QR · All rooms and teachers","active":True,"has_active_qr":bool(qr),"qr_hint":qr.token_hint if qr else None}]
@router.get("/admin/teachers")
def list_teachers(user:User=Depends(require_roles(Role.DEPT_ADMIN,Role.SYSTEM_ADMIN,Role.VIEWER)),db:Session=Depends(get_db)):
    q=select(Teacher)
    if user.role!=Role.SYSTEM_ADMIN:q=q.where(Teacher.department_id==user.department_id)
    return [{"id":t.id,"name":t.name,"department_id":t.department_id,"email":t.user.email,"active":t.active,"aliases":db.scalars(select(TeacherAlias.alias).where(TeacherAlias.teacher_id==t.id)).all()} for t in db.scalars(q).all()]
