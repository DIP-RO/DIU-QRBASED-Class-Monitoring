"""Controlled 20-session SQLite concurrency exercise; prints actual timings/errors."""
import concurrent.futures,os,tempfile,time
from datetime import datetime,timedelta,timezone,date
from sqlalchemy import create_engine,event
from sqlalchemy.orm import sessionmaker
from backend.models import Base,Department,PolicyVersion,Room,Teacher,User,Role,ClassSession,AttendanceRecord,AttendanceResult
fd,path=tempfile.mkstemp(suffix=".db");os.close(fd);engine=create_engine("sqlite:///"+path,connect_args={"check_same_thread":False,"timeout":5});Session=sessionmaker(engine)
@event.listens_for(engine,"connect")
def pragmas(c,_): c.execute("PRAGMA journal_mode=WAL");c.execute("PRAGMA busy_timeout=5000");c.execute("PRAGMA foreign_keys=ON")
Base.metadata.create_all(engine)
with Session() as db:
 d=Department(code="LOAD",name="Load Test");db.add(d);db.flush();p=PolicyVersion(early_minutes=5,grace_minutes=5,freshness_minutes=60,effective_at=datetime.now(timezone.utc),active=True);r=Room(campus="T",building="T",name="T",normalized_name="T");db.add_all([p,r]);db.flush()
 for i in range(20):
  u=User(provider_subject=f"u{i}",email=f"u{i}@invalid",name=f"U{i}",role=Role.TEACHER,department_id=d.id);db.add(u);db.flush();t=Teacher(user_id=u.id,department_id=d.id,name=u.name);db.add(t);db.flush();now=datetime.now(timezone.utc);db.add(ClassSession(occurrence_key=f"l{i}",teacher_id=t.id,department_id=d.id,room_id=r.id,policy_id=p.id,teaching_date=date.today(),start_at=now,end_at=now+timedelta(hours=1),course_code="LOAD",source_version="test",snapshot={}))
 db.commit()
def write(i):
 started=time.perf_counter()
 try:
  with Session() as db:
   s=db.query(ClassSession).filter_by(occurrence_key=f"l{i}").one();db.add(AttendanceRecord(session_id=s.id,teacher_id=s.teacher_id,original_result=AttendanceResult.ON_TIME,effective_result=AttendanceResult.ON_TIME,submitted_at=datetime.now(timezone.utc),network_policy_id=s.policy_id));db.commit()
  return time.perf_counter()-started,None
 except Exception as e:return time.perf_counter()-started,type(e).__name__+":"+str(e)
started=time.perf_counter()
with concurrent.futures.ThreadPoolExecutor(max_workers=20) as x:results=list(x.map(write,range(20)))
print({"sessions":20,"total_seconds":round(time.perf_counter()-started,4),"max_write_seconds":round(max(x[0] for x in results),4),"lock_errors":sum(bool(x[1]) for x in results),"errors":[x[1] for x in results if x[1]]})
os.unlink(path)
