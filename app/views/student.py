"""Student portal pages (Stage 3)."""
from __future__ import annotations

import pandas as pd
import streamlit as st

from app import session
from app.components import ui
from services import ai_service, learning
from services.access import student_profile_id
from services.overview import student_profile

SOURCE_LABEL = {"subject_rules": "Subject progress", "ai_module": "AI prediction", "teacher": "Teacher"}
TYPE_ICON = {"revision": "📘", "practice": "✏️", "enrichment": "🚀", "alternative": "🔄"}
STATUS_STYLE = {"pending": ("#f0efec", "#52514e", "Not started"), "started": ("#e3eefc", "#1c5cab", "In progress"),
                "completed": ("#dff3df", "#006300", "✓ Completed"), "skipped": ("#f0efec", "#898781", "Skipped")}


# ---------------------------------------------------------------- helpers
def _me():
    user = session.require_role("student")
    sid = student_profile_id(user.id)
    if sid is None:
        st.error("No student profile is linked to this account.")
        st.stop()
    return user, sid


def _refresh_if_needed(sid: int):
    if learning.needs_refresh(sid):
        learning.refresh_recommendations(sid)


def _status_badge(status: str) -> str:
    bg, fg, text = STATUS_STYLE[status]
    return f'<span class="badge" style="background:{bg};color:{fg}">{text}</span>'


def _priority_badge(priority: str) -> str:
    bg, fg, text = ui.PRIORITY_STYLE[priority.title()]
    return f'<span class="badge" style="background:{bg};color:{fg}">{text}</span>'


def _demo_notice(sid_profile: dict):
    if sid_profile and sid_profile["is_demo"]:
        st.caption("ℹ️ Demo account: the module record comes from the OULAD test set; quiz scores are "
                   "synthetic demonstration data.")


# ---------------------------------------------------------------- Dashboard
def dashboard():
    user, sid = _me()
    _refresh_if_needed(sid)
    profile = student_profile(user.id)
    mastery = learning.topic_mastery(sid)
    subjects = learning.subject_summary(mastery)
    recs = learning.list_recommendations(sid, active=True)
    done = [r for r in learning.list_recommendations(sid, active=None) if r.status == "completed"]
    pred = ai_service.latest_prediction(sid)

    ui.hero(f"Welcome back, {user.full_name}",
            "Your progress, strengths, weaknesses and next steps in one place.", tag="Student portal")
    _demo_notice(profile)

    k = st.columns(4)
    ui.kpi(k[0], "Overall mastery", f"{mastery['mastery'].mean():.0f}%" if len(mastery) else "—",
           f"Across {len(mastery)} topics" if len(mastery) else "No assessments yet")
    ui.kpi(k[1], "Topics needing work", str(int((mastery["level"] == "weak").sum())) if len(mastery) else "—",
           "Below 50%")
    ui.kpi(k[2], "Active recommendations", str(len(recs)), f"{len(done)} completed so far")
    ui.kpi(k[3], "AI predicted result", pred["predicted_class"] if pred else "—",
           "Estimate, not a final result" if pred else "Open AI Prediction to run")

    if mastery.empty:
        st.info("No assessment results are recorded yet. Your teacher will add quiz or assignment scores.")
        return

    st.write("")
    c1, c2 = st.columns([1.35, 1], gap="large")
    with c1:
        st.markdown("#### Performance by subject")
        st.plotly_chart(ui.mastery_bars(list(subjects["subject_name"]), list(subjects["mastery"]),
                                        list(subjects["level"])), width="stretch", config={"displayModeBar": False})
    with c2:
        st.markdown("#### Strengths and weaknesses")
        strong = mastery.nlargest(3, "mastery")
        weak = mastery.nsmallest(3, "mastery")
        st.markdown("**Strongest topics**")
        for r in strong.itertuples():
            st.markdown(f"{ui.level_badge(r.level)} {ui.esc(r.topic_name)} · {r.subject_name} — **{r.mastery:.0f}%**",
                        unsafe_allow_html=True)
        st.markdown("**Topics to improve**")
        for r in weak.itertuples():
            st.markdown(f"{ui.level_badge(r.level)} {ui.esc(r.topic_name)} · {r.subject_name} — **{r.mastery:.0f}%**",
                        unsafe_allow_html=True)

    st.markdown("#### Your next steps")
    if not recs:
        st.success("No open recommendations. Keep up the good work!")
    for r in recs[:3]:
        st.markdown(f'<div class="rec-card">{_priority_badge(r.priority)} <span class="rec-title">'
                    f'{TYPE_ICON.get(r.rec_type, "💡")} {ui.esc(r.title)}</span>'
                    f'<div class="rec-evidence">{ui.esc(r.subject or "")} {("· " + ui.esc(r.topic)) if r.topic else ""}'
                    f' · {_status_badge(r.status)}</div></div>', unsafe_allow_html=True)
    if len(recs) > 3:
        st.caption(f"+ {len(recs) - 3} more in Recommendations.")

    fb = learning.visible_teacher_feedback(sid)
    if len(fb):
        st.markdown("#### Feedback from your teachers")
        for r in fb.head(3).itertuples():
            st.markdown(f'<div class="note"><b>{ui.esc(r.teacher)}</b> · {r.created_at:%d %b %Y}'
                        f'{(" · " + ui.esc(r.subject_name)) if r.subject_name else ""}<br>{ui.esc(r.feedback)}</div>',
                        unsafe_allow_html=True)


