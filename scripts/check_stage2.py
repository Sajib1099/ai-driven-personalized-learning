"""
Stage 2 verification: login, registration, roles and data access rules.

Run from the project folder (after scripts.seed_demo):   python -m scripts.check_stage2
Temporary test accounts are deleted at the end.
"""
from __future__ import annotations

import sys

from sqlalchemy import delete, select

from db.models import StudentProfile, Subject, TeacherProfile, User
from db.session import get_session
from services.access import (can_edit_subject, can_view_student, student_profile_id, teacher_profile_id,
                             teacher_student_ids)
from services.auth import AuthError, authenticate, hash_password, register_student

DEMO_PW = "Demo@12345"
TMP = "@stage2-test.example.com"
ok = True


def check(passed: bool, text: str):
    global ok
    ok &= bool(passed)
    print(("  [PASS] " if passed else "  [FAIL] ") + text)


def raises(fn, *args) -> str | None:
    try:
        fn(*args)
    except AuthError as e:
        return str(e)
    return None


def cleanup():
    with get_session() as s:
        s.execute(delete(User).where(User.email.like(f"%{TMP}")))


cleanup()
try:
    print("\n=== Login ===")
    for email, role in [("admin@demo.example.com", "admin"), ("teacher.a@demo.example.com", "teacher"),
                        ("student01@demo.example.com", "student")]:
        u = authenticate(email, DEMO_PW)
        check(u.role == role, f"{email} logs in as {role}")
    check(raises(authenticate, "student01@demo.example.com", "wrong-password1") == "Incorrect e-mail or password.",
          "Wrong password rejected")
    check(raises(authenticate, "nobody@demo.example.com", DEMO_PW) == "Incorrect e-mail or password.",
          "Unknown e-mail gives the same message (does not reveal which e-mails exist)")
    check(authenticate("  STUDENT01@demo.example.com ", DEMO_PW).role == "student", "E-mail is case-insensitive")

    print("\n=== Registration ===")
    u = register_student("Test Student", f"new{TMP}", "Abcdef12", "TEST-0001", "SWE", "BSc", "Fall 2026", 2024)
    check(u.role == "student", "New student can register and gets the student role")
    check(authenticate(f"new{TMP}", "Abcdef12").id == u.id, "New student can log in")
    check(raises(register_student, "Another", f"new{TMP}", "Abcdef12", "TEST-0002") is not None,
          "Duplicate e-mail rejected")
    check(raises(register_student, "Another", f"b{TMP}", "Abcdef12", "TEST-0001") is not None,
          "Duplicate student ID rejected")
    check(raises(register_student, "Another", f"c{TMP}", "short1", "TEST-0003") is not None,
          "Short password rejected")
    check(raises(register_student, "Another", f"d{TMP}", "onlyletters", "TEST-0004") is not None,
          "Password without a number rejected")
    check(raises(register_student, "Another", "not-an-email", "Abcdef12", "TEST-0005") is not None,
          "Invalid e-mail rejected")

    print("\n=== Disabled account and lockout ===")
    with get_session() as s:
        s.add(User(full_name="Disabled User", email=f"disabled{TMP}", password_hash=hash_password("Abcdef12"),
                   role="student", account_status="disabled"))
        s.add(User(full_name="Lockout User", email=f"lock{TMP}", password_hash=hash_password("Abcdef12"),
                   role="student"))
    check("disabled" in (raises(authenticate, f"disabled{TMP}", "Abcdef12") or ""), "Disabled account cannot log in")
    for _ in range(5):
        raises(authenticate, f"lock{TMP}", "Wrong-pass1")
    check("Too many failed attempts" in (raises(authenticate, f"lock{TMP}", "Abcdef12") or ""),
          "After 5 wrong passwords the account is locked for 10 minutes (even with the right password)")

    print("\n=== Data access rules ===")
    with get_session() as s:
        codes = dict(s.execute(select(StudentProfile.student_code, StudentProfile.id)).all())
        subj = dict(s.execute(select(Subject.subject_code, Subject.id)).all())
    s1, s2 = codes["DEMO-0001"], codes["DEMO-0002"]
    student1 = authenticate("student01@demo.example.com", DEMO_PW)
    teacher_a = authenticate("teacher.a@demo.example.com", DEMO_PW)
    teacher_b = authenticate("teacher.b@demo.example.com", DEMO_PW)
    admin = authenticate("admin@demo.example.com", DEMO_PW)
    check(student_profile_id(student1.id) == s1, "student01 is linked to DEMO-0001")
    check(can_view_student(student1, s1) and not can_view_student(student1, s2),
          "A student can see only their own data")
    check(len(teacher_student_ids(teacher_profile_id(teacher_a.id))) == 12 and
          len(teacher_student_ids(teacher_profile_id(teacher_b.id))) == 12,
          "Both subject teachers see the 12 students enrolled in their program")
    check(can_edit_subject(teacher_a, s1, subj["DEMO-DS"]) and not can_edit_subject(teacher_a, s1, subj["DEMO-DB"]),
          "Teacher A can edit Data Structures but not Database Systems")
    check(can_edit_subject(teacher_b, s1, subj["DEMO-DB"]) and not can_edit_subject(teacher_b, s1, subj["DEMO-OOP"]),
          "Teacher B can edit Database Systems but not OOP")
    check(not can_edit_subject(student1, s1, subj["DEMO-DS"]), "A student cannot edit scores, even their own")

    # a teacher with no assignments and a student in no program
    with get_session() as s:
        tu = User(full_name="Unassigned Teacher", email=f"teacher{TMP}", password_hash=hash_password("Abcdef12"),
                  role="teacher")
        s.add(tu)
        s.flush()
        s.add(TeacherProfile(user_id=tu.id))
    lonely = register_student("Lonely Student", f"lonely{TMP}", "Abcdef12", "TEST-LONELY")
    t_none = authenticate(f"teacher{TMP}", "Abcdef12")
    lonely_id = student_profile_id(lonely.id)
    check(len(teacher_student_ids(teacher_profile_id(t_none.id))) == 0 and not can_view_student(t_none, s1),
          "A teacher with no assigned subjects sees no students")
    check(not can_view_student(teacher_a, lonely_id), "A teacher cannot see a student outside their programs")
    check(can_view_student(admin, lonely_id), "Admin can see every student")
finally:
    cleanup()

print("\n" + ("ALL CHECKS PASSED" if ok else "SOME CHECKS FAILED — send this output"))
sys.exit(0 if ok else 1)
