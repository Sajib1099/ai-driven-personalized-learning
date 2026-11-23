"""Teacher portal pages (Stage 4)."""
from __future__ import annotations

from datetime import date

import pandas as pd
import streamlit as st

from app import session
from app.components import ui
from services import ai_service, learning, teaching
from services.teaching import TeacherActionError

SELECTED = "teacher_selected_student"


def _me():
    return session.require_role("teacher", "admin")


# ---------------------------------------------------------------- Class dashboard
def dashboard():
    user = _me()
    subjects = teaching.my_subject_names(user)
    ui.hero(f"Welcome, {user.full_name}", "Monitor your students, spot who needs support and act early.",
            tag="Teacher portal · " + (", ".join(subjects) if subjects else "no subjects assigned"))
    df = teaching.class_overview(user)
    if df.empty:
        st.info("No students are assigned to you yet. An administrator can assign you subjects.")
        return

    k = st.columns(4)
    ui.kpi(k[0], "Assigned students", str(len(df)))
    ui.kpi(k[1], "Needs attention", str(int(df["Needs attention"].sum())), "See reasons in the table")
    n_pred = int((df["AI prediction"] != "Not run").sum())
    ui.kpi(k[2], "High predicted risk", str(int(df["High risk"].sum())) if n_pred else "—",
           f"AI run for {n_pred}/{len(df)} students")
    ui.kpi(k[3], "Low engagement", str(int(df["Low engagement"].sum())),
           f"No activity in {teaching.ENGAGEMENT_DAYS} days")

    st.write("")
    c1, c2 = st.columns([1.2, 1], gap="large")
    with c1:
        st.markdown("#### Class performance in your subjects")
        perf = teaching.class_subject_performance(user)
        if len(perf):
            st.plotly_chart(ui.mastery_bars(list(perf["subject_name"]), list(perf["mastery"]), list(perf["level"])),
                            width="stretch", config={"displayModeBar": False})
    with c2:
        st.markdown("#### AI predictions")
        st.markdown("Run the AI model for every student who has module activity data. Results are estimates "
                    "that support your judgement — they are never a final label.")
        if st.button("🤖 Run AI for my students", type="primary", width="stretch"):
            with st.spinner("Running predictions…"):
                n = teaching.run_predictions_for_class(user)
            st.toast(f"Predictions updated for {n} students")
            st.rerun()
        if n_pred:
            counts = df[df["AI prediction"] != "Not run"]["AI prediction"].value_counts()
            st.markdown(" ".join(f"{ui.class_badge(c)} {counts.get(c, 0)}" for c in ui.CLASS_COLORS),
                        unsafe_allow_html=True)

    st.markdown("#### Students")
    only = st.toggle("Show only students who need attention", value=False)
    view = df[df["Needs attention"]] if only else df
    table = pd.DataFrame({
        "Student ID": view["Student ID"], "Name": view["Name"],
        "Overall mastery": view["Mastery"].map(lambda v: f"{v:.0f}%" if pd.notna(v) else "—"),
        "In my subjects": view["My subjects"].map(lambda v: f"{v:.0f}%" if pd.notna(v) else "—"),
        "Weak topics": view["Weak topics"], "Weakest of my subjects": view["Weakest of mine"],
        "AI prediction": view["AI prediction"],
        "Risk": view["Risk"].map(lambda v: f"{v * 100:.0f}%" if pd.notna(v) else "—"),
        "Open / done": view["Open recs"].astype(str) + " / " + view["Completed"].astype(str),
        "Status": view.apply(lambda r: ("⚠️ " if r["Needs attention"] else "✓ ") + r["Why"], axis=1),
    })
    st.dataframe(table, hide_index=True, width="stretch")
    st.caption(f"Needs attention = overall mastery < {teaching.ATTENTION_MASTERY:.0f}%, "
               f"≥ {teaching.ATTENTION_WEAK_TOPICS} weak topics, AI Fail/Withdrawn risk ≥ "
               f"{teaching.HIGH_RISK * 100:.0f}%, or no improvement after a completed activity.")

    st.markdown("#### Open a student")
    opts = dict(zip(df["Student ID"] + " · " + df["Name"], df["student_id"]))
    c1, c2 = st.columns([3, 1], vertical_alignment="bottom")
    pick = c1.selectbox("Student", list(opts))
    if c2.button("Open student →", width="stretch"):
        st.session_state[SELECTED] = int(opts[pick])
        st.switch_page(PAGES["detail"])


