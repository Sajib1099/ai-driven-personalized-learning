"""
Stage 1b — demo data.

Run from the project folder:
    python -m scripts.seed_demo            # add demo data (safe to run again, nothing is duplicated)
    python -m scripts.seed_demo --reset    # delete all demo data, then add it again

What it creates
  - 1 admin, 2 subject teachers, 12 demo students (all e-mails end with @demo.example.com)
  - 1 example program with 4 subjects and their topics (any program can be added later)
  - Teacher A teaches Data Structures + OOP, Teacher B teaches Database Systems + Discrete Mathematics
  - Layer A: each demo student is linked to one REAL record from the held-out OULAD
    test set (3 students per actual outcome). These records were never used for training.
  - Layer B: SYNTHETIC topic quiz scores (2 rounds) so the subject-level features can be
    demonstrated. They are clearly marked as synthetic and are NOT real student data.
  - No learning-resource links are created: resources must be added and approved by a
    teacher/admin (no invented URLs).
"""
from __future__ import annotations

import argparse
import os
from datetime import date

import numpy as np
import pandas as pd
from sqlalchemy import delete, func, select

from db.models import (Assessment, Course, Enrollment, ModuleRecord, StudentProfile, Subject,
                       TeacherAssignment, TeacherProfile, Topic, User)
from db.session import describe_database, get_session
from services.auth import hash_password
from services.prediction import Predictor, load_csv

DEMO_DOMAIN = "@demo.example.com"
DEMO_PASSWORD = os.getenv("DEMO_PASSWORD", "Demo@12345")
RANDOM_SEED = 42
SYNTHETIC_NOTE = "[SYNTHETIC DEMO DATA]"

# ---------------------------------------------------------------------------
# Example academic structure (only an example — the platform accepts any course)
# ---------------------------------------------------------------------------
COURSE = {"course_code": "DEMO-SWE", "course_name": "B.Sc. in Software Engineering (Demo)",
          "department": "Software Engineering",
          "description": "Example course used for the thesis demonstration."}

SUBJECTS = [
    ("DEMO-DS", "Data Structures", 3.0,
     ["Arrays", "Linked Lists", "Stacks and Queues", "Trees", "Graphs"]),
    ("DEMO-DB", "Database Systems", 3.0,
     ["ER Modelling", "SQL Basics", "Joins", "Normalization", "Transactions"]),
    ("DEMO-OOP", "Object-Oriented Programming", 3.0,
     ["Classes and Objects", "Inheritance", "Polymorphism", "Exception Handling"]),
    ("DEMO-DM", "Discrete Mathematics", 3.0,
     ["Sets and Logic", "Relations and Functions", "Graph Theory", "Combinatorics"]),
]

SUBJECT_TEACHERS = {"teacher.a": ["DEMO-DS", "DEMO-OOP"], "teacher.b": ["DEMO-DB", "DEMO-DM"]}
STUDENTS_PER_OUTCOME = 3
OUTCOME_BASE = {"Distinction": 82, "Pass": 68, "Fail": 50, "Withdrawn": 45}   # synthetic score levels
QUIZ_ROUNDS = [("Quiz 1", date(2026, 10, 5)), ("Quiz 2", date(2026, 11, 9))]
QUIZ_TOTAL = 20.0   # one quiz per subject; its marks are split equally across the subject's topics


def get_or_create_user(s, email, full_name, role):
    user = s.scalar(select(User).where(User.email == email))
    if user:
        return user, False
    user = User(full_name=full_name, email=email, password_hash=hash_password(DEMO_PASSWORD), role=role)
    s.add(user)
    s.flush()
    return user, True


def reset_demo():
    with get_session() as s:
        n_users = s.execute(delete(User).where(User.email.like(f"%{DEMO_DOMAIN}"))).rowcount
        n_courses = s.execute(delete(Course).where(Course.course_code == COURSE["course_code"])).rowcount
    print(f"Reset: removed {n_users} demo users (and their data) and {n_courses} demo course.")


