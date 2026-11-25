# NutriTrack

NutriTrack is a Flask nutrition tracker with a normalized SQLite catalogue, optional USDA FoodData Central search, optional Google OpenID Connect, meal history, and rule-based recipe suggestions.

## Requirements

- Python 3.10 or newer
- The INDB workbook `Anuvaad_INDB_2024_11.xlsx` for creating a fresh catalogue database. The workbook is excluded from Git; obtain and use it according to the Indian Nutrient Databank's distribution terms.
- Optional USDA FoodData Central API key
- Optional Google OAuth web client credentials

## Install and run locally

Windows PowerShell:

```powershell
python -m venv .venv
.\.venv\Scripts\Activate.ps1
python -m pip install -r requirements.txt
python -m pip install -r requirements-dev.txt
Copy-Item .env.example .env
```

macOS/Linux:

```bash
python3 -m venv .venv
source .venv/bin/activate
python -m pip install -r requirements.txt
python -m pip install -r requirements-dev.txt
cp .env.example .env
```

Set `FLASK_SECRET_KEY` in `.env` to a stable random value. Generate one with:

```bash
python -c "import secrets; print(secrets.token_urlsafe(48))"
```

`DATABASE_PATH` chooses the database. For a new checkout, initialize into a new path (the command refuses any existing file):

```bash
python -m scripts.init_db --db instance/nutritrack.sqlite3 --workbook data/Anuvaad_INDB_2024_11.xlsx
```

Set `DATABASE_PATH` to that same path in `.env`, then run:

```bash
python app.py
```

Open http://127.0.0.1:5000. If you already have the local populated `nutritrack_v2.db`, it remains the default when `DATABASE_PATH` is unset. Initialization and tests never target it unless you explicitly pass that exact path; the initializer refuses to proceed when the file exists.

## Environment variables

| Variable | Required | Purpose |
| --- | --- | --- |
| `FLASK_SECRET_KEY` | Production | Stable secret for signing sessions. There is no generated production fallback. |
| `APP_ENV` | Production | Set to `production` to enable secure session cookies and require the secret. |
| `DATABASE_PATH` | No | SQLite file location; defaults to `nutritrack_v2.db` beside `app.py`. Use persistent storage in deployment. |
| `USDA_API_KEY` | No | Enables USDA FoodData Central search and live nutrient verification. |
| `GOOGLE_CLIENT_ID` | No | Enables Google OpenID Connect when paired with its secret and the identity table. |
| `GOOGLE_CLIENT_SECRET` | No | Google OAuth client secret. Keep server-side only. |
| `TRUST_PROXY` | No | Set to `1` only behind exactly one trusted reverse proxy that sets forwarded headers. |

USDA search degrades to an empty result when the key is absent, the service times out, or a response is malformed. Local INDB search remains available. Google callback URLs must use the deployment's HTTPS host and be registered in Google Cloud Console.

## Database safety and initialization

- `schema.sql` is the sole canonical normalized **core schema** for new databases. It intentionally excludes tables owned by incremental migrations.
- `scripts/init_db.py` creates a **new** database from `schema.sql`, applies every numbered migration in order inside transactions, records applied versions in `schema_migrations`, then imports INDB foods, allergy tags, and curated recipes. It refuses every existing destination.
- Migrations `001_usda_meal_items.sql`, `002_google_identities.sql`, and `003_recipe_allergens.sql` are all required to bring the fresh core schema to the application's current schema. They use `IF NOT EXISTS`, and the migration ledger prevents duplicate application.
- `schema_legacy_v1.sql`, `schema_v2_legacy_destructive.sql`, and `schema_v2_actual_snapshot.sql` are preserved historical references. The first two contain destructive rebuild statements; none are used by the application or initializer.
- Curated allergies and recipes live in `scripts/reference_data.py`. There is no legacy seeder that writes to a hardcoded database.
- The existing `nutritrack.db`, `nutritrack_v2.db`, and all database backups are local-only and ignored by Git. Initialization does not inspect or update them.
- INDB diet/allergy classification is inferred from food names. It is useful for filtering, not a guarantee of safety for severe allergies. USDA allergy checks also depend on source declarations.

## Tests

Install the test dependencies in the active virtual environment from the project root:

```bash
python -m pip install -r requirements-dev.txt
```

This file includes the application dependencies plus pytest. Run the suite with:

```bash
python -m pytest -v
```

