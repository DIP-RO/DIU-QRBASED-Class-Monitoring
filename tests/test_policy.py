from datetime import datetime,timezone
from backend.models import AttendanceResult
from backend.policy import classify_submission
def dt(h,m,s=0): return datetime(2026,1,1,h,m,s,tzinfo=timezone.utc)
def test_exact_boundaries():
    start,end=dt(10,0),dt(11,30)
    assert classify_submission(start,end,dt(9,54,59))=="TOO_EARLY"
    assert classify_submission(start,end,dt(9,55))==AttendanceResult.ON_TIME
    assert classify_submission(start,end,dt(10,5))==AttendanceResult.ON_TIME
    assert classify_submission(start,end,dt(10,5,1))==AttendanceResult.LATE
    assert classify_submission(start,end,dt(11,29,59))==AttendanceResult.LATE
    assert classify_submission(start,end,dt(11,30))=="CLOSED"