# ---------------------------------------------------------------- My Performance
def performance():
    user, sid = _me()
    ui.hero("My Performance", "Subject and topic results from your recorded assessments.")
    mastery = learning.topic_mastery(sid)
    if mastery.empty:
        st.info("No assessment results are recorded yet.")
        return
    subjects = learning.subject_summary(mastery)

    st.markdown("#### Progress: first vs latest assessment")
    st.plotly_chart(ui.progress_bars(list(subjects["subject_name"]), list(subjects["first_avg"]),
                                     list(subjects["latest_avg"])), width="stretch", config={"displayModeBar": False})

    st.markdown("#### Topic details")
    names = list(subjects.sort_values("subject_name")["subject_name"])
    choice = st.selectbox("Subject", names)
    m = mastery[mastery["subject_name"] == choice]
    c1, c2 = st.columns([1.2, 1], gap="large")
    with c1:
        st.plotly_chart(ui.mastery_bars(list(m["topic_name"]), list(m["mastery"]), list(m["level"])),
                        width="stretch", config={"displayModeBar": False})
    with c2:
        table = pd.DataFrame({
            "Topic": m["topic_name"], "Mastery": m["mastery"].round(0).astype(int).astype(str) + "%",
            "Latest": m["latest_pct"].round(0).astype(int).astype(str) + "%",
            "Change": m["trend"].map(lambda v: f"{v:+.0f}"), "Level": m["level"].str.title(),
            "Attempts": m["attempts"]})
        st.dataframe(table, hide_index=True, width="stretch")
        st.caption("Mastery weighs recent attempts more. Weak < 50%, Developing 50–69%, Strong ≥ 70%.")

    with st.expander("All assessment records"):
        df = learning.assessments_frame(sid)
        df = df[["assessment_date", "subject_name", "topic_name", "assessment_name", "score", "maximum_score"]]
        df.columns = ["Date", "Subject", "Topic", "Assessment", "Score", "Out of"]
        st.dataframe(df.sort_values("Date", ascending=False), hide_index=True, width="stretch")