# ---------------------------------------------------------------- Student detail
def student_detail():
    user = _me()
    df = teaching.class_overview(user)
    if df.empty:
        st.info("No students are assigned to you yet.")
        return
    opts = dict(zip(df["student_id"], df["Student ID"] + " · " + df["Name"]))
    ids = list(opts)
    current = st.session_state.get(SELECTED, ids[0])
    sid = st.selectbox("Student", ids, index=ids.index(current) if current in ids else 0,
                       format_func=lambda i: opts[i])
    st.session_state[SELECTED] = sid
    try:
        head = teaching.student_header(user, sid)
    except PermissionError as e:
        st.error(str(e))
        return
    teaching.log_view(user, sid)
    row = df[df["student_id"] == sid].iloc[0]

    ui.hero(head["name"], f'{head["code"]} · {head["program"] or ""} · {head["semester"] or ""}',
            tag="Student report" + (" · demo account" if head["is_demo"] else ""))
    k = st.columns(4)
    ui.kpi(k[0], "Overall mastery", f'{row["Mastery"]:.0f}%' if pd.notna(row["Mastery"]) else "—")
    ui.kpi(k[1], "Weak topics", str(row["Weak topics"]))
    ui.kpi(k[2], "AI prediction", row["AI prediction"],
           f'Risk {row["Risk"] * 100:.0f}%' if pd.notna(row["Risk"]) else "")
    ui.kpi(k[3], "Recommendations", f'{row["Open recs"]} open', f'{row["Completed"]} completed')
    if row["Needs attention"]:
        st.warning(f"Needs attention: {row['Why']}.")

    t1, t2, t3, t4 = st.tabs(["📈 Performance", "🤖 AI & explanation", "💡 Recommendations & progress",
                              "✍️ Actions"])

    with t1:
        m = learning.topic_mastery(sid)
        if m.empty:
            st.info("No assessments recorded yet.")
        else:
            subj = learning.subject_summary(m)
            c1, c2 = st.columns(2, gap="large")
            with c1:
                st.markdown("**By subject**")
                st.plotly_chart(ui.mastery_bars(list(subj["subject_name"]), list(subj["mastery"]),
                                                list(subj["level"])), width="stretch", config={"displayModeBar": False})
            with c2:
                st.markdown("**First vs latest**")
                st.plotly_chart(ui.progress_bars(list(subj["subject_name"]), list(subj["first_avg"]),
                                                 list(subj["latest_avg"])), width="stretch",
                                config={"displayModeBar": False})
            st.markdown("**Topics (weakest first)**")
            show = m.sort_values("mastery")[["subject_name", "topic_name", "mastery", "latest_pct", "trend", "level"]]
            show.columns = ["Subject", "Topic", "Mastery %", "Latest %", "Change", "Level"]
            st.dataframe(show.round(0), hide_index=True, width="stretch")

    with t2:
        pred = ai_service.latest_prediction(sid)
        if not head["has_module_record"]:
            st.info("No module activity record for this student, so the AI model cannot be applied.")
        else:
            if st.button("Run / update AI prediction", key="run_one"):
                with st.spinner("Predicting…"):
                    ai_service.run_prediction(sid)
                st.rerun()
            if pred:
                cls = pred["predicted_class"]
                c1, c2 = st.columns([1, 1.3], gap="large")
                c1.markdown(f'<div class="pred-card" style="border-left:6px solid {ui.CLASS_COLORS[cls]}">'
                            f'<div class="kpi-label">Predicted module result (estimate)</div>'
                            f'<div class="pred-class">{cls}</div><div style="color:{ui.INK_2}">Fail/Withdrawn risk: '
                            f'<b>{pred["risk_probability"] * 100:.1f}%</b></div></div>', unsafe_allow_html=True)
                c2.plotly_chart(ui.probability_chart(pred["probabilities"]), width="stretch",
                                config={"displayModeBar": False})
                top = pred["shap"][cls][:10][::-1]
                st.markdown(f"**Why the model predicts {cls} (SHAP)**")
                st.plotly_chart(ui.contribution_chart(
                    [f"{t['label']} = {t['value']:.2f}" if isinstance(t["value"], (int, float)) else
                     f"{t['label']} = {t['value']}" for t in top],
                    [t["contribution"] for t in top], [t["label"] for t in top], f"SHAP value toward “{cls}”"),
                    width="stretch", config={"displayModeBar": False})
                st.caption("Use this as one input to your judgement. The model is retrospective (whole-module data) "
                           "and 73% accurate on held-out students.")
            else:
                st.info("No prediction yet.")

    with t3:
        recs = learning.list_recommendations(sid, active=None)
        if not recs:
            st.info("No recommendations yet.")
        else:
            tab = pd.DataFrame([{
                "Recommendation": r.title, "Source": {"subject_rules": "Subject progress", "ai_module": "AI",
                                                      "teacher": "Teacher"}[r.source],
                "Priority": r.priority.title(), "Status": r.status.title(), "Open": "Yes" if r.is_active else "No",
                "Student feedback": r.feedback or "", "Helpful (1–5)": r.rating or "",
                "Why": r.reason} for r in recs])
            st.dataframe(tab, hide_index=True, width="stretch")
        fb = teaching.feedback_history(user, sid)
        st.markdown("**Feedback history**")
        if fb.empty:
            st.caption("No feedback yet.")
        else:
            fb.columns = ["Date", "Teacher", "Subject", "Visible to", "Feedback"]
            st.dataframe(fb, hide_index=True, width="stretch")

    with t4:
        _actions(user, sid)


