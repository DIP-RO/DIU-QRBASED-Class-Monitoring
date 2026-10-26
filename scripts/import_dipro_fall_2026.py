"""Import Dipro Paul's verified Fall 2026 routine from the supplied DIU image.

Removes the earlier LOCALTEST fixtures, preserves the institutional user and
permanent QR, and creates four temporary current-time validation sessions.
"""
from datetime import date, datetime, timedelta, timezone
from hashlib import sha256
from zoneinfo import ZoneInfo

from sqlalchemy import delete, select

from backend.database import SessionLocal
from backend.models import (
    AttendanceAttempt, AttendanceRecord, ClassSession, CorrectionRequest,
    Department, PolicyVersion, Room, RoomQR, RoutineEntry, RoutineVersion,
    SourceConfiguration, SyncRun, Teacher, TeacherAlias, User,
)

DHAKA = ZoneInfo("Asia/Dhaka")
SOURCE_FILE = "6264651294249259663.jpg"

# weekday uses Python's Monday=0 convention. Course code is deliberately
# "Not shown" where the source image does not display an official code.
ROUTINE = (
    (5, "11:30", "13:00", "SE322", "SE322", "UC-A1", "Annex-409 (LAB)"),
    (5, "13:00", "14:30", "SE321", "SE321", "UC-A", "Annex-308"),
    (5, "14:30", "16:00", "SE321", "SE321", "UC-A", "Annex-308"),
    (6, "08:30", "10:00", "Not shown", "Algorithms Design & Analysis", "45-L", "Annex-308"),
    (6, "10:00", "11:30", "Not shown", "Algorithms Design & Analysis", "45-L", "Annex-308"),
    (0, "11:30", "13:00", "Not shown", "System Analysis & Design Capstone Project (Lab)", "44-J2", "LAB-ONLINE"),
    (2, "10:00", "11:30", "Not shown", "Software Quality Assurance & Testing", "43-O", "913"),
    (2, "14:30", "16:00", "Not shown", "System Analysis & Design Capstone Project (Lab)", "44-J2", "LAB-G1-022 (COM LAB)"),
    (2, "16:00", "17:30", "Not shown", "System Analysis & Design Capstone Project (Lab)", "44-J2", "LAB-G1-022 (COM LAB)"),
    (3, "10:00", "11:30", "Not shown", "Software Quality Assurance & Testing", "43-O", "812"),
    (3, "13:00", "14:30", "Not shown", "Software Quality Assurance & Testing Lab", "43-O1", "LAB-710"),
)


def building_for(name: str) -> str:
    if name.startswith("Annex"):
        return "Annex"
    if name == "LAB-ONLINE":
        return "Online"
    return "Daffodil Smart City"


