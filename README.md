# KI-Zukunft 2035 — Chainlit interface

Interactive web interface for modelling **positive AI future scenarios to 2035**.
Participants provide only their *background* and *assumptions*; the goal and the
work assignment live in a configurable system prompt. The app streams responses
from either **OpenAI** or **Anthropic** (selected by env var) and supports free,
multi-turn refinement. Conversations persist to **Heroku Postgres**.

See [`context/MEETING.md`](context/MEETING.md) for the project background.

## Architecture

| File | Purpose |
|------|---------|
| `app.py` | Chainlit app: auth, data layer, guided intake, chat loop |
| `llm.py` | Provider abstraction (`stream_chat`) over the OpenAI & Anthropic SDKs |
| `config.py` | All env-var configuration (provider, models, keys, DB URL, prompt) |
| `prompts/system_prompt.md` | Goal (#1) + Work assignment (#4) — **placeholder, replace with the finalized prompt** |
| `schema.sql` | Chainlit's Postgres tables |

The 4-part prompt structure (from the meeting): **#1 Goal** and **#4 Work
assignment** are the system prompt; **#2 Background** and **#3 Assumptions**
are collected from the user during intake.

## Local development

Requires Python 3.12 and a local (or Docker) PostgreSQL.

```bash
python3 -m venv .venv && source .venv/bin/activate
pip install -r requirements.txt

cp .env.example .env          # then edit: keys, model, DATABASE_URL, password
chainlit create-secret        # paste output into CHAINLIT_AUTH_SECRET in .env

psql "$DATABASE_URL" < schema.sql   # create Chainlit tables once

chainlit run app.py -w        # http://localhost:8000
```

Log in with `APP_USERNAME` / `APP_PASSWORD`, answer the two intake questions,
then continue the conversation. Restart the process and confirm the prior
thread reappears in the left sidebar (persistence check).

Switch provider by setting `LLM_PROVIDER=anthropic` and `ANTHROPIC_API_KEY`.

## Deploy to Heroku

```bash
heroku create <your-app>
heroku addons:create heroku-postgresql:essential-0 --app <your-app>

# Create the Chainlit tables in the add-on DB (run once):
heroku pg:psql --app <your-app> < schema.sql

# Config vars:
heroku config:set --app <your-app> \
  LLM_PROVIDER=openai \
  OPENAI_API_KEY=sk-... \
  OPENAI_MODEL=gpt-5.6-luna \
  APP_USERNAME=admin \
  APP_PASSWORD='choose-a-strong-password' \
  CHAINLIT_AUTH_SECRET="$(chainlit create-secret | tail -1)"
# DATABASE_URL is set automatically by the Postgres add-on.

git push heroku main
heroku open --app <your-app>
```

Notes:
- Heroku's `DATABASE_URL` uses the `postgres://` scheme and appends `sslmode`;
  `config.py` rewrites it to `postgresql+asyncpg://` and enables SSL. No manual
  fix needed.
- To use Claude instead: set `LLM_PROVIDER=anthropic`, `ANTHROPIC_API_KEY`, and
  optionally `ANTHROPIC_MODEL` / `ANTHROPIC_THINKING`.
- To change the goal/work-assignment prompt without redeploying code, set the
  `SYSTEM_PROMPT` config var (overrides the file).
