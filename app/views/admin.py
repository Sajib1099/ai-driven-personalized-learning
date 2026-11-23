"""Admin portal pages."""
from __future__ import annotations

import pandas as pd
import streamlit as st

from app import session
from app.components import ui
from services import admin
from services.admin import AdminError
from services.overview import system_counts


def _me():
    return session.require_role("admin")


def _run(fn, success: str):
    """Call an admin action and show a friendly message."""
    try:
        fn()
    except (AdminError, PermissionError) as e:
        st.error(str(e))
        return False
    st.success(success)
    return True


# ---------------------------------------------------------------- Dashboard
def dashboard():
    user = _me()
    ui.hero("Administration", "Manage users, programs, subjects, teachers and learning resources.",
            tag="Admin portal")
    c = system_counts()
    pending = admin.list_resources("pending")
    k = st.columns(4)
    ui.kpi(k[0], "Students", str(c["students"]))
    ui.kpi(k[1], "Teachers", str(c["teachers"]))
    ui.kpi(k[2], "Programs / subjects / topics", f'{c["courses"]} / {c["subjects"]} / {c["topics"]}')
    ui.kpi(k[3], "Resources waiting for review", str(len(pending)), "Approve them in Learning Resources")
    st.write("")
    st.markdown("#### Teachers and their subjects")
    m = admin.teacher_subject_map()
    if m.empty:
        st.info("No subjects are assigned to teachers yet.")
    else:
        st.dataframe(m.groupby("teacher")["subject_name"].apply(", ".join).reset_index()
                     .rename(columns={"teacher": "Teacher", "subject_name": "Subjects"}),
                     hide_index=True, width="stretch")
    st.markdown("#### Recent activity")
    log = admin.audit_log(user, 8)
    log.columns = ["Time", "User", "Action", "Item", "ID"]
    st.dataframe(log, hide_index=True, width="stretch")


# ---------------------------------------------------------------- Users
def users():
    user = _me()
    ui.hero("Users", "Create accounts, disable access and reset passwords.")
    df = admin.list_users(user)
    c1, c2 = st.columns(2)
    role = c1.selectbox("Role", ["All", "student", "teacher", "admin"], format_func=str.title)
    status = c2.selectbox("Status", ["All", "active", "disabled"], format_func=str.title)
    view = df if role == "All" else df[df["role"] == role]
    view = view if status == "All" else view[view["account_status"] == status]
    show = view.rename(columns={"full_name": "Name", "email": "E-mail", "role": "Role", "account_status": "Status",
                                "last_login_at": "Last login", "student_code": "Student ID",
                                "designation": "Designation"}).drop(columns=["id"])
    st.dataframe(show, hide_index=True, width="stretch")

    t1, t2 = st.tabs(["➕ Create account", "🔧 Manage an account"])
    with t1:
        with st.form("create_user", clear_on_submit=True):
            c1, c2 = st.columns(2)
            new_role = c1.selectbox("Role", ["teacher", "student", "admin"], format_func=str.title)
            name = c2.text_input("Full name")
            c3, c4 = st.columns(2)
            email = c3.text_input("E-mail")
            pw = c4.text_input("Temporary password", type="password",
                               help="At least 8 characters with a letter and a number. Ask the user to change it.")
            c5, c6, c7 = st.columns(3)
            dept = c5.text_input("Department", value="Software Engineering")
            code = c6.text_input("Student ID (students only)")
            desig = c7.text_input("Designation (teachers only)", placeholder="e.g. Lecturer")
            if st.form_submit_button("Create account", type="primary"):
                _run(lambda: admin.create_user(user, new_role, name, email, pw, student_code=code, department=dept,
                                               designation=desig), f"{new_role.title()} account created.")
    with t2:
        opts = dict(zip(df["id"], df["full_name"] + " · " + df["email"] + " · " + df["role"]))
        uid = st.selectbox("Account", list(opts), format_func=lambda i: opts[i])
        current = df.set_index("id").at[uid, "account_status"]
        c1, c2 = st.columns(2)
        with c1:
            st.markdown(f"Status: **{current}**")
            if current == "active":
                if st.button("Disable account", width="stretch"):
                    if _run(lambda: admin.set_account_status(user, uid, "disabled"), "Account disabled."):
                        st.rerun()
            elif st.button("Enable account", width="stretch"):
                if _run(lambda: admin.set_account_status(user, uid, "active"), "Account enabled."):
                    st.rerun()
        with c2:
            with st.form("reset_pw", clear_on_submit=True):
                new_pw = st.text_input("New temporary password", type="password")
                if st.form_submit_button("Reset password"):
                    _run(lambda: admin.reset_password(user, uid, new_pw), "Password reset.")