with SessionLocal() as db:
    now = datetime.now(timezone.utc)
    local_now = now.astimezone(DHAKA)
    user = db.scalar(select(User).where(User.active, ~User.provider_subject.startswith("demo-")).order_by(User.id))
    if not user:
        raise SystemExit("No verified institutional user exists. Sign in first.")

    department = db.scalar(select(Department).where(Department.code == "SWE"))
    if not department:
        department = Department(code="SWE", name="Department of Software Engineering", active=True)
        db.add(department)
        db.flush()

    teacher = db.scalar(select(Teacher).where(Teacher.user_id == user.id))
    if not teacher:
        teacher = Teacher(user_id=user.id, department_id=department.id, name="Dipro Paul", active=True)
        db.add(teacher)
        db.flush()
    teacher.department_id = department.id
    teacher.name = "Dipro Paul"
    teacher.active = True
    user.department_id = department.id

    rooms = {}
    for room_name in dict.fromkeys(row[6] for row in ROUTINE):
        normalized = room_name.upper()
        room = db.scalar(select(Room).where(Room.normalized_name == normalized))
        if not room:
            room = Room(
                campus="Daffodil International University",
                building=building_for(room_name), name=room_name,
                normalized_name=normalized, active=True,
            )
            db.add(room)
            db.flush()
        rooms[room_name] = room

    # Preserve the already distributed QR by making it the permanent QR for
    # Annex-308. Class/time resolution remains dynamic.
    test_room = db.scalar(select(Room).where(Room.normalized_name == "TEST-ROOM"))
    if test_room:
        for qr in db.scalars(select(RoomQR).where(RoomQR.room_id == test_room.id)):
            qr.room_id = rooms["Annex-308"].id

    test_versions = db.scalars(
        select(RoutineVersion).join(SourceConfiguration).where(
            SourceConfiguration.adapter_type == "LOCAL_TEST"
        )
    ).all()
    test_version_ids = [version.id for version in test_versions]
    test_entry_ids = []
    if test_version_ids:
        test_entry_ids = list(db.scalars(select(RoutineEntry.id).where(RoutineEntry.routine_version_id.in_(test_version_ids))))

    test_session_ids = list(db.scalars(select(ClassSession.id).where(
        (ClassSession.source_version.in_((
            "LOCAL_TEST_CURRENT", "LOCAL-TEST-CURRENT", "DEVELOPMENT_TEST",
            "TEMPORARY_CURRENT_TIME_VALIDATION",
        )))
        | (ClassSession.routine_entry_id.in_(test_entry_ids) if test_entry_ids else False)
    )))
    if test_session_ids:
        attendance_ids = list(db.scalars(select(AttendanceRecord.id).where(AttendanceRecord.session_id.in_(test_session_ids))))
        if attendance_ids:
            db.execute(delete(CorrectionRequest).where(CorrectionRequest.attendance_id.in_(attendance_ids)))
        db.execute(delete(AttendanceAttempt).where(AttendanceAttempt.session_id.in_(test_session_ids)))
        db.execute(delete(AttendanceRecord).where(AttendanceRecord.session_id.in_(test_session_ids)))
        db.execute(delete(ClassSession).where(ClassSession.id.in_(test_session_ids)))
    if test_entry_ids:
        db.execute(delete(RoutineEntry).where(RoutineEntry.id.in_(test_entry_ids)))
    if test_version_ids:
        db.execute(delete(RoutineVersion).where(RoutineVersion.id.in_(test_version_ids)))

    test_sources = db.scalars(select(SourceConfiguration).where(SourceConfiguration.adapter_type == "LOCAL_TEST")).all()
    for test_source in test_sources:
        db.execute(delete(SyncRun).where(SyncRun.source_id == test_source.id))
        db.delete(test_source)

    db.execute(delete(TeacherAlias).where(TeacherAlias.teacher_id == teacher.id))
    db.add(TeacherAlias(
        teacher_id=teacher.id, department_id=department.id,
        source="DIU_CAMPUS_SCHEDULE", alias="DP", resolved=True,
    ))
    if test_room:
        db.delete(test_room)
    local_department = db.scalar(select(Department).where(Department.code == "LOCALTEST"))
    if local_department:
        db.delete(local_department)
    db.flush()

    source = db.scalar(select(SourceConfiguration).where(SourceConfiguration.adapter_type == "MANUAL_IMAGE"))
    if not source:
        source = SourceConfiguration(
            adapter_type="MANUAL_IMAGE", label="DIU Campus Schedule · Dipro Paul · Fall 2026",
            status="VERIFIED_IMAGE", config={"source_file": SOURCE_FILE, "teacher_initials": "DP"},
            last_good_at=now, active=True,
        )
        db.add(source)
        db.flush()

    old_versions = db.scalars(select(RoutineVersion).where(RoutineVersion.source_id == source.id)).all()
    old_version_ids = [old_version.id for old_version in old_versions]
    if old_version_ids:
        db.execute(delete(RoutineEntry).where(RoutineEntry.routine_version_id.in_(old_version_ids)))
        db.execute(delete(RoutineVersion).where(RoutineVersion.id.in_(old_version_ids)))
    digest = sha256(repr(ROUTINE).encode()).hexdigest()
    version = RoutineVersion(
        source_id=source.id, external_version="DIU-SWE-FALL-2026-DP-20261010",
        digest=digest, imported_at=now, active=True, demonstration=False,
    )
    db.add(version)
    db.flush()

    entries = []
    for index, (weekday, start, end, code, title, section, room_name) in enumerate(ROUTINE, 1):
        entry = RoutineEntry(
            routine_version_id=version.id, source_key=f"DP-FALL-2026-{index:02d}",
            department_id=department.id, teacher_id=teacher.id, room_id=rooms[room_name].id,
            course_code=code, course_title=title, batch="Fall 2026", section=section,
            weekday=weekday, start_time=start, end_time=end, semester="Fall 2026",
            effective_from=date(2026, 10, 10), effective_to=date(2027, 1, 31),
            enrolled_count=None,
        )
        db.add(entry)
        entries.append(entry)
    db.flush()

    policy = db.scalar(select(PolicyVersion).where(PolicyVersion.active).order_by(PolicyVersion.id.desc()))
    if not policy:
        raise SystemExit("No active attendance policy exists.")

    # Four temporary validation records based on real routine entries. Only
    # the first is active now; the others are sequential to avoid conflicts.
    validation_entries = (entries[1], entries[0], entries[2], entries[3])
    for offset, entry in enumerate(validation_entries):
        start_at = now - timedelta(minutes=2) if offset == 0 else now + timedelta(minutes=30 * offset)
        end_at = now + timedelta(minutes=28) if offset == 0 else start_at + timedelta(minutes=28)
        db.add(ClassSession(
            occurrence_key=f"DP-VALIDATION-{local_now:%Y%m%d%H%M}-{offset + 1}",
            routine_entry_id=entry.id, teacher_id=teacher.id, department_id=department.id,
            room_id=entry.room_id, policy_id=policy.id, teaching_date=local_now.date(),
            start_at=start_at, end_at=end_at, course_code=entry.course_code,
            course_title=entry.course_title, batch=entry.batch, section=entry.section,
            source_version="TEMPORARY_CURRENT_TIME_VALIDATION", reliability_state="RELIABLE",
            snapshot={"temporary_validation": True, "real_routine_entry": True, "source_file": SOURCE_FILE},
        ))

    db.commit()
    print({
        "teacher": teacher.name, "initials": "DP", "department": department.code,
        "real_routine_entries": len(entries), "temporary_validation_sessions": 4,
        "active_now_room": validation_entries[0].room_id, "active_now_course": validation_entries[0].course_code,
        "active_from": str(now - timedelta(minutes=2)), "active_until": str(now + timedelta(minutes=28)),
    })