def _subject_topic_picker(user, key: str, allow_none_topic: bool = True):
    st_df = teaching.teacher_subjects(user)
    if st_df.empty:
        st.warning("No subjects are assigned to you yet.")
        return None, None
    subjects = st_df.drop_duplicates("id")[["id", "subject_name"]]
    sub_id = st.selectbox("Subject", list(subjects["id"]), key=f"{key}_subj",
                          format_func=lambda i: subjects.set_index("id").at[i, "subject_name"])
    topics = st_df[(st_df["id"] == sub_id) & st_df["topic_id"].notna()]
    t_opts = ([None] if allow_none_topic else []) + [int(t) for t in topics["topic_id"]]
    names = dict(zip(topics["topic_id"].astype(int), topics["topic_name"]))
    top_id = st.selectbox("Topic", t_opts, key=f"{key}_topic",
                          format_func=lambda t: "Whole subject" if t is None else names[t])
    return int(sub_id), top_id


def _actions(user, sid):
    mine = teaching.my_subject_names(user)
    st.caption("You can record results, assign work and set targets only in the subjects you teach: "
               + (", ".join(mine) if mine else "none") + ". Feedback without a subject is a general note.")
    a1, a2 = st.columns(2, gap="large")
    with a1:
        with st.container(border=True):
            st.markdown("**Record an assessment result**")
            sub_id, top_id = _subject_topic_picker(user, "rec")
            with st.form("record_one", clear_on_submit=True):
                name = st.text_input("Assessment name", placeholder="e.g. Quiz 3")
                c1, c2, c3 = st.columns(3)
                a_type = c1.selectbox("Type", teaching.ASSESSMENT_TYPES)
                score = c2.number_input("Score", min_value=0.0, value=0.0, step=0.5)
                maximum = c3.number_input("Out of", min_value=1.0, value=20.0, step=1.0)
                when = st.date_input("Date", value=date.today())
                if st.form_submit_button("Save result", type="primary"):
                    try:
                        teaching.record_assessment(user, sid, sub_id, top_id, name, a_type, score, maximum, when)
                        st.success("Saved. The student's recommendations will update automatically.")
                    except (TeacherActionError, PermissionError) as e:
                        st.error(str(e))

        with st.container(border=True):
            st.markdown("**Write feedback**")
            with st.form("feedback", clear_on_submit=True):
                text = st.text_area("Feedback")
                vis = st.radio("Visible to", ["student", "private"], horizontal=True,
                               format_func=lambda v: "Student" if v == "student" else "Only teachers (private note)")
                if st.form_submit_button("Save feedback"):
                    try:
                        teaching.add_feedback(user, sid, text, None, vis)
                        st.success("Feedback saved.")
                    except (TeacherActionError, PermissionError) as e:
                        st.error(str(e))

    with a2:
        with st.container(border=True):
            st.markdown("**Assign a learning activity**")
            sub_id2, top_id2 = _subject_topic_picker(user, "act")
            with st.form("assign", clear_on_submit=True):
                title = st.text_input("Activity title", placeholder="e.g. Solve 10 practice questions on Joins")
                desc = st.text_area("Instructions (optional)")
                c1, c2 = st.columns(2)
                prio = c1.selectbox("Priority", ["high", "medium", "low"], index=1, format_func=str.title)
                diff = c2.selectbox("Level", ["beginner", "intermediate", "advanced"], index=0, format_func=str.title)
                if st.form_submit_button("Assign activity", type="primary"):
                    try:
                        teaching.assign_activity(user, sid, title, desc, sub_id2, top_id2, prio, diff)
                        st.success("Activity assigned. The student will see it in Recommendations.")
                    except (TeacherActionError, PermissionError) as e:
                        st.error(str(e))

        with st.container(border=True):
            st.markdown("**Set a study target**")
            st_df = teaching.teacher_subjects(user).drop_duplicates("id")
            if st_df.empty:
                st.caption("No subjects assigned to you.")
                return
            with st.form("target", clear_on_submit=True):
                sub3 = st.selectbox("Subject", list(st_df["id"]),
                                    format_func=lambda i: st_df.set_index("id").at[i, "subject_name"])
                c1, c2 = st.columns(2)
                mins = c1.number_input("Minutes per day", min_value=5, max_value=480, value=45, step=5)
                prio3 = c2.selectbox("Priority", ["high", "medium", "low"], format_func=str.title, key="tprio")
                end = st.date_input("Until (optional)", value=None)
                if st.form_submit_button("Save target"):
                    try:
                        teaching.set_study_target(user, sid, int(sub3), int(mins), prio3, end)
                        st.success("Study target saved. It replaces the system suggestion for this subject.")
                    except (TeacherActionError, PermissionError) as e:
                        st.error(str(e))