def seed():
    rng = np.random.default_rng(RANDOM_SEED)
    predictor = Predictor()
    test_students = load_csv("test_students.csv")

    with get_session() as s:
        # ---------------- Admin and teachers
        admin, _ = get_or_create_user(s, f"admin{DEMO_DOMAIN}", "System Administrator (Demo)", "admin")
        teachers = []
        for code, name, desig in [("a", "Demo Teacher A", "Lecturer"), ("b", "Demo Teacher B", "Assistant Professor")]:
            u, created = get_or_create_user(s, f"teacher.{code}{DEMO_DOMAIN}", name, "teacher")
            if created:
                s.add(TeacherProfile(user_id=u.id, department="Software Engineering", designation=desig))
                s.flush()
            teachers.append(s.scalar(select(TeacherProfile).where(TeacherProfile.user_id == u.id)))

        # ---------------- Course, subjects, topics
        course = s.scalar(select(Course).where(Course.course_code == COURSE["course_code"]))
        if course is None:
            course = Course(**COURSE)
            s.add(course)
            s.flush()
            for code, name, credit, topics in SUBJECTS:
                subj = Subject(course_id=course.id, subject_code=code, subject_name=name, credit=credit,
                               description=f"Example subject: {name}")
                s.add(subj)
                s.flush()
                for i, t in enumerate(topics):
                    s.add(Topic(subject_id=subj.id, topic_name=t, order_index=i))
            s.flush()
        subjects = s.scalars(select(Subject).where(Subject.course_id == course.id).order_by(Subject.id)).all()
        teacher_of = {code: t for t, codes in zip(teachers, SUBJECT_TEACHERS.values()) for code in codes}

        # ---------------- Demo students linked to real OULAD test-set records (3 per outcome)
        picks = pd.concat([g.sample(STUDENTS_PER_OUTCOME, random_state=RANDOM_SEED)
                           for _, g in test_students.groupby("final_result")])
        picks = picks.sample(frac=1, random_state=RANDOM_SEED).reset_index(drop=True)

        for i, rec in picks.iterrows():
            n = i + 1
            email = f"student{n:02d}{DEMO_DOMAIN}"
            user, created = get_or_create_user(s, email, f"Demo Student {n:02d}", "student")
            if not created:
                continue
            profile = StudentProfile(user_id=user.id, student_code=f"DEMO-{n:04d}",
                                     university="Daffodil International University (demo account)",
                                     department="Software Engineering", program="B.Sc. in SWE",
                                     semester="Fall 2026", enrollment_year=2024, is_demo=True)
            s.add(profile)
            s.flush()

            # Layer A: real OULAD record (37 model inputs)
            s.add(ModuleRecord(
                student_id=profile.id, source="oulad_test_set", oulad_id_student=int(rec["id_student"]),
                code_module=str(rec["code_module"]), code_presentation=str(rec["code_presentation"]),
                features={f: (str(rec[f]) if f in predictor.categorical else float(rec[f]))
                          for f in predictor.features},
                actual_result=str(rec["final_result"])))

            s.add(Enrollment(student_id=profile.id, course_id=course.id, academic_year="2026-27",
                             semester="Fall 2026"))

            # Layer B: synthetic topic quizzes — every student gets a different strength profile
            base = OUTCOME_BASE[rec["final_result"]]
            for subj in subjects:
                subject_offset = rng.normal(0, 12)
                part_max = QUIZ_TOTAL / len(subj.topics)
                teacher = teacher_of[subj.subject_code]
                for topic in subj.topics:
                    level = base + subject_offset + rng.normal(0, 8)
                    change = rng.normal(3, 6)          # some improve, some do not
                    for r, (quiz_name, quiz_date) in enumerate(QUIZ_ROUNDS):
                        pct = float(np.clip(level + r * change + rng.normal(0, 4), 5, 100))
                        s.add(Assessment(
                            student_id=profile.id, subject_id=subj.id, topic_id=topic.id,
                            assessment_name=(f"{quiz_name}, {subj.subject_name} ({QUIZ_TOTAL:.0f} marks): "
                                             f"{topic.topic_name} questions {SYNTHETIC_NOTE}"),
                            assessment_type="quiz", score=round(pct / 100 * part_max * 2) / 2,
                            maximum_score=part_max, assessment_date=quiz_date, recorded_by=teacher.user_id))

        s.flush()
        # ---------------- Subject-wise teachers: A teaches DS + OOP, B teaches DB + DM
        # (older demo databases used course/student assignments — those are replaced)
        for teacher, codes in zip(teachers, SUBJECT_TEACHERS.values()):
            s.execute(delete(TeacherAssignment).where(TeacherAssignment.teacher_id == teacher.id,
                                                      TeacherAssignment.subject_id.is_(None)))
            for code in codes:
                subj_id = s.scalar(select(Subject.id).where(Subject.subject_code == code))
                exists = s.scalar(select(TeacherAssignment.id).where(TeacherAssignment.teacher_id == teacher.id,
                                                                     TeacherAssignment.subject_id == subj_id))
                if not exists:
                    s.add(TeacherAssignment(teacher_id=teacher.id, subject_id=subj_id))


def summary():
    with get_session() as s:
        counts = {m.__tablename__: s.scalar(select(func.count()).select_from(m)) for m in
                  [User, StudentProfile, TeacherProfile, Course, Subject, Topic, Enrollment,
                   TeacherAssignment, ModuleRecord, Assessment]}
        print("\nRows per table:")
        for t, c in counts.items():
            print(f"  {t:22s} {c}")

        print("\nDemo students (subject averages from the latest quiz, SYNTHETIC):")
        print(f"  {'Code':10s} {'OULAD outcome':14s} {'Strongest subject':36s} {'Weakest subject'}")
        profiles = s.scalars(select(StudentProfile).where(StudentProfile.is_demo.is_(True))
                             .order_by(StudentProfile.student_code)).all()
        for p in profiles:
            mr = s.scalar(select(ModuleRecord).where(ModuleRecord.student_id == p.id))
            rows = s.execute(
                select(Subject.subject_name, func.avg(Assessment.score / Assessment.maximum_score * 100))
                .join(Subject, Subject.id == Assessment.subject_id)
                .where(Assessment.student_id == p.id, Assessment.assessment_date == QUIZ_ROUNDS[-1][1])
                .group_by(Subject.subject_name)).all()
            best = max(rows, key=lambda r: r[1])
            worst = min(rows, key=lambda r: r[1])
            best_s, worst_s = f"{best[0]} ({best[1]:.0f}%)", f"{worst[0]} ({worst[1]:.0f}%)"
            print(f"  {p.student_code:10s} {mr.actual_result:14s} {best_s:36s} {worst_s}")

    print("\nDemo logins (password for all: " + DEMO_PASSWORD + ")")
    print(f"  admin{DEMO_DOMAIN}")
    print(f"  teacher.a{DEMO_DOMAIN}   (teaches Data Structures + Object-Oriented Programming)")
    print(f"  teacher.b{DEMO_DOMAIN}   (teaches Database Systems + Discrete Mathematics)")
    print(f"  student01{DEMO_DOMAIN} ... student12{DEMO_DOMAIN}")
    print("Login pages are added in Stage 2.")


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Add demo data to the database.")
    parser.add_argument("--reset", action="store_true", help="delete demo data first")
    args = parser.parse_args()

    print("Using", describe_database())
    if args.reset:
        reset_demo()
    seed()
    summary()
    print("\nDone.")
