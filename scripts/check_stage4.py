"""
Stage 4 verification: teacher dashboard data, permissions and teacher actions.

Run from the project folder (after scripts.seed_demo):   python -m scripts.check_stage4
Changes made by this test are removed at the end.
"""
from __future__ import annotations

import sys
from datetime import date

from sqlalchemy import delete, func, select

from db.models import (Assessment, AuditLog, Notification, Recommendation, StudentProfile, StudyPlan, Subject,
                       TeacherFeedback)
from db.session import get_session
from services import learning, teaching
from services.auth import authenticate
from services.teaching import TeacherActionError

PW = "Demo@12345"
TAG = "[stage4-test]"
ok = True


def check(passed, text):
    global ok
    ok &= bool(passed)
    print(("  [PASS] " if passed else "  [FAIL] ") + text)


def sid_of(code):
    with get_session() as s:
        return s.scalar(select(StudentProfile.id).where(StudentProfile.student_code == code))


def max_id(model):
    with get_session() as s:
        return s.scalar(select(func.max(model.id))) or 0


START = {"notification": max_id(Notification), "plan": max_id(StudyPlan)}


def cleanup():
    with get_session() as s:
        s.execute(delete(Assessment).where(Assessment.assessment_name.like(f"%{TAG}%")))
        s.execute(delete(TeacherFeedback).where(TeacherFeedback.feedback.like(f"%{TAG}%")))
        s.execute(delete(Recommendation).where(Recommendation.title.like(f"%{TAG}%")))
        s.execute(delete(Notification).where(Notification.id > START["notification"]))
        s.execute(delete(StudyPlan).where(StudyPlan.id > START["plan"], StudyPlan.created_by == "teacher"))


try:
    ta = authenticate("teacher.a@demo.example.com", PW)
    tb = authenticate("teacher.b@demo.example.com", PW)
    s1, s12 = sid_of("DEMO-0001"), sid_of("DEMO-0012")

    print("\n=== Class overview ===")
    ov_a, ov_b = teaching.class_overview(ta), teaching.class_overview(tb)
    check(len(ov_a) == 12 and len(ov_b) == 12, f"Teacher A sees {len(ov_a)} students, Teacher B sees {len(ov_b)}")
    check(set(teaching.my_subject_names(tb)) == {"Database Systems", "Discrete Mathematics"},
          "Teacher B's subjects: Database Systems, Discrete Mathematics")
    check(ov_a["Needs attention"].any() and (~ov_a["Needs attention"]).any(),
          f"Attention flag separates students ({int(ov_a['Needs attention'].sum())} need attention)")
    check((ov_a[ov_a["Needs attention"]]["Why"] != "On track").all(), "Every flagged student has a stated reason")
    perf = teaching.class_subject_performance(tb)
    check(set(perf["subject_name"]) == {"Database Systems", "Discrete Mathematics"},
          "Class performance shows only the teacher's own subjects")

    print("\n=== AI predictions for the class ===")
    n = teaching.run_predictions_for_class(tb)
    ov_b = teaching.class_overview(tb)
    check(n == 12 and (ov_b["AI prediction"] != "Not run").all(), f"Predictions run for {n} students")
    check(ov_b["High risk"].dtype == bool, f"{int(ov_b['High risk'].sum())} high-risk students flagged (risk ≥ 60%)")

    print("\n=== Permissions (subject-wise) ===")
    with get_session() as s:
        ds = s.scalar(select(Subject.id).where(Subject.subject_code == "DEMO-DS"))
    for label, fn in [
        ("record a Data Structures score", lambda: teaching.record_assessment(tb, s1, ds, None, f"x {TAG}", "quiz", 5, 10, date.today())),
        ("assign Data Structures work", lambda: teaching.assign_activity(tb, s1, f"x {TAG}", "", ds, None, "low", None)),
        ("set a Data Structures target", lambda: teaching.set_study_target(tb, s1, ds, 30, "low", None)),
        ("enter Data Structures class scores", lambda: teaching.record_class_scores(tb, ds, None, f"x {TAG}", "quiz", 10, date.today(), {s1: 5})),
    ]:
        try:
            fn()
            check(False, f"Teacher B cannot {label} (not their subject)")
        except PermissionError:
            check(True, f"Teacher B cannot {label} (not their subject)")
    teaching.record_assessment(ta, s1, ds, None, f"DS quiz {TAG}", "quiz", 15, 20, date.today())
    check(True, "Teacher A can record a Data Structures score")

    print("\n=== Teacher actions ===")
    subjects = teaching.teacher_subjects(tb)
    subj_id = int(subjects["id"].iloc[0])
    topic_id = int(subjects["topic_id"].iloc[0])
    try:
        teaching.record_assessment(tb, s1, subj_id, topic_id, f"Bad {TAG}", "quiz", 25, 20, date.today())
        check(False, "Score above maximum rejected")
    except TeacherActionError:
        check(True, "Score above maximum rejected")
    before = len(learning.assessments_frame(s1))
    teaching.record_assessment(tb, s1, subj_id, topic_id, f"Quiz 3 {TAG}", "quiz", 18, 20, date.today())
    check(len(learning.assessments_frame(s1)) == before + 1, "Score saved to the student's record")

    n = teaching.record_class_scores(tb, subj_id, topic_id, f"Class quiz {TAG}", "quiz", 10, date.today(),
                                     {sid_of(f"DEMO-{i:04d}"): (7 if i != 3 else None) for i in range(1, 6)})
    check(n == 4, "Class score entry saved 4 scores (1 student absent)")

    teaching.add_feedback(tb, s1, f"Good effort, revise joins {TAG}", subj_id, "student")
    teaching.add_feedback(tb, s1, f"Private note {TAG}", None, "private")
    visible = learning.visible_teacher_feedback(s1)
    check(visible["feedback"].str.contains("Good effort").any() and
          not visible["feedback"].str.contains("Private note").any(),
          "Student sees shared feedback but not private notes")

    teaching.assign_activity(tb, s1, f"Practice set {TAG}", "Do 10 questions", subj_id, topic_id, "high", "beginner")
    recs = learning.list_recommendations(s1, active=True)
    check(any(r.source == "teacher" and TAG in r.title for r in recs), "Assigned activity appears in the student's recommendations")

    learning.refresh_recommendations(s1)          # makes sure a system plan exists first
    teaching.set_study_target(tb, s1, subj_id, 60, "high", None)
    plan = learning.current_study_plan(s1)
    row = plan[plan["created_by"] == "teacher"]
    check(len(row) == 1 and int(row["target_minutes_per_day"].iloc[0]) == 60 and len(plan) == 4,
          "Teacher study target replaces the system suggestion for that subject")

    with get_session() as s:
        uid = s.scalar(select(StudentProfile.user_id).where(StudentProfile.id == s1))
    notes = teaching.notifications_for(uid, limit=20)
    check(len(notes) >= 4, f"Student received {len(notes)} notifications")
    teaching.log_view(tb, s1)
    with get_session() as s:
        logged = s.scalar(select(AuditLog.id).where(AuditLog.user_id == tb.id, AuditLog.action == "view_student"))
    check(logged is not None, "Teacher viewing a student report is written to the audit log")
finally:
    cleanup()

print("\n" + ("ALL CHECKS PASSED" if ok else "SOME CHECKS FAILED — send this output"))
sys.exit(0 if ok else 1)
