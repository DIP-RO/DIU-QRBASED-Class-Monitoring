import pytest
from backend.sources import normalize_batch,parse_time
def test_am_pm_boundaries():
    assert parse_time("12:00 AM")=="00:00"; assert parse_time("12:00 PM")=="12:00"; assert parse_time("1.30 pm")=="13:30"
def test_alias_shapes_and_quarantine():
    rows=[{"department":"CSE","teacher_initial":"AA","course_code":"C1","weekday":"Monday","start_time":"10:00 AM","end_time":"11:30 AM","room":"AB 1"},{"department":"CSE"}]
    accepted,errors=normalize_batch(rows)
    assert accepted[0]["room"]=="AB1" and accepted[0]["teacher_alias"]=="AA"
    assert len(errors)==1 and "Missing" in errors[0]["error"]
def test_reject_implicit_overnight():
    rows=[{"department":"CSE","teacherInitial":"AA","courseCode":"C1","weekday":"Monday","startTime":"11:00 PM","endTime":"1:00 AM","room":"1"}]
    assert normalize_batch(rows)[1]

