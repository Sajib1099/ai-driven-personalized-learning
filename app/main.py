"""
AI Personalized Learning Platform — Streamlit entry point.

Run from the project folder:   streamlit run app/main.py
"""
from __future__ import annotations

import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))          # make services/, db/ and app/ importable

import streamlit as st  # noqa: E402

st.set_page_config(page_title="AI Personalized Learning Platform", page_icon="🎓", layout="wide")

from app import session  # noqa: E402
from app.components import ui  # noqa: E402
from app.views import admin, auth_page, profile, student, teacher  # noqa: E402

ui.inject_css()
user = session.current_user()

# ----------------------------------------------------------------- not logged in
if user is None:
    auth_page.render()
    st.stop()

# ----------------------------------------------------------------- role-based pages
profile_page = st.Page(profile.render, title="My Profile", icon="👤", url_path="profile")
PAGES = {
    "student": [st.Page(student.dashboard, title="Dashboard", icon="🏠", url_path="student", default=True),
                st.Page(student.performance, title="My Performance", icon="📈", url_path="performance"),
                st.Page(student.recommendations, title="Recommendations", icon="💡", url_path="recommendations"),
                st.Page(student.study_plan, title="Study Plan", icon="🗓️", url_path="study-plan"),
                st.Page(student.ai_prediction, title="AI Prediction", icon="🤖", url_path="ai-prediction"),
                profile_page],
    "teacher": [st.Page(teacher.dashboard, title="Class Dashboard", icon="🏠", url_path="teacher", default=True),
                st.Page(teacher.student_detail, title="Student Detail", icon="🧑‍🎓", url_path="student-detail"),
                st.Page(teacher.record_scores, title="Record Class Scores", icon="📝", url_path="record-scores"),
                st.Page(teacher.resources, title="Learning Resources", icon="📚", url_path="teacher-resources"),
                profile_page],
    "admin": [st.Page(admin.dashboard, title="Dashboard", icon="🏠", url_path="admin", default=True),
              st.Page(admin.users, title="Users", icon="👥", url_path="users"),
              st.Page(admin.academics, title="Programs & Teachers", icon="🎓", url_path="academics"),
              st.Page(admin.resources, title="Learning Resources", icon="📚", url_path="resources"),
              st.Page(admin.audit, title="Audit Log", icon="🗒️", url_path="audit"),
              profile_page],
}
if user.role == "teacher":
    teacher.PAGES["detail"] = PAGES["teacher"][1]
nav = st.navigation(PAGES[user.role])

with st.sidebar:
    st.markdown(f"**{ui.esc(user.full_name)}**  \n<span class='role-badge'>{user.role.title()}</span>",
                unsafe_allow_html=True)
    st.caption(user.email)
    if st.button("Log out", width="stretch"):
        session.logout()
        st.rerun()
    st.divider()
    st.caption("🎓 AI Personalized Learning Platform  \nSajib Sarker · Software Engineering  \n"
               "Daffodil International University")

nav.run()
