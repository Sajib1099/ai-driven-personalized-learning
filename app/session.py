"""Login state for the Streamlit app (only the user id is kept in the browser session)."""
from __future__ import annotations

import streamlit as st

from services.auth import CurrentUser, load_current_user, log_logout

def current_user() -> CurrentUser | None:
    uid = st.session_state.get("user_id")
    if uid is None:
        return None
    user = load_current_user(uid)          # re-checked against the database on every run
    if user is None:
        st.session_state.pop("user_id", None)
    return user


def login(user: CurrentUser) -> None:
    st.session_state["user_id"] = user.id


def logout() -> None:
    uid = st.session_state.get("user_id")
    if uid is not None:
        log_logout(uid)
    st.session_state.clear()


def require_role(*roles: str) -> CurrentUser:
    """Stop the page unless the logged-in user has one of the given roles."""
    user = current_user()
    if user is None or user.role not in roles:
        st.error("You do not have permission to view this page.")
        st.stop()
    return user