# ---------------------------------------------------------------- Academic structure
def academics():
    user = _me()
    ui.hero("Programs, Subjects & Teachers", "Build the academic structure, enroll students and assign "
                                             "subjects to teachers. Works for any program or subject.")
    t1, t2, t3, t4 = st.tabs(["🎓 Programs", "📚 Subjects & topics", "🧑‍🎓 Enrollments", "🧑‍🏫 Teacher subjects"])
    programs = admin.list_programs()

    with t1:
        st.dataframe(programs.rename(columns={"course_code": "Code", "course_name": "Program",
                                              "department": "Department", "subjects": "Subjects"})
                     .drop(columns=["id"]), hide_index=True, width="stretch")
        with st.form("new_program", clear_on_submit=True):
            st.markdown("**Add a program**")
            c1, c2, c3 = st.columns([1, 2, 1.5])
            code = c1.text_input("Code", placeholder="e.g. BSC-SWE")
            name = c2.text_input("Program name", placeholder="e.g. B.Sc. in Software Engineering")
            dept = c3.text_input("Department", value="Software Engineering")
            if st.form_submit_button("Add program", type="primary"):
                if _run(lambda: admin.create_program(user, code, name, dept), "Program added."):
                    st.rerun()

    if programs.empty:
        for t in (t2, t3, t4):
            with t:
                st.info("Add a program first.")
        return
    p_opts = dict(zip(programs["id"], programs["course_name"]))

    with t2:
        pid = st.selectbox("Program", list(p_opts), format_func=lambda i: p_opts[i], key="subj_prog")
        subs = admin.list_subjects(pid)
        st.dataframe(subs.rename(columns={"subject_code": "Code", "subject_name": "Subject", "credit": "Credit",
                                          "topics": "Topics"}).drop(columns=["id", "course_name"]),
                     hide_index=True, width="stretch")
        with st.form("new_subject", clear_on_submit=True):
            st.markdown("**Add a subject**")
            c1, c2, c3 = st.columns([1, 2, 0.8])
            scode = c1.text_input("Code", placeholder="e.g. SE231")
            sname = c2.text_input("Subject name", placeholder="e.g. Database Management System")
            credit = c3.number_input("Credit", min_value=0.0, max_value=10.0, value=3.0, step=0.5)
            if st.form_submit_button("Add subject", type="primary"):
                if _run(lambda: admin.create_subject(user, pid, scode, sname, credit), "Subject added."):
                    st.rerun()
        if len(subs):
            st.markdown("**Topics**")
            s_opts = dict(zip(subs["id"], subs["subject_name"]))
            sid = st.selectbox("Subject", list(s_opts), format_func=lambda i: s_opts[i], key="topic_subj")
            tops = admin.list_topics(sid)
            c1, c2 = st.columns([1.2, 1], gap="large")
            with c1:
                st.dataframe(tops.rename(columns={"topic_name": "Topic", "order_index": "Order"}).drop(columns=["id"]),
                             hide_index=True, width="stretch")
            with c2:
                with st.form("new_topic", clear_on_submit=True):
                    tname = st.text_input("New topic", placeholder="e.g. Normalization")
                    if st.form_submit_button("Add topic"):
                        if _run(lambda: admin.add_topic(user, sid, tname), "Topic added."):
                            st.rerun()
                if len(tops):
                    t_opts = dict(zip(tops["id"], tops["topic_name"]))
                    tid = st.selectbox("Edit topic", list(t_opts), format_func=lambda i: t_opts[i])
                    new_name = st.text_input("Rename to", value=t_opts[tid], key=f"rename_{tid}")
                    b1, b2 = st.columns(2)
                    if b1.button("Rename", width="stretch"):
                        if _run(lambda: admin.rename_topic(user, tid, new_name), "Topic renamed."):
                            st.rerun()
                    if b2.button("Delete", width="stretch"):
                        st.session_state["confirm_delete_topic"] = tid
                    if st.session_state.get("confirm_delete_topic") == tid:
                        st.warning("Delete this topic? Existing scores are kept but lose their topic link.")
                        if st.button("Yes, delete topic", type="primary"):
                            st.session_state.pop("confirm_delete_topic")
                            if _run(lambda: admin.delete_topic(user, tid), "Topic deleted."):
                                st.rerun()

    with t3:
        pid3 = st.selectbox("Program", list(p_opts), format_func=lambda i: p_opts[i], key="enr_prog")
        enr = admin.list_enrollments(pid3)
        if enr.empty:
            st.info("No students enrolled yet.")
        else:
            st.dataframe(enr.rename(columns={"student_code": "Student ID", "full_name": "Name",
                                             "academic_year": "Year", "semester": "Semester",
                                             "enrollment_status": "Status"}).drop(columns=["id", "student_id"]),
                         hide_index=True, width="stretch")
        students = admin.all_students()
        enrolled = set(enr["student_id"]) if len(enr) else set()
        free = students[~students["id"].isin(enrolled)]
        with st.form("enroll", clear_on_submit=True):
            st.markdown("**Enroll students**")
            s_opts = dict(zip(free["id"], free["student_code"] + " · " + free["full_name"]))
            picks = st.multiselect("Students not yet in this program", list(s_opts), format_func=lambda i: s_opts[i])
            c1, c2 = st.columns(2)
            year = c1.text_input("Academic year", value="2026-27")
            sem = c2.text_input("Semester", value="Fall 2026")
            if st.form_submit_button("Enroll", type="primary"):
                if _run(lambda: admin.enroll_students(user, pid3, picks, year, sem), f"Enrolled {len(picks)} student(s)."):
                    st.rerun()
        if len(enr):
            e_opts = dict(zip(enr["id"], enr["student_code"] + " · " + enr["full_name"]))
            c1, c2, c3 = st.columns([2, 1, 1], vertical_alignment="bottom")
            eid = c1.selectbox("Change enrollment status", list(e_opts), format_func=lambda i: e_opts[i])
            new_status = c2.selectbox("Status", ["active", "completed", "dropped"], format_func=str.title)
            if c3.button("Update", width="stretch"):
                if _run(lambda: admin.set_enrollment_status(user, eid, new_status), "Enrollment updated."):
                    st.rerun()

    with t4:
        teachers = admin.list_teachers()
        if teachers.empty:
            st.info("Create a teacher account first (Users page).")
        else:
            m = admin.teacher_subject_map()
            all_subs = admin.list_subjects()
            sub_opts = dict(zip(all_subs["id"], all_subs["subject_name"] + " (" + all_subs["course_name"] + ")"))
            t_opts = dict(zip(teachers["id"], teachers["full_name"] + " · " + teachers["email"]))
            tid = st.selectbox("Teacher", list(t_opts), format_func=lambda i: t_opts[i])
            current = list(m[m["teacher_id"] == tid]["subject_id"]) if len(m) else []
            picks = st.multiselect("Subjects this teacher teaches", list(sub_opts), default=current,
                                   format_func=lambda i: sub_opts[i], key=f"tsub_{tid}")
            st.caption("The teacher will see the students enrolled in these subjects' programs and can record "
                       "results, assign work and set targets only in these subjects.")
            if st.button("Save subjects", type="primary"):
                if _run(lambda: admin.set_teacher_subjects(user, tid, picks), "Teacher subjects saved."):
                    st.rerun()
            if len(m):
                st.dataframe(m[["teacher", "subject_name", "course_name"]].rename(
                    columns={"teacher": "Teacher", "subject_name": "Subject", "course_name": "Program"}),
                    hide_index=True, width="stretch")


