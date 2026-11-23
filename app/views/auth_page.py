"""Sign-in and student registration screen (shown when nobody is logged in)."""
from __future__ import annotations

import streamlit as st

from app import session
from app.components import ui
from services.auth import AuthError, authenticate, register_student


def render():
    left, mid, right = st.columns([1, 1.5, 1])
    with mid:
        st.markdown(
            '<div class="login-brand"><div class="login-logo">🎓</div>'
            '<h1>AI Personalized Learning Platform</h1>'
            '<p>Performance prediction · Explainable AI · Personalised recommendations</p></div>',
            unsafe_allow_html=True)

        sign_in, register = st.tabs(["Sign in", "Student registration"])

        with sign_in:
            with st.form("login_form", border=True):
                email = st.text_input("E-mail", placeholder="name@example.com", key="login_email")
                password = st.text_input("Password", type="password", key="login_password")
                submitted = st.form_submit_button("Sign in", type="primary", width="stretch")
            if submitted:
                try:
                    user = authenticate(email, password)
                except AuthError as e:
                    st.error(str(e))
                else:
                    session.login(user)
                    st.rerun()

            with st.expander("Demo accounts (for the thesis demonstration)"):
                st.markdown(
                    "Password for all demo accounts: **`Demo@12345`**\n\n"
                    "| Role | E-mail |\n|---|---|\n"
                    "| Admin | `admin@demo.example.com` |\n"
                    "| Teacher (Data Structures, OOP) | `teacher.a@demo.example.com` |\n"
                    "| Teacher (Database, Discrete Math) | `teacher.b@demo.example.com` |\n"
                    "| Student | `student01@demo.example.com` … `student12@demo.example.com` |")

        with register:
            st.caption("Teachers and administrators are created by an administrator.")
            with st.form("register_form", border=True):
                full_name = st.text_input("Full name", key="reg_name")
                c1, c2 = st.columns(2)
                student_code = c1.text_input("Student ID", placeholder="e.g. 0242310005341099", key="reg_code")
                email = c2.text_input("E-mail", placeholder="name@example.com", key="reg_email")
                c3, c4 = st.columns(2)
                department = c3.text_input("Department", value="Software Engineering", key="reg_dept")
                program = c4.text_input("Program", value="B.Sc. in Software Engineering", key="reg_program")
                c5, c6 = st.columns(2)
                semester = c5.text_input("Current semester", placeholder="e.g. Fall 2026", key="reg_semester")
                year = c6.number_input("Enrollment year", min_value=2000, max_value=2100, value=2024, step=1, key="reg_year")
                p1, p2 = st.columns(2)
                pw1 = p1.text_input("Password", type="password", key="reg_pw1",
                                  help="At least 8 characters, with a letter and a number.")
                pw2 = p2.text_input("Confirm password", type="password", key="reg_pw2")
                agree = st.checkbox("I agree that my academic data is stored and used to give me learning "
                                    "recommendations.", key="reg_agree")
                submitted = st.form_submit_button("Create student account", type="primary", width="stretch")
            if submitted:
                if pw1 != pw2:
                    st.error("Passwords do not match.")
                elif not agree:
                    st.error("Please accept the data-use statement to create an account.")
                else:
                    try:
                        user = register_student(full_name, email, pw1, student_code, department, program,
                                                semester, int(year))
                    except AuthError as e:
                        st.error(str(e))
                    else:
                        session.login(user)
                        st.success("Account created.")
                        st.rerun()
