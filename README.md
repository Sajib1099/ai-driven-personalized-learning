# AI-Driven Personalized Learning Platform

Undergraduate thesis project — Sajib Sarker, Department of Software Engineering, Daffodil International University.

A database-driven learning platform with Student, Teacher and Admin portals that predicts student
performance (XGBoost, OULAD), explains predictions (SHAP, LIME) and gives personalised learning
recommendations that use each student's stored learning history.

## Current status
- [x] **Stage 1a** — project structure, database schema (21 tables), migrations, ML artifacts verified
- [x] **Stage 1b** — demo data: `python -m scripts.seed_demo` (12 demo students linked to real OULAD test records + synthetic topic quizzes)
- [x] **Stage 2** — login, student registration, roles (student/teacher/admin), profile & password change, account lockout, access rules
- [x] **Stage 3** — Student portal: dashboard, topic mastery, history-aware recommendations (start/complete/skip), study plan, AI prediction with SHAP and LIME
- [x] **Stage 4** — Subject-wise teachers (each teacher edits only their own subjects). Teacher portal: class dashboard with attention/risk/engagement flags, AI for the class, student report (performance, SHAP, recommendations, feedback), record scores (single and whole class), assign activities, study targets, notifications
- [x] **Stage 5–6** — AI and recommendation integration (built into Stages 3–4)
- [x] **Stage 7** — Admin portal: users (create, disable, reset password), programs/subjects/topics, enrollments, teacher subjects, learning resources with teacher suggestion → admin approval, audit log
- [x] **Stage 8 (ready)** — all checks pass on SQLite and PostgreSQL; automatic migrations and optional demo seed at start-up; deployment steps in `DEPLOYMENT.md`

## Setup (Windows, VS Code terminal)
```powershell
py -3.12 -m venv venv
venv\Scripts\activate
pip install -r requirements.txt
alembic upgrade head          # creates the database tables
python -m scripts.check_stage1
python -m scripts.seed_demo   # adds demo accounts and data (use --reset to rebuild)
python -m scripts.check_stage2
python -m scripts.check_stage3
python -m scripts.check_stage4
python -m scripts.check_stage7
streamlit run app/main.py     # open the platform
```

Known limitation: refreshing the browser page (F5) signs the user out (Streamlit keeps login per browser session).

## Folder structure
```
app/            Streamlit pages and UI components (Stage 2+)
services/       business logic: prediction, explainability, recommendations, auth
db/             database models (models.py) and connection (session.py)
migrations/     Alembic database migrations
ml_artifacts/   trained model and files exported by the notebook
notebooks/      OULAD_Thesis_Final.ipynb (data → model → SHAP/LIME → export)
scripts/        setup and verification scripts
data/           local SQLite database (not uploaded to GitHub)
```

## Model
Leakage-free XGBoost, 37 features, OULAD. Test accuracy 73.02%, macro F1 0.669, ROC-AUC 0.919.
It is a retrospective (full-module) model, not an early-warning model.