# ---------------------------------------------------------------- Record class scores
def record_scores():
    user = _me()
    ui.hero("Record Class Scores", "Enter one assessment for all your students at once.")
    df = teaching.class_overview(user)
    if df.empty:
        st.info("No students are assigned to you yet.")
        return
    with st.container(border=True):
        sub_id, top_id = _subject_topic_picker(user, "class")
        c1, c2, c3, c4 = st.columns([2, 1, 1, 1])
        name = c1.text_input("Assessment name", placeholder="e.g. Quiz 3")
        a_type = c2.selectbox("Type", teaching.ASSESSMENT_TYPES)
        maximum = c3.number_input("Out of", min_value=1.0, value=20.0, step=1.0)
        when = c4.date_input("Date", value=date.today())
    editor = pd.DataFrame({"student_id": df["student_id"], "Student ID": df["Student ID"], "Name": df["Name"],
                           "Score": [None] * len(df)})
    edited = st.data_editor(editor, hide_index=True, width="stretch", disabled=["Student ID", "Name"],
                            column_config={"student_id": None,
                                           "Score": st.column_config.NumberColumn(min_value=0.0, step=0.5,
                                                                                  help="Leave empty if absent")},
                            key="class_scores")
    if st.button("Save all scores", type="primary"):
        try:
            n = teaching.record_class_scores(user, sub_id, top_id, name, a_type, maximum, when,
                                             dict(zip(edited["student_id"], edited["Score"])))
            st.success(f"Saved {n} scores. Recommendations will update when students open the platform.")
        except (TeacherActionError, PermissionError) as e:
            st.error(str(e))


PAGES: dict = {}   # filled by app/main.py so dashboard can switch to the detail page
