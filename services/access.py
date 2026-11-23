"""
Authorization rules (who may see or change which student's data).

  student : only their own records
  teacher : VIEW  students enrolled in a program where the teacher teaches a subject,
                  students in a program the teacher is responsible for, or students they advise
            EDIT  (scores, activities, study targets) only in subjects they are responsible for
  admin   : everyone, every subject

Every page that shows or changes student data must use these functions.
"""
from __future__ import annotations

from sqlalchemy import select

from db.models import Enrollment, StudentProfile, Subject, TeacherAssignment, TeacherProfile
from db.session import get_session
from services.auth import CurrentUser


def student_profile_id(user_id: int) -> int | None:
    with get_session() as s:
        return s.scalar(select(StudentProfile.id).where(StudentProfile.user_id == user_id))


def teacher_profile_id(user_id: int) -> int | None:
    with get_session() as s:
        return s.scalar(select(TeacherProfile.id).where(TeacherProfile.user_id == user_id))


def _assignments(s, teacher_id: int):
    return s.execute(select(TeacherAssignment.student_id, TeacherAssignment.course_id, TeacherAssignment.subject_id)
                     .where(TeacherAssignment.teacher_id == teacher_id)).all()


def _active_students_in(s, course_ids: set[int]) -> set[int]:
    if not course_ids:
        return set()
    return set(s.scalars(select(Enrollment.student_id).where(Enrollment.course_id.in_(course_ids),
                                                              Enrollment.enrollment_status == "active")))


def teacher_student_ids(teacher_id: int) -> set[int]:
    """Student profile ids a teacher may VIEW."""
    with get_session() as s:
        rows = _assignments(s, teacher_id)
        direct = {r.student_id for r in rows if r.student_id}
        course_ids = {r.course_id for r in rows if r.course_id}
        subject_ids = {r.subject_id for r in rows if r.subject_id}
        if subject_ids:
            course_ids |= set(s.scalars(select(Subject.course_id).where(Subject.id.in_(subject_ids))))
        return direct | _active_students_in(s, course_ids)


def teacher_subject_ids(teacher_id: int, student_id: int | None = None) -> set[int]:
    """Subjects a teacher may EDIT (optionally: for one student)."""
    with get_session() as s:
        rows = _assignments(s, teacher_id)
        subjects = {r.subject_id for r in rows if r.subject_id}
        course_ids = {r.course_id for r in rows if r.course_id}
        if student_id is not None and student_id in {r.student_id for r in rows if r.student_id}:
            course_ids |= set(s.scalars(select(Enrollment.course_id).where(Enrollment.student_id == student_id)))
        if course_ids:
            subjects |= set(s.scalars(select(Subject.id).where(Subject.course_id.in_(course_ids))))
        if student_id is not None:   # only subjects of programs the student is enrolled in
            student_courses = set(s.scalars(select(Enrollment.course_id).where(Enrollment.student_id == student_id)))
            subjects = set(s.scalars(select(Subject.id).where(Subject.id.in_(subjects),
                                                              Subject.course_id.in_(student_courses)))) \
                if subjects and student_courses else set()
        return subjects


def can_view_student(user: CurrentUser, student_id: int) -> bool:
    if user.role == "admin":
        return True
    if user.role == "student":
        return student_profile_id(user.id) == student_id
    if user.role == "teacher":
        tid = teacher_profile_id(user.id)
        return tid is not None and student_id in teacher_student_ids(tid)
    return False


def can_edit_subject(user: CurrentUser, student_id: int, subject_id: int | None) -> bool:
    """May this user record scores / assign work for this student in this subject?
    subject_id=None means a general item (allowed for anyone who can view the student)."""
    if not can_view_student(user, student_id) or user.role == "student":
        return False
    if user.role == "admin" or subject_id is None:
        return True
    tid = teacher_profile_id(user.id)
    return subject_id in teacher_subject_ids(tid, student_id)
