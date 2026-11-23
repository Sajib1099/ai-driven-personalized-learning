"""
Stage 7 verification: admin portal and learning-resource workflow.

Run from the project folder (after scripts.seed_demo):   python -m scripts.check_stage7
Everything created by this test is removed at the end.
"""
from __future__ import annotations

import sys

from sqlalchemy import delete, select

from db.models import Course, LearningResource, StudentProfile, Subject, User
from db.session import get_session
from services import admin, learning
from services.access import can_edit_subject, can_view_student, student_profile_id, teacher_profile_id
from services.admin import AdminError
from services.auth import AuthError, authenticate

PW = "Demo@12345"
TMP = "@stage7-test.example.com"
ok = True


def check(passed, text):
    global ok
    ok &= bool(passed)
    print(("  [PASS] " if passed else "  [FAIL] ") + text)


def expect(exc, fn, text):
    try:
        fn()
        check(False, text)
    except exc:
        check(True, text)


def cleanup():
    with get_session() as s:
        s.execute(delete(User).where(User.email.like(f"%{TMP}")))
        s.execute(delete(Course).where(Course.course_code == "TEST-PROG"))
        s.execute(delete(LearningResource).where(LearningResource.url.like("https://example.org/stage7%")))


cleanup()
try:
    adm = authenticate("admin@demo.example.com", PW)
    ta = authenticate("teacher.a@demo.example.com", PW)
    st1 = authenticate("student01@demo.example.com", PW)

    print("\n=== Only admins can administer ===")
    expect(PermissionError, lambda: admin.list_users(ta), "Teacher cannot open user management")
    expect(PermissionError, lambda: admin.create_program(st1, "X1", "X"), "Student cannot create a program")

    print("\n=== Users ===")
    tid_user = admin.create_user(adm, "teacher", "New Teacher", f"newteacher{TMP}", "Teach1234",
                                 department="SWE", designation="Lecturer")
    new_teacher = authenticate(f"newteacher{TMP}", "Teach1234")
    check(new_teacher.role == "teacher", "Admin creates a teacher account that can log in")
    sid_user = admin.create_user(adm, "student", "New Student", f"newstudent{TMP}", "Study1234", student_code="T7-001")
    check(student_profile_id(sid_user) is not None, "Admin creates a student account with a profile")
    expect(AdminError, lambda: admin.create_user(adm, "student", "Dup", f"newstudent{TMP}", "Study1234",
                                                 student_code="T7-002"), "Duplicate e-mail rejected")
    admin.set_account_status(adm, sid_user, "disabled")
    expect(AuthError, lambda: authenticate(f"newstudent{TMP}", "Study1234"), "Disabled account cannot log in")
    admin.set_account_status(adm, sid_user, "active")
    admin.reset_password(adm, sid_user, "NewPass123")
    check(authenticate(f"newstudent{TMP}", "NewPass123").id == sid_user, "Re-enabled account works with reset password")
    expect(AdminError, lambda: admin.set_account_status(adm, adm.id, "disabled"), "Admin cannot disable own account")

    print("\n=== Programs, subjects, topics (any subject) ===")
    pid = admin.create_program(adm, "TEST-PROG", "Test Program in Business Studies", "Business")
    sub = admin.create_subject(adm, pid, "TEST-ACC101", "Principles of Accounting", 3)
    t1 = admin.add_topic(adm, sub, "Journal Entries")
    t2 = admin.add_topic(adm, sub, "Trial Balance")
    check(list(admin.list_topics(sub)["topic_name"]) == ["Journal Entries", "Trial Balance"],
          "A non-SWE subject with topics can be created without code changes")
    expect(AdminError, lambda: admin.add_topic(adm, sub, "Trial Balance"), "Duplicate topic rejected")
    admin.rename_topic(adm, t2, "Trial Balance and Errors")
    admin.delete_topic(adm, t1)
    check(list(admin.list_topics(sub)["topic_name"]) == ["Trial Balance and Errors"], "Topic rename and delete work")

    print("\n=== Enrollment and teacher subjects ===")
    new_sid = student_profile_id(sid_user)
    new_tid = teacher_profile_id(tid_user)
    new_teacher = authenticate(f"newteacher{TMP}", "Teach1234")
    check(not can_view_student(new_teacher, new_sid), "Before assignment the new teacher sees nobody")
    admin.enroll_students(adm, pid, [new_sid], "2026-27", "Fall 2026")
    admin.set_teacher_subjects(adm, new_tid, [sub])
    check(can_view_student(new_teacher, new_sid) and can_edit_subject(new_teacher, new_sid, sub),
          "After enrollment + subject assignment the teacher can see and edit that student")
    with get_session() as s:
        demo1 = s.scalar(select(StudentProfile.id).where(StudentProfile.student_code == "DEMO-0001"))
    check(not can_view_student(new_teacher, demo1), "The new teacher still cannot see students of other programs")
    admin.set_teacher_subjects(adm, new_tid, [])
    check(not can_view_student(new_teacher, new_sid), "Removing the subject removes access")

    print("\n=== Learning resources ===")
    with get_session() as s:
        ds = s.scalar(select(Subject.id).where(Subject.subject_code == "DEMO-DS"))
        db = s.scalar(select(Subject.id).where(Subject.subject_code == "DEMO-DB"))
    expect(AdminError, lambda: admin.add_resource(ta, ds, None, "Bad link", "video", "en", "not-a-url", "beginner"),
           "Invalid link rejected")
    expect(PermissionError, lambda: admin.add_resource(ta, db, None, "Not my subject", "video", "en",
                                                       "https://example.org/stage7-db", "beginner"),
           "Teacher A cannot add a resource for Database Systems")
    learning.refresh_recommendations(demo1)
    ds_topic = learning.list_recommendations(demo1, active=True)
    ds_rec = next((r for r in ds_topic if r.subject == "Data Structures"), None)
    with get_session() as s:
        from db.models import Recommendation
        rec_topic = s.scalar(select(Recommendation.topic_id).where(Recommendation.id == ds_rec.id)) if ds_rec else None
    rid = admin.add_resource(ta, ds, rec_topic, "Stage 7 test video", "video", "bn",
                             "https://example.org/stage7-video", "beginner")
    check(admin.list_resources("pending").query("id == @rid").shape[0] == 1, "Teacher's resource waits for approval")
    before = next(r for r in learning.list_recommendations(demo1, active=True) if r.id == ds_rec.id).resources
    check(not any(x["url"].endswith("stage7-video") for x in before), "Students do not see pending resources")
    admin.review_resource(adm, rid, True)
    after = next(r for r in learning.list_recommendations(demo1, active=True) if r.id == ds_rec.id).resources
    check(any(x["url"].endswith("stage7-video") for x in after),
          "After approval the resource appears in the student's open recommendation")
    rid2 = admin.add_resource(adm, ds, None, "Admin resource", "pdf", "en", "https://example.org/stage7-pdf", "advanced")
    check(admin.list_resources("approved").query("id == @rid2").shape[0] == 1, "Admin-added resource is approved directly")

    print("\n=== Audit log ===")
    log = admin.audit_log(adm, 50)
    check({"create_teacher", "set_teacher_subjects", "approve_resource"} <= set(log["action"]),
          "Admin actions are written to the audit log")
finally:
    cleanup()

print("\n" + ("ALL CHECKS PASSED" if ok else "SOME CHECKS FAILED — send this output"))
sys.exit(0 if ok else 1)