# ---------------------------------------------------------------- Learning resources (shared)
def resource_form(user, subjects: pd.DataFrame, key: str):
    """Add-resource form. `subjects` columns: id, subject_name, topic_id, topic_name."""
    if subjects.empty:
        st.info("No subjects available.")
        return
    subs = subjects.drop_duplicates("id")
    s_opts = dict(zip(subs["id"], subs["subject_name"]))
    sid = st.selectbox("Subject", list(s_opts), format_func=lambda i: s_opts[i], key=f"{key}_s")
    tops = subjects[(subjects["id"] == sid) & subjects["topic_id"].notna()]
    t_names = dict(zip(tops["topic_id"].astype(int), tops["topic_name"]))
    tid = st.selectbox("Topic", [None] + list(t_names), key=f"{key}_t",
                       format_func=lambda t: "Whole subject" if t is None else t_names[t])
    with st.form(f"{key}_form", clear_on_submit=True):
        title = st.text_input("Title", placeholder="Exact title of the video, PDF or page")
        url = st.text_input("Link", placeholder="https://…")
        c1, c2, c3 = st.columns(3)
        rtype = c1.selectbox("Type", admin.RESOURCE_TYPES, format_func=str.title)
        lang = c2.selectbox("Language", list(admin.LANGUAGES), format_func=lambda k: admin.LANGUAGES[k])
        diff = c3.selectbox("Level", admin.DIFFICULTIES, format_func=str.title)
        st.caption("Only add resources you have opened and checked. Use legal sources (no pirated books).")
        if st.form_submit_button("Add resource", type="primary"):
            msg = "Resource added and approved." if user.role == "admin" else \
                "Resource submitted. It will be shown to students after an administrator approves it."
            if _run(lambda: admin.add_resource(user, sid, tid, title, rtype, lang, url, diff), msg):
                st.rerun()