# ---------------------------------------------------------------- AI Prediction
def ai_prediction():
    user, sid = _me()
    ui.hero("AI Performance Prediction", "Estimated module result with SHAP and LIME explanations.")
    mr = ai_service.module_record(sid)
    if mr is None:
        st.info("AI prediction is not available for this account yet. It needs module activity data "
                "(assessment and online-engagement records in the format the model was trained on).")
        return
    st.markdown(
        '<div class="note">This is an <b>estimate</b> from a machine-learning model trained on the Open University '
        'Learning Analytics Dataset (OULAD). It uses information from the whole module, so it is not an '
        'early-warning prediction and it is not a guaranteed result. Test accuracy: 73.02%.</div>',
        unsafe_allow_html=True)
    st.caption(f"Module record: {mr['code_module']} {mr['code_presentation']} ({mr['source'].replace('_', ' ')})")

    if st.button("Run AI analysis", type="primary"):
        with st.spinner("Predicting and explaining…"):
            ai_service.run_prediction(sid)
        st.rerun()

    pred = ai_service.latest_prediction(sid)
    if pred is None:
        st.info("No prediction yet. Click **Run AI analysis**.")
        return

    cls = pred["predicted_class"]
    plan = ai_service.plan_for(cls)
    c1, c2 = st.columns([1, 1.3], gap="large")
    with c1:
        st.markdown(
            f'<div class="pred-card" style="border-left:6px solid {ui.CLASS_COLORS[cls]}">'
            f'<div class="kpi-label">Predicted module result</div><div class="pred-class">{cls}</div>'
            f'<div style="color:{ui.INK_2};margin-top:.4rem">Confidence: <b>{pred["probabilities"][cls] * 100:.1f}%</b>'
            f' · Fail/Withdrawn risk: <b>{pred["risk_probability"] * 100:.1f}%</b></div>'
            f'<div style="color:{ui.MUTED};font-size:.8rem;margin-top:.4rem">Run on {pred["created_at"]:%d %b %Y %H:%M}'
            f' · {pred["model_version"]}</div></div>', unsafe_allow_html=True)
        st.caption(f"{plan['headline']}. {plan['summary']}")
    with c2:
        st.plotly_chart(ui.probability_chart(pred["probabilities"]), width="stretch", config={"displayModeBar": False})

    t1, t2, t3 = st.tabs(["🔍 SHAP — why this result", "🧪 LIME — local rules", "🕘 History"])
    with t1:
        target = st.selectbox("Explain the probability of", list(pred["shap"]), index=list(pred["shap"]).index(cls))
        top = pred["shap"][target][:10][::-1]
        labels_ = [f"{t['label']} = {t['value']:.2f}" if isinstance(t["value"], (int, float)) else f"{t['label']} = {t['value']}"
                   for t in top]
        st.plotly_chart(ui.contribution_chart(labels_, [t["contribution"] for t in top], [t["label"] for t in top],
                                              f"SHAP value toward “{target}”"), width="stretch",
                        config={"displayModeBar": False})
        st.markdown(f'<span style="color:{ui.POSITIVE}">■</span> increases the chance of **{target}** &nbsp; '
                    f'<span style="color:{ui.NEGATIVE}">■</span> decreases it', unsafe_allow_html=True)
    with t2:
        lime = pred["lime"][::-1]
        st.plotly_chart(ui.contribution_chart([r["rule"] for r in lime], [r["weight"] for r in lime],
                                              [r["rule"] for r in lime], f"LIME weight toward “{cls}”"),
                        width="stretch", config={"displayModeBar": False})
    with t3:
        hist = ai_service.prediction_history(sid)
        hist.columns = ["Run at", "Predicted", "Fail/Withdrawn risk", "Model"]
        hist["Fail/Withdrawn risk"] = (hist["Fail/Withdrawn risk"] * 100).round(1).astype(str) + "%"
        st.dataframe(hist, hide_index=True, width="stretch")
    st.caption("Behaviour-based advice from this prediction appears on the Recommendations page "
               "(source: AI prediction). SHAP and LIME explain the model, not real-world causes.")


