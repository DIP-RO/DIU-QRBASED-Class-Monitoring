import csv, hashlib, io, json, re
from abc import ABC, abstractmethod
from datetime import date, datetime
from typing import Any
import httpx

TIME_FORMATS=("%I:%M %p","%I.%M %p","%H:%M")
def parse_time(value: str):
    cleaned=re.sub(r"\s+"," ",value.strip().upper())
    for fmt in TIME_FORMATS:
        try: return datetime.strptime(cleaned,fmt).strftime("%H:%M")
        except ValueError: pass
    raise ValueError(f"Invalid time: {value}")

def normalize_row(row: dict[str,Any], index=0):
    def pick(*keys):
        for key in keys:
            if row.get(key) not in (None,""): return str(row[key]).strip()
        return ""
    required={"department":pick("department","dept"),"teacher_alias":pick("teacherInitial","teacher_initial","teacher_alias"),"course_code":pick("courseCode","course_code"),"weekday":pick("weekday","day"),"start_time":pick("startTime","start_time"),"end_time":pick("endTime","end_time"),"room":pick("room","classroom")}
    missing=[k for k,v in required.items() if not v]
    if missing: raise ValueError("Missing: "+", ".join(missing))
    weekdays={"MONDAY":0,"TUESDAY":1,"WEDNESDAY":2,"THURSDAY":3,"FRIDAY":4,"SATURDAY":5,"SUNDAY":6}
    wd=int(required["weekday"]) if required["weekday"].isdigit() else weekdays.get(required["weekday"].upper(),-1)
    if wd not in range(7): raise ValueError("Invalid weekday")
    start,end=parse_time(required["start_time"]),parse_time(required["end_time"])
    if end <= start: raise ValueError("End must be after start; overnight requires explicit support")
    normalized={**required,"weekday":wd,"start_time":start,"end_time":end,"room":required["room"].upper().replace(" ",""),"batch":pick("batch"),"section":pick("section"),"semester":pick("semester") or "CURRENT","effective_from":pick("effective_from") or date.today().isoformat(),"effective_to":pick("effective_to") or date.today().replace(year=date.today().year+1).isoformat(),"source_id":pick("source_id","id")}
    normalized["source_key"]=normalized["source_id"] or hashlib.sha256(json.dumps(normalized,sort_keys=True).encode()).hexdigest()[:24]
    return normalized

class RoutineSourceAdapter(ABC):
    @abstractmethod
    def fetch(self): ...
class CSVAdapter(RoutineSourceAdapter):
    def __init__(self, content: str): self.content=content
    def fetch(self): return list(csv.DictReader(io.StringIO(self.content)))
class DemoAdapter(CSVAdapter): pass
class FirestoreAdapter(RoutineSourceAdapter):
    def __init__(self, project_id: str, token: str): self.project_id=project_id; self.token=token
    def fetch(self):
        if not self.token: raise RuntimeError("Reconnect source: authorized access token is not configured")
        url=f"https://firestore.googleapis.com/v1/projects/{self.project_id}/databases/(default)/documents/routines"
        rows=[]; page=None
        with httpx.Client(timeout=20) as client:
            while True:
                params={"pageToken":page} if page else {}
                res=client.get(url,params=params,headers={"Authorization":f"Bearer {self.token}"})
                if res.status_code in (401,403): raise RuntimeError("Reconnect source: authorization expired or insufficient")
                res.raise_for_status(); data=res.json()
                for doc in data.get("documents",[]): rows.append(doc)
                page=data.get("nextPageToken")
                if not page: break
        return rows

def normalize_batch(rows):
    accepted=[]; errors=[]
    for i,row in enumerate(rows,2):
        try:
            schedule=row.get("data",{}).get("schedule") if isinstance(row.get("data"),dict) else None
            schedule=schedule or row.get("schedule")
            if isinstance(schedule,list):
                for nested in schedule: accepted.append(normalize_row(nested,i))
            else: accepted.append(normalize_row(row,i))
        except Exception as exc: errors.append({"row":i,"error":str(exc)})
    return accepted,errors