def _resource_table(df: pd.DataFrame):
    if df.empty:
        st.caption("Nothing here.")
        return
    show = df.rename(columns={"title": "Title", "url": "Link", "resource_type": "Type", "language": "Lang",
                              "difficulty": "Level", "verification_status": "Status", "subject_name": "Subject",
                              "topic_name": "Topic", "added_by": "Added by", "created_at": "Added"}).drop(columns=["id"])
    st.dataframe(show, hide_index=True, width="stretch", column_config={"Link": st.column_config.LinkColumn()})


def resources():
    user = _me()
    ui.hero("Learning Resources", "Curated, verified resources. Students only see approved ones.")
    from services.teaching import teacher_subjects
    pending = admin.list_resources("pending")
    t1, t2, t3 = st.tabs([f"⏳ Waiting for review ({len(pending)})", "✅ Library", "➕ Add resource"])
    with t1:
        if pending.empty:
            st.success("No resources waiting for review.")
        for r in pending.itertuples():
            with st.container(border=True):
                st.markdown(f"**{ui.esc(r.title)}** — {r.subject_name}{(' · ' + r.topic_name) if r.topic_name else ''}"
                            f"  \n{r.resource_type.title()} · {admin.LANGUAGES[r.language]} · {r.difficulty.title()}"
                            f" · added by {r.added_by}")
                st.markdown(f"[Open link to check]({r.url})")
                c1, c2, _ = st.columns([1, 1, 3])
                if c1.button("Approve", key=f"ap_{r.id}", type="primary", width="stretch"):
                    if _run(lambda: admin.review_resource(user, r.id, True), "Approved."):
                        st.rerun()
                if c2.button("Reject", key=f"rj_{r.id}", width="stretch"):
                    if _run(lambda: admin.review_resource(user, r.id, False), "Rejected."):
                        st.rerun()
    with t2:
        status = st.selectbox("Show", ["approved", "rejected"], format_func=str.title)
        _resource_table(admin.list_resources(status))
    with t3:
        resource_form(user, teacher_subjects(user), "admin_res")


# ---------------------------------------------------------------- Audit log
def audit():
    user = _me()
    ui.hero("Audit Log", "Who signed in, viewed student reports or changed data.")
    log = admin.audit_log(user, 300)
    actions = ["All"] + sorted(log["action"].dropna().unique())
    pick = st.selectbox("Action", actions)
    if pick != "All":
        log = log[log["action"] == pick]
    log.columns = ["Time", "User", "Action", "Item", "ID"]
    st.dataframe(log, hide_index=True, width="stretch")
    st.caption("The log records actions only — it does not store any academic data.")
