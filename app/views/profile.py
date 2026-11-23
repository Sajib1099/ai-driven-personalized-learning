"""My profile — every role can update their name and change their password."""
from __future__ import annotations

import streamlit as st

from app import session
from app.components import ui
from services.auth import AuthError, change_password, update_name
from services.overview import student_profile


def render():
    user = session.require_role("student", "teacher", "admin")
    ui.hero("My Profile", "Your account details and password.")

    c1, c2 = st.columns(2, gap="large")
    with c1:
        st.markdown("#### Account")
        st.markdown(f"**E-mail:** {user.email}  \n**Role:** {user.role.title()}")
        if user.role == "student":
            p = student_profile(user.id)
            if p:
                st.markdown(f"**Student ID:** {p['student_code']}  \n**Program:** {p['program'] or '—'}  \n"
                            f"**Semester:** {p['semester'] or '—'}")
        with st.form("name_form"):
            name = st.text_input("Full name", value=user.full_name, key="profile_name")
            if st.form_submit_button("Save name"):
                try:
                    update_name(user.id, name)
                    st.success("Name updated.")
                    st.rerun()
                except AuthError as e:
                    st.error(str(e))

    with c2:
        st.markdown("#### Change password")
        with st.form("password_form", clear_on_submit=True):
            current = st.text_input("Current password", type="password", key="pw_current")
            new1 = st.text_input("New password", type="password", key="pw_new1",
                                 help="At least 8 characters, with a letter and a number.")
            new2 = st.text_input("Confirm new password", type="password", key="pw_new2")
            if st.form_submit_button("Change password"):
                if new1 != new2:
                    st.error("New passwords do not match.")
                else:
                    try:
                        change_password(user.id, current, new1)
                        st.success("Password changed.")
                    except AuthError as e:
                        st.error(str(e))