# ---------------------------------------------------------------- Recommendations
def _rec_card(r, sid: int, active: bool):
    with st.container(border=True):
        where = " · ".join(x for x in [r.subject, r.topic] if x)
        st.markdown(f'{_priority_badge(r.priority)} {_status_badge(r.status)} '
                    f'<span class="badge" style="background:#f0efec;color:#52514e">{SOURCE_LABEL[r.source]}</span>'
                    f'<div class="rec-title" style="margin-top:.4rem">{TYPE_ICON.get(r.rec_type, "💡")} '
                    f'{ui.esc(r.title)}</div><div class="rec-evidence">{ui.esc(where)}'
                    f'{(" · " + r.difficulty.title()) if r.difficulty else ""}</div>', unsafe_allow_html=True)
        st.markdown(r.description)
        st.caption(f"Why: {r.reason}")
        if r.resources:
            st.markdown("**Resources**")
            for res in r.resources:
                st.markdown(f"- [{res['title']}]({res['url']}) — {res['resource_type']}, {res['language'].upper()}, "
                            f"{res['difficulty']}")
        elif r.source == "subject_rules":
            st.caption("No approved resources for this topic yet — your teacher can add them.")
        if r.feedback or r.rating:
            st.caption(f"Your feedback: {r.feedback or '—'}" + (f" · Helpfulness {r.rating}/5" if r.rating else ""))

        if active and r.status in ("pending", "started"):
            b1, b2, b3 = st.columns([1, 1.4, 1])
            if r.status == "pending" and b1.button("▶ Start", key=f"start_{r.id}", width="stretch"):
                learning.update_progress(sid, r.id, "started")
                st.rerun()
            with b2.popover("✓ Mark as completed", width="stretch"):
                with st.form(f"done_{r.id}"):
                    fb = st.text_area("What did you do? (optional)", key=f"fb_{r.id}")
                    rating = st.slider("How helpful was it?", 1, 5, 4, key=f"rate_{r.id}")
                    if st.form_submit_button("Save as completed", type="primary"):
                        learning.update_progress(sid, r.id, "completed", fb, rating)
                        st.rerun()
            if b3.button("Skip", key=f"skip_{r.id}", width="stretch"):
                learning.update_progress(sid, r.id, "skipped")
                st.rerun()
        elif active and r.status == "completed":
            st.caption("✓ Completed. Your next assessment in this topic will decide the next step.")


def recommendations():
    user, sid = _me()
    _refresh_if_needed(sid)
    ui.hero("My Recommendations", "Personalised next steps based on your results and your learning history.")
    c1, c2 = st.columns([3, 1])
    c1.markdown('<div class="note">Recommendations update automatically when new results are recorded or when '
                'you complete or skip an activity. If your score improves after an activity you move to the next '
                'level; if it does not, you get a different approach and teacher support is suggested.</div>',
                unsafe_allow_html=True)
    if c2.button("🔄 Update now", width="stretch"):
        changes = learning.refresh_recommendations(sid)
        st.toast(f"{changes['created']} new, {changes['closed']} closed")
        st.rerun()

    active = learning.list_recommendations(sid, active=True)
    history = learning.list_recommendations(sid, active=False)
    t1, t2 = st.tabs([f"Active ({len(active)})", f"History ({len(history)})"])
    with t1:
        if not active:
            st.success("No open recommendations right now.")
        for r in active:
            _rec_card(r, sid, active=True)
    with t2:
        if not history:
            st.info("Closed recommendations will appear here.")
        for r in history:
            _rec_card(r, sid, active=False)


# ---------------------------------------------------------------- Study Plan
def study_plan():
    user, sid = _me()
    _refresh_if_needed(sid)
    ui.hero("My Study Plan", "Suggested daily study time per subject, based on where you need the most work.")
    plan = learning.current_study_plan(sid)
    if plan.empty:
        st.info("A study plan is created once assessment results are available.")
        return
    total = int(plan["target_minutes_per_day"].sum())
    c1, c2 = st.columns([1.2, 1], gap="large")
    with c1:
        show = pd.DataFrame({"Subject": plan["subject_name"], "Priority": plan["priority"].str.title(),
                             "Suggested time": plan["target_minutes_per_day"].map(lambda m: f"{m} min/day")})
        st.dataframe(show, hide_index=True, width="stretch")
        st.caption(f"Total ≈ {total} minutes per day. Subjects with more weak topics get more time; every subject "
                   f"keeps some revision time. These are suggestions — adjust them to your timetable.")
    with c2:
        mastery = learning.topic_mastery(sid)
        targets = mastery[mastery["level"] != "strong"].nsmallest(6, "mastery")
        st.markdown("#### Upcoming targets")
        for r in targets.itertuples():
            goal = 60 if r.level == "weak" else 70
            st.markdown(f"{ui.level_badge(r.level)} **{ui.esc(r.topic_name)}** ({r.subject_name}): "
                        f"{r.mastery:.0f}% → aim for **{goal}%** in the next assessment", unsafe_allow_html=True)
