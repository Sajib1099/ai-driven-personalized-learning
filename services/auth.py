"""
Authentication and accounts.

- Passwords are stored only as bcrypt hashes.
- Login fails with the same message for "unknown e-mail" and "wrong password"
  (does not reveal which e-mails exist).
- Disabled accounts cannot log in.
- Logins and account changes are written to the audit log.
"""
from __future__ import annotations

import re
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone

import bcrypt
from sqlalchemy import select

from db.models import AuditLog, StudentProfile, User
from db.session import get_session

MIN_PASSWORD_LENGTH = 8
MAX_PASSWORD_BYTES = 72   # bcrypt limit
MAX_FAILED_LOGINS = 5            # per account ...
LOCKOUT_MINUTES = 10             # ... within this window
EMAIL_RE = re.compile(r"^[^@\s]+@[^@\s]+\.[^@\s]+$")
ROLES = ("student", "teacher", "admin")


class AuthError(ValueError):
    """Error with a message that is safe to show to the user."""


@dataclass(frozen=True)
class CurrentUser:
    id: int
    full_name: str
    email: str
    role: str


# ---------------------------------------------------------------- passwords
def validate_password(password: str) -> None:
    if len(password) < MIN_PASSWORD_LENGTH:
        raise AuthError(f"Password must be at least {MIN_PASSWORD_LENGTH} characters.")
    if len(password.encode("utf-8")) > MAX_PASSWORD_BYTES:
        raise AuthError("Password is too long (maximum 72 bytes).")
    if not (re.search(r"[A-Za-z]", password) and re.search(r"\d", password)):
        raise AuthError("Password must contain at least one letter and one number.")


def hash_password(password: str) -> str:
    validate_password(password)
    return bcrypt.hashpw(password.encode("utf-8"), bcrypt.gensalt(rounds=12)).decode("utf-8")


def verify_password(password: str, password_hash: str) -> bool:
    try:
        return bcrypt.checkpw(password.encode("utf-8"), password_hash.encode("utf-8"))
    except ValueError:
        return False


def normalize_email(email: str) -> str:
    email = (email or "").strip().lower()
    if not EMAIL_RE.match(email) or len(email) > 254:
        raise AuthError("Please enter a valid e-mail address.")
    return email


def _audit(session, user_id: int | None, action: str, entity: str = "user", entity_id: int | None = None):
    session.add(AuditLog(user_id=user_id, action=action, entity=entity, entity_id=entity_id))


# ---------------------------------------------------------------- login
def authenticate(email: str, password: str) -> CurrentUser:
    try:
        email = normalize_email(email)
    except AuthError:
        raise AuthError("Incorrect e-mail or password.")

    error: str | None = None
    result: CurrentUser | None = None
    with get_session() as s:
        user = s.scalar(select(User).where(User.email == email))
        if user is not None and _recent_failures(s, user) >= MAX_FAILED_LOGINS:
            error = f"Too many failed attempts. Please try again in {LOCKOUT_MINUTES} minutes."
        elif user is None or not verify_password(password, user.password_hash):
            _audit(s, user.id if user else None, "login_failed")
            error = "Incorrect e-mail or password."
        elif user.account_status != "active":
            _audit(s, user.id, "login_blocked_disabled")
            error = "This account is disabled. Please contact the administrator."
        else:
            user.last_login_at = datetime.now(timezone.utc)
            _audit(s, user.id, "login")
            result = CurrentUser(user.id, user.full_name, user.email, user.role)
    # raise only after the session is committed, so failed attempts are saved in the audit log
    if error:
        raise AuthError(error)
    return result


def _as_utc(dt: datetime) -> datetime:
    return dt if dt.tzinfo else dt.replace(tzinfo=timezone.utc)


def _recent_failures(s, user: User) -> int:
    """Failed logins since the last successful login, within the lockout window."""
    since = datetime.now(timezone.utc) - timedelta(minutes=LOCKOUT_MINUTES)
    if user.last_login_at is not None:
        since = max(since, _as_utc(user.last_login_at))
    times = s.scalars(select(AuditLog.created_at).where(
        AuditLog.user_id == user.id, AuditLog.action == "login_failed")).all()
    return sum(1 for t in times if _as_utc(t) >= since)


def load_current_user(user_id: int) -> CurrentUser | None:
    """Re-read the user on every page load, so disabled accounts are logged out immediately."""
    with get_session() as s:
        user = s.get(User, user_id)
        if user is None or user.account_status != "active":
            return None
        return CurrentUser(user.id, user.full_name, user.email, user.role)


def log_logout(user_id: int) -> None:
    with get_session() as s:
        _audit(s, user_id, "logout")


# ---------------------------------------------------------------- registration
def register_student(full_name: str, email: str, password: str, student_code: str,
                     department: str = "", program: str = "", semester: str = "",
                     enrollment_year: int | None = None) -> CurrentUser:
    full_name = (full_name or "").strip()
    student_code = (student_code or "").strip().upper()
    if len(full_name) < 3:
        raise AuthError("Please enter your full name.")
    if not re.fullmatch(r"[A-Z0-9\-]{3,40}", student_code):
        raise AuthError("Student ID may contain only letters, numbers and '-' (3–40 characters).")
    email = normalize_email(email)
    password_hash = hash_password(password)

    with get_session() as s:
        if s.scalar(select(User.id).where(User.email == email)):
            raise AuthError("An account with this e-mail already exists.")
        if s.scalar(select(StudentProfile.id).where(StudentProfile.student_code == student_code)):
            raise AuthError("This student ID is already registered.")
        user = User(full_name=full_name, email=email, password_hash=password_hash, role="student")
        s.add(user)
        s.flush()
        s.add(StudentProfile(user_id=user.id, student_code=student_code, department=department.strip() or None,
                             program=program.strip() or None, semester=semester.strip() or None,
                             enrollment_year=enrollment_year, is_demo=False))
        _audit(s, user.id, "register_student", entity_id=user.id)
        return CurrentUser(user.id, user.full_name, user.email, user.role)


# ---------------------------------------------------------------- profile
def change_password(user_id: int, current_password: str, new_password: str) -> None:
    with get_session() as s:
        user = s.get(User, user_id)
        if user is None or not verify_password(current_password, user.password_hash):
            raise AuthError("Current password is incorrect.")
        if current_password == new_password:
            raise AuthError("New password must be different from the current password.")
        user.password_hash = hash_password(new_password)
        _audit(s, user_id, "change_password", entity_id=user_id)


def update_name(user_id: int, full_name: str) -> None:
    full_name = (full_name or "").strip()
    if len(full_name) < 3:
        raise AuthError("Please enter your full name.")
    with get_session() as s:
        user = s.get(User, user_id)
        user.full_name = full_name
        _audit(s, user_id, "update_profile", entity_id=user_id)
