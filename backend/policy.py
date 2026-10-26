from datetime import timedelta, timezone
from backend.models import AttendanceResult

def classify_submission(start, end, received, early_minutes=5, grace_minutes=5):
    if start.tzinfo is None: start=start.replace(tzinfo=timezone.utc)
    if end.tzinfo is None: end=end.replace(tzinfo=timezone.utc)
    if received.tzinfo is None: received=received.replace(tzinfo=timezone.utc)
    if received < start - timedelta(minutes=early_minutes): return "TOO_EARLY"
    if received <= start + timedelta(minutes=grace_minutes): return AttendanceResult.ON_TIME
    if received < end: return AttendanceResult.LATE
    return "CLOSED"

def lifecycle_label(session, attendance, now):
    if session.lifecycle.value == "CANCELLED": return "CANCELLED"
    if attendance: return attendance.effective_result.value
    if now < session.start_at - timedelta(minutes=5): return "UPCOMING"
    if now < session.start_at: return "CHECKIN_OPEN"
    if now < session.end_at: return "IN_PROGRESS_NO_CHECKIN"
    return "ENDED_NO_CHECKIN"
