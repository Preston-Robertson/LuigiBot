# LuigiBot — Postgres Backend Support (Change Report)

_Change to `Preston-Robertson/LuigiBot`. Implements
`docs_POSTGRES_SUPPORT_SPEC_Version2.md` as revised by
`POSTGRES_SUPPORT_SPEC_REVISIONS.md`. Default backend stays SQLite; Postgres
is opt-in via a single env var. Public API of `bot_modules/db.py` is
unchanged — no other module was modified._

---

## What this change does

Adds a second persistence backend (Postgres) behind the existing `db.py`
public API by routing all reads/writes through a single SQLAlchemy Core
engine that is built once at import time from configuration.

- `LUIGI_DB_BACKEND=sqlite` (default) → engine points at `luigi.db`; behavior
  identical to before.
- `LUIGI_DB_BACKEND=postgres` → engine points at a shared Postgres server
  using either `LUIGI_DATABASE_URL` or the discrete `PG_*` fields.

No callers changed. `main.py`, `task_helpers.py`, `discipline_helpers.py`,
`follow_up_helpers.py`, and `ui_components.py` are byte-identical to before.

## Files changed

| File | Change |
|---|---|
| `requirements.txt` | Added `SQLAlchemy>=2.0` and `psycopg[binary]>=3.1` |
| `bot_modules/bot_config.py` | Added `db_backend`, `database_url`, `pg_host`, `pg_port`, `pg_database`, `pg_user`, `pg_password` |
| `bot_modules/db.py` | Full rewrite of internals onto SQLAlchemy Core (public API unchanged) |
| `README.md` | New "Optional: Postgres backend" section; dual-engine runtime and backup notes |

Nothing else in the repo was touched.

## Configuration surface (added)

Every field: **env var wins > `config.json` > code default**. The password is
the only field with no `config.json` fallback.

| Purpose | Env var | `config.json` key | Default |
|---|---|---|---|
| Backend selector | `LUIGI_DB_BACKEND` | `DB_Backend` | `sqlite` |
| Full SQLAlchemy URL | `LUIGI_DATABASE_URL` | `Database_URL` | *(none)* |
| PG host | `LUIGI_PG_HOST` | `PG_Host` | `127.0.0.1` |
| PG port | `LUIGI_PG_PORT` | `PG_Port` | `5432` |
| PG database | `LUIGI_PG_DB` | `PG_Database` | `luigi_todo` |
| PG user | `LUIGI_PG_USER` | `PG_User` | `luigi_app` |
| PG password | `LUIGI_PG_PASSWORD` | *(not read)* | `""` |

SQLite path resolution (unchanged): `LUIGI_DB_PATH` env > `Database_Path` in
config > `<repo>/luigi.db`.

## Design decisions (per revisions doc)

- **Single engine per process.** Built once at `db.py` import via
  `_make_engine()`; reused for the life of the bot. `pool_pre_ping=True` on
  Postgres so long-lived connections survive network blips.
- **Windows-safe SQLite URL.** `URL.create("sqlite", database=database_path)`
  instead of string concat, so `C:\...\luigi.db` doesn't need special quoting.
- **PRAGMAs via `@event.listens_for(engine, "connect")`, sqlite-only.**
  Every new SQLite connection still gets WAL, `synchronous=NORMAL`,
  `foreign_keys=ON`, and `busy_timeout=30000`. Postgres gets none of these
  (MVCC handles it).
- **DDL branch is minimal.** The only per-engine DDL difference is the
  identity column:
  - SQLite: `INTEGER PRIMARY KEY AUTOINCREMENT`
  - Postgres: `INTEGER GENERATED ALWAYS AS IDENTITY PRIMARY KEY`
  All other column types are identical on both engines, including booleans
  stored as `INTEGER` 0/1.
- **Booleans stay INTEGER on Postgres.** Not native `BOOLEAN`. Reason:
  psycopg3 rejects Python `int → boolean` coercion at insert time, and the
  existing write path everywhere sends `_to_bool_int(...) → 0/1`. Keeping
  `INTEGER` means zero read-side changes.
