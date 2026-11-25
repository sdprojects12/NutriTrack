# NutriTrack deployment readiness audit (pre-change)

Date: 2026-11-25

## Scope and safety

Inspected application routes and database access, templates/static asset references, SQL schemas, migrations, workbook importer, legacy seeder, requirements, README, Git tracking state, and SQLite schema/count metadata. All four SQLite database files were inspected through SQLite read-only URI connections. No database or backup was modified.

## Architecture and active data

- Flask/Jinja application in `app.py`; SQLite, server-rendered templates, and JavaScript search UI.
- `app.py` currently hardcodes `nutritrack_v2.db` under the source directory.
- `nutritrack_v2.db` is the normalized active database (1,014 foods, 11 categories, 9 allergens, 15 recipes, 11 meals, USDA snapshot and Google identity tables).
- `nutritrack.db` is a separate legacy schema (denormalized foods/allergies; 1,014 foods, 15 recipes, 6 meals). It is also the hardcoded target of `seed_data.py`.
- The two named backups are normalized-schema snapshots with earlier meal/account counts. All DBs and backups remain untouched.

## Findings by severity

### Critical

- The production secret key silently falls back to a new random key at each process start, invalidating sessions across restarts/workers. Production should fail fast if the environment variable is absent; local development can use an explicitly documented local-only fallback.
- Signup commits the user and profile in separate transactions. Profile failure can leave an incomplete account. Google first-time account/profile/identity writes have the same partial-commit risk.
- `seed_data.py` is incompatible with the active normalized schema and targets legacy `nutritrack.db`; it deletes all foods/recipes before insertion. It must not be used to initialize production.

### High

- No configurable database path or safe fresh database initialization process exists. The current runtime expects an already-populated normalized schema.
- The deployment docs recommend `FLASK_ENV=production`, but current Flask versions no longer use it to configure production; cookie security should be explicit and proxy/HTTPS behavior documented/configured.
- `.env` is not tracked, but its local contents include third-party credentials. Treat credentials stored there as sensitive; no values are repeated in this report.
- Google OAuth state/session behavior, account writes, USDA failures, and ownership paths need regression coverage using isolated temporary DBs.
- The existing README has migration instructions against the valuable local active DB, which are unsafe as generic setup guidance.

### Medium

- Schema files are not one consistent source: `schema.sql` is historical/legacy; `schema_v2.sql` is a destructive rebuild definition containing DROP statements; `schema_v2_actual.sql` is an additive reference snapshot of the normalized current schema. Existing migration files add the USDA snapshot and Google identity tables; both target tables are already present in active DB.
- The workbook importer expects a checked-in workbook path, while `.gitignore` excludes all `.xlsx` files. A fresh deployment cannot seed food records unless the workbook is supplied separately or bundled intentionally.
- Requirements lack a production WSGI server and pinned/test dependency setup.
- No automated tests are present.

## Proposed safe stabilization

1. Keep every existing `.db` and backup read-only; introduce `DATABASE_PATH` and a standalone initializer that refuses any existing target, creates only a new file, uses the normalized v2 snapshot plus safe idempotent migration checks, and imports reference data transactionally.
2. Make signup and Google account creation transactional; harden startup secret handling, cookie/proxy configuration, USDA request bounds/error behavior, and health endpoint.
3. Add isolated temporary-database automated tests covering the requested core paths; do not invoke tests against project DB files.
4. Add Gunicorn, deployment environment configuration, updated README and ignore rules.
5. Choose a host only after checking current free-plan/persistent-disk facts; SQLite requires a persistent mounted disk, so ephemeral filesystem hosting is not suitable.

## Database risk

Initialization must only run against a new explicitly chosen path. The legacy seeder remains unsafe for the normalized schema and must be replaced or clearly fenced. The schema snapshot is suitable as the starting point for a fresh normalized DB; the two additive migrations should be applied only when their tables are absent. No destructive SQL should run against any existing project database.

## Database architecture cleanup update

This report's earlier findings preserve the filenames present during the initial audit. The active layout now uses `schema.sql` as the normalized core schema, followed by migrations `001` through `003`; `scripts/init_db.py` applies them transactionally and records their filenames in `schema_migrations`. The prior schema files were retained under historical/destructive names. Recipe and allergy seed constants now live in `scripts/reference_data.py`; the obsolete `seed_data.py` writer was removed after its runtime, initializer, test, and README references were cleared.
