"""
First version of each role's home page (Stage 2).
They show real data from the database and prove that each role only sees what it is allowed to see.
Full dashboards are built in Stages 3, 4 and 7.
"""
from __future__ import annotations

import pandas as pd
import streamlit as st

from app import session
from app.components import ui
from services.access import teacher_profile_id, teacher_student_ids
from services.overview import student_profile, students_by_ids, system_counts


def student_home():
    user = session.require_role("student")
    p = student_profile(user.id)
    ui.hero(f"Welcome, {user.full_name}", "Your personal learning dashboard.", tag="Student portal")
    if p is None:
        st.warning("No student profile found for this account.")
        return
    if p["is_demo"]:
        st.info("This is a **demo account**. Its module record comes from the OULAD test set and its quiz "
                "scores are synthetic demonstration data.")
    k = st.columns(4)
    ui.kpi(k[0], "Student ID", p["student_code"])
    ui.kpi(k[1], "Enrolled courses", str(p["courses"]))
    ui.kpi(k[2], "Recorded assessments", str(p["assessments"]))
    ui.kpi(k[3], "AI prediction data", "Available" if p["has_module_record"] else "Not available",
           "Module activity record" if p["has_module_record"] else "Requires module activity data")
    st.write("")
    st.markdown(f"**Program:** {p['program'] or '—'} &nbsp;·&nbsp; **Department:** {p['department'] or '—'} "
                f"&nbsp;·&nbsp; **Semester:** {p['semester'] or '—'}")
    st.caption("Performance overview, AI prediction, recommendations and study plan are added in Stage 3.")


def teacher_home():
    user = session.require_role("teacher")
    tid = teacher_profile_id(user.id)
    ui.hero(f"Welcome, {user.full_name}", "Monitor and support your assigned students.", tag="Teacher portal")
    ids = teacher_student_ids(tid) if tid else set()
    k = st.columns(3)
    ui.kpi(k[0], "Assigned students", str(len(ids)))
    ui.kpi(k[1], "Students needing attention", "—", "Available in Stage 4")
    ui.kpi(k[2], "High predicted risk", "—", "Available in Stage 4")
    st.write("")
    st.markdown("#### Your students")
    rows = students_by_ids(ids)
    if not rows:
        st.info("No students are assigned to you yet. An administrator can assign students or courses.")
        return
    df = pd.DataFrame(rows).rename(columns={"student_code": "Student ID", "full_name": "Name",
                                            "program": "Program", "semester": "Semester", "is_demo": "Demo"})
    st.dataframe(df.drop(columns=["id"]), hide_index=True, width="stretch")
    st.caption("You can only see students assigned to you directly or through your courses.")


def admin_home():
    session.require_role("admin")
    ui.hero("Administration", "Manage users, courses, subjects and learning resources.", tag="Admin portal")
    c = system_counts()
    k = st.columns(4)
    ui.kpi(k[0], "Students", str(c["students"]))
    ui.kpi(k[1], "Teachers", str(c["teachers"]))
    ui.kpi(k[2], "Courses / subjects", f'{c["courses"]} / {c["subjects"]}')
    ui.kpi(k[3], "Topics", str(c["topics"]))
    st.write("")
    st.caption("User, course, subject, resource and assignment management are added in Stage 7.")