- **Whole-table replace on writes, kept for v1.** `save_tasks_df`,
  `save_recurring_df`, `save_discipline_df`, `save_follow_ups` all do
  `DELETE FROM <table>` + bulk `INSERT` inside `_ENGINE.begin()`. Postgres
  MVCC guarantees concurrent readers see the pre-transaction snapshot until
  COMMIT — no partial-state reads. Per-row upserts were deferred: the DF
  does not carry the surrogate `id`, and there is no other stable business
  key on these tables, so a pure upsert would silently drop delete
  semantics. Revisit only when the DF grows an `id` column (out of scope).
- **Dialect-specific upsert lives in exactly one function.**
  `append_discipline_completion` uses `INSERT OR IGNORE` on SQLite and
  `INSERT ... ON CONFLICT (task, completed_date) DO NOTHING` on Postgres.
  Both return `rowcount=1` on insert, `0` on skip, so the caller contract
  is identical.
- **`get_connection()` removed.** It was internal-only and its
  `sqlite3.Connection` API (positional `?` params, `executescript`,
  `cursor.rowcount`, `Row["col"]`) does not survive on SA `Connection`.
  Every internal call site now uses:
  - `_ENGINE.connect()` for reads,
  - `_ENGINE.begin()` for writes,
  - `sqlalchemy.text("... :name ...")` + named parameter dicts.

## Security decisions

- **`LUIGI_PG_PASSWORD` is env-only.** No `config.get("PG_Password")`
  fallback. `config.json` already holds the Discord bot token; adding
  another secret would widen the "secrets sitting in a repo-adjacent file"
  problem.
- **`config.json` remains gitignored** (verified in `.gitignore`).

## What is deliberately NOT in this change

- No data migration from SQLite → Postgres. First Postgres run creates a
  fresh empty database via `init_db()`. Any bulk copy of existing data is a
  separate operational task (throwaway script or `pgloader`).
- No per-row upserts. Whole-table replace is kept for v1.
- No native Postgres `BOOLEAN` / `DATE` / `TIMESTAMP` columns. Storage
  remains ISO-8601 `TEXT` for dates and `INTEGER` 0/1 for booleans on both
  engines, matching the existing SQLite behavior byte-for-byte on the
  DataFrame side.
- No changes to any module outside `bot_modules/`.
- No lint/type-checker cleanup, refactoring, or behavior tweaks unrelated
  to the backend swap.

## Verification performed on SQLite

The existing `luigi.db` was used as the fixture (18 tasks, 4 recurring, 6
discipline entries, 41 completions, 0 follow-ups).

- `init_db()` idempotent; row counts unchanged after the rewrite.
- `load_*` → `save_*` → `load_*` round-trip on all four list DataFrames:
  shapes and values preserved, NaN masks identical.
- `read_discipline_history()` still returns the expected 63×6 matrix.
- `append_discipline_completion` returns `True` on insert / `False` on
  duplicate; `delete_discipline_completion` returns `True` when a row was
  removed; `is_task_completed_on` live-lookup path works.
- `py_compile` clean on `main.py` and every module in `bot_modules/`.

Postgres path was not exercised — no server was configured in this
workspace. First real Postgres run is expected to happen against a fresh
empty DB as part of the deployment runbook.

## Follow-ups that this change enables but does NOT do

- Stand up the shared Postgres server + role/grants. That's the
  environment-setup runbook, not this code.
- Copy existing SQLite data into the new Postgres DB. Separate script or
  `pgloader` one-shot.
- Web GUI or any other secondary reader/writer against the shared DB. The
  bot is now MVCC-safe under concurrent connections; that's all.
- Migrate discipline history from `bool` → `int` for per-day quantity
  logging. Independent feature.
- Switch the four list-table writes to per-row upserts. Requires the DF to
  carry a stable `id`. Independent refactor.

## Rollback

Revert the four files listed above. No DB migration to undo (schema is
identical to before on SQLite; Postgres tables never existed).
