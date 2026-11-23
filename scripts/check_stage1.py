"""
Stage 1a verification.

Run from the project folder:   python -m scripts.check_stage1

1. ML artifacts : model.json + preprocessor + label encoder load, and the model
                  reproduces 73.02% accuracy on the held-out test students.
2. Database     : all tables exist, a test user is saved with a hashed password,
                  and on the NEXT run the same user is found again (persistence).
"""
from __future__ import annotations

import sys

import pandas as pd
from sqlalchemy import inspect, select

from db.models import Base, User
from db.session import describe_database, engine, get_session
from services.auth import hash_password, verify_password
from services.prediction import Predictor, load_csv

TEST_EMAIL = "stage1.test@example.com"
TEST_PASSWORD = "Stage1-Test-Password"
EXPECTED_ACCURACY = 73.02

ok = True


def result(passed: bool, text: str):
    global ok
    ok &= passed
    print(("  [PASS] " if passed else "  [FAIL] ") + text)


print("\n=== 1. ML artifacts ===")
try:
    p = Predictor()
    result(True, f"Model loaded: {type(p.model).__name__}, {len(p.features)} input features, "
                 f"{p.model.n_features_in_} encoded features")
    result(p.classes == ["Distinction", "Fail", "Pass", "Withdrawn"], f"Classes: {p.classes}")
    t = load_csv("test_students.csv")
    proba = p.predict_proba_df(t[p.features])
    pred = pd.Series(proba.argmax(axis=1)).map(dict(enumerate(p.classes)))
    acc = round((pred.values == t["final_result"].values).mean() * 100, 2)
    result(abs(acc - EXPECTED_ACCURACY) < 0.01, f"Test accuracy {acc}% (expected {EXPECTED_ACCURACY}%) on {len(t):,} students")
except Exception as e:  # show the real error, do not hide it
    result(False, f"{type(e).__name__}: {e}")

print("\n=== 2. Database ===")
print("  Using", describe_database())
try:
    existing = set(inspect(engine).get_table_names())
    expected = set(Base.metadata.tables)
    missing = expected - existing
    result(not missing, f"{len(expected & existing)}/{len(expected)} tables exist"
                        + (f" — missing: {sorted(missing)}. Run:  alembic upgrade head" if missing else ""))
    if missing:
        raise SystemExit(1)

    with get_session() as s:
        user = s.scalar(select(User).where(User.email == TEST_EMAIL))
        if user is None:
            s.add(User(full_name="Stage 1 Test User", email=TEST_EMAIL,
                       password_hash=hash_password(TEST_PASSWORD), role="student"))
            print("  [INFO] Test user did not exist -> created now.")
            print("         Run this script AGAIN: it should say the user was found (data persisted).")
        else:
            print(f"  [PASS] Test user FOUND from an earlier run (created {user.created_at:%Y-%m-%d %H:%M}). "
                  "Data persisted after restart.")

    with get_session() as s:
        user = s.scalar(select(User).where(User.email == TEST_EMAIL))
        result(user is not None, "Test user can be read back from the database")
        result(user.password_hash != TEST_PASSWORD and user.password_hash.startswith("$2"),
               "Password stored as bcrypt hash (not plain text)")
        result(verify_password(TEST_PASSWORD, user.password_hash) and not verify_password("wrong", user.password_hash),
               "Correct password accepted, wrong password rejected")
except SystemExit:
    pass
except Exception as e:
    result(False, f"{type(e).__name__}: {e}")

print("\n" + ("ALL CHECKS PASSED" if ok else "SOME CHECKS FAILED — send this output"))
sys.exit(0 if ok else 1)
