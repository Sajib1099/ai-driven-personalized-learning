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
from app.views import auth_page, home, profile  # noqa: E402

ui.inject_css()
user = session.current_user()

# ----------------------------------------------------------------- not logged in
if user is None:
    auth_page.render()
    st.stop()

# ----------------------------------------------------------------- role-based pages
profile_page = st.Page(profile.render, title="My Profile", icon="👤", url_path="profile")
PAGES = {
    "student": [st.Page(home.student_home, title="Dashboard", icon="🏠", url_path="student", default=True),
                profile_page],
    "teacher": [st.Page(home.teacher_home, title="Dashboard", icon="🏠", url_path="teacher", default=True),
                profile_page],
    "admin": [st.Page(home.admin_home, title="Dashboard", icon="🏠", url_path="admin", default=True),
              profile_page],
}
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
