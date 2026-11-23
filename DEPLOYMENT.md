# Deployment guide

The platform runs on **Streamlit Community Cloud** (free) with a **PostgreSQL** database
from **Neon** (free tier). Supabase works the same way — only the connection string differs.

On start-up the app applies the database migrations itself, and (if enabled) adds the demo
data to an empty database, so no terminal commands are needed on the server.

## 1. Create the PostgreSQL database (Neon)
1. Sign up at neon.tech (GitHub login is fine).
2. **Create project** → name `ai-learning-platform`, region **AWS Asia Pacific (Singapore)** (closest to Bangladesh).
3. On the project dashboard click **Connect** and copy the connection string. It looks like:
   `postgresql://USER:PASSWORD@ep-xxxx.ap-southeast-1.aws.neon.tech/neondb?sslmode=require`
   Keep it private — it contains the database password.

## 2. Deploy the app (Streamlit Community Cloud)
1. Sign in at share.streamlit.io with the GitHub account that owns the repository.
2. **Create app** → *Deploy a public app from GitHub*:
   - Repository: `Sajib1099/ai-driven-personalized-learning`
   - Branch: `main`
   - Main file path: `app/main.py`
3. Open **Advanced settings**:
   - Python version: **3.12**
   - Secrets (paste, then replace the values):
     ```toml
     DATABASE_URL = "postgresql://USER:PASSWORD@HOST/neondb?sslmode=require"
     DEMO_PASSWORD = "choose-a-private-password-1"
     SEED_DEMO_ON_EMPTY = "true"
     SHOW_DEMO_LOGINS = "false"
     ```
4. **Deploy**. The first start installs the libraries and prepares the database (a few minutes).

| Secret | Meaning |
|---|---|
| `DATABASE_URL` | Neon/Supabase connection string |
| `DEMO_PASSWORD` | Password of all demo accounts (do **not** use the public `Demo@12345` online) |
| `SEED_DEMO_ON_EMPTY` | `true` = add demo accounts and data when the database is empty |
| `SHOW_DEMO_LOGINS` | `false` = hide the demo account list on the public login page |

Share the demo password only with the supervisor and examiners.

## 3. After deployment
- Sign in as `admin@demo.example.com` with your `DEMO_PASSWORD` and change it in **My Profile**.
- Every `git push` to `main` redeploys the app automatically.
- Free apps sleep after a period without visitors; the first visit wakes them up (about 30 seconds).

## Running locally
Nothing changes: without secrets the app uses the SQLite file `data/app.db`.
`python -m scripts.seed_demo` adds the demo data locally.

## Never commit
`.env`, `.streamlit/secrets.toml` and `data/` are listed in `.gitignore`.