Tests create and destroy separate temporary SQLite databases. They cover signup/login, profile validation, local and USDA search behavior, allergy filtering, meal quantities and totals, history, ownership, health/readiness, and fresh initialization. The existing project databases are not opened by the test suite.

## Production server

On a Linux host, install dependencies and run Gunicorn with one worker when using SQLite:

```bash
gunicorn --bind 0.0.0.0:$PORT --workers 1 --threads 4 --timeout 30 app:app
```

SQLite supports multiple readers but is not a good shared-write database across several application workers or replicas. Keep one process/worker and place the DB on a persistent local disk. Back up that deployment DB separately. Do not use an ephemeral filesystem for SQLite: restarts and redeploys can erase it.

`/health` checks that the app can query its configured database. `/ready` checks that core application tables are present. Neither endpoint initializes or changes the database.

## Free hosting assessment

As of November 25, 2026, there is no free platform I can recommend as durable production for the current SQLite-backed app with all integrations enabled. Render's free web service has an ephemeral filesystem, so SQLite changes disappear on restart/redeploy/sleep; its free Postgres also expires after 30 days. [Render's free-plan documentation](https://render.com/docs/free) describes those limits.

For a no-cost **demo**, PythonAnywhere is the simplest fit because its account files persist and it supports Flask WSGI apps. Its current free account has only 100 CPU seconds, 512 MiB storage, one web worker, and a one-month web-app expiry; outbound requests are restricted to an allowlist. USDA and Google endpoints may need to be allowlisted, and free access can be suspended/expire. [PythonAnywhere free account limits](https://help.pythonanywhere.com/pages/FreeAccountsFeatures/), [outbound allowlist policy](https://help.pythonanywhere.com/pages/RequestingAllowlistAdditions). Treat this as a demo, not a reliable public production service.

### PythonAnywhere demo deployment outline

1. Create a PythonAnywhere Beginner account and clone this repository over HTTPS into your home directory.
2. Create a virtual environment, install `requirements.txt`, and upload the INDB workbook separately if permitted by its data terms.
3. In a Bash console, initialize a new database in your home directory, for example `python -m scripts.init_db --db /home/USERNAME/nutritrack.sqlite3 --workbook /home/USERNAME/Anuvaad_INDB_2024_11.xlsx`. Confirm the target does not already exist.
4. In the Web tab, create a manual Flask app using the same Python version/virtual environment. Update the WSGI file to add the project directory to `sys.path` and import `app` from the project.
5. Set `DATABASE_PATH`, `APP_ENV=production`, and a stable `FLASK_SECRET_KEY` in the WSGI startup configuration. Set USDA/Google credentials only if desired. Never upload a local `.env` file or any project DB/backup.
6. Set the Google authorized callback to `https://USERNAME.pythonanywhere.com/auth/google/callback`. Request allowlisting for documented USDA/Google endpoints as needed; otherwise leave those optional integrations disabled.
7. Reload the web app and check `/health`, `/ready`, registration, profile setup, search, and meal logging. Confirm the DB path is under persistent home storage and arrange your own backups.

For continuous public use, budget for a host with persistent storage and unrestricted outbound HTTPS (or explicitly choose and operate a separate managed DB). Do not select a free ephemeral web service while keeping SQLite as the persistent store.

## Security and operational notes

- Parameterized SQL, password hashing, CSRF validation on state-changing requests, ownership checks, and private/no-store response headers are enabled.
- Production cookies are `Secure`, `HttpOnly`, and `SameSite=Lax` when `APP_ENV=production`.
- `TRUST_PROXY=1` trusts one proxy hop. Do not enable it when requests can bypass that proxy.
- USDA requests have explicit timeouts; API keys never go to browser JavaScript.
- Keep `.env`, credentials, database files, backups, and deployment secrets out of Git.
- Review INDB attribution/licensing before redistributing its workbook or derived catalogue publicly.

## Project layout

```text
app.py
schema.sql                         # canonical normalized core schema
schema_legacy_v1.sql               # historical denormalized schema
schema_v2_legacy_destructive.sql   # historical DROP/CREATE rebuild
schema_v2_actual_snapshot.sql      # historical integrated schema snapshot
migrations/                        # numbered additive schema changes
scripts/init_db.py                 # safe fresh-database workflow
scripts/import_indb.py             # workbook importer
scripts/reference_data.py          # allergy and recipe seed records
data/                              # source INDB workbook (supply separately)
templates/                         # Jinja pages
static/                             # CSS and frontend assets
tests/                              # isolated temporary-database tests
README.md
.env.example
```
