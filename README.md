# LuigiBot

A personal Discord bot for managing a to-do list and a separate discipline tracker directly from Discord.

## Features

- Create and manage to-do tasks with metadata (category, group, due date, priority, links, recurring cadence)
- View active tasks in a numbered embed and use buttons to start, pause, complete, or push to the weekend
- Track logged time as tasks move through statuses
- Auto re-add recurring tasks each morning when due
- Send daily to-do summaries and completed-task recaps
- Maintain a separate discipline tracker dataframe and completion log
- Surface discipline streaks, best streaks, 4-week consistency scores, and missed-target alerts
- View weekly partial-credit progress bars (X-of-Y with bar + percent) for each discipline
- Generate a weekly category-level adherence chart (e.g. Focus 90%, Health 60%)
- Receive an automatic midweek nudge listing disciplines that won't hit their weekly target at current pace
- Visualize the last 90 days of discipline activity as a GitHub-style heatmap
- Send a nightly discipline check-in with numbered buttons for quick logging

## Project Structure

```text
LuigiBot/
|-- main.py                       # Bot instance, commands, scheduler, event handlers
|-- luigi.db                      # SQLite database (default backend; Postgres is opt-in)
|-- bot_modules/                  # Helper package
|   |-- __init__.py
|   |-- bot_config.py             # Shared config (paths, channel IDs, prefix, DB backend + connection)
|   |-- db.py                     # Persistence layer (SQLAlchemy Core; SQLite or Postgres)
|   |-- chart_rendering.py        # Visual theme + all chart rendering functions
|   |-- discipline_helpers.py     # Discipline data processing, streaks, embeds
|   |-- follow_up_helpers.py      # Follow-up task creation helpers
|   |-- task_helpers.py           # To-do row builders, series builder, task embeds
|   |-- ui_components.py          # Discord Button/View classes
|   `-- required_functions.py     # Utility: extract_task_name
|-- requirements.txt
`-- config.json
```

## Prerequisites

- Python 3.9+
- A Discord bot token from the Discord Developer Portal
- Bot permissions:
  - Send Messages
  - Read Message History
  - Embed Links
  - Use Application Commands

## Setup

1. Install dependencies.

```bash
pip install -r requirements.txt
```

2. Create `config.json` in the project root.

```json
{
  "APPLICATION_ID": 123456789012345678,
  "PUBLIC_KEY": "your-public-key",
  "TOKEN": "your-discord-bot-token",
  "Channel_ID": 123456789012345678,
  "Channel_ID_to_do": 123456789012345678,
  "Channel_ID_discipline": 123456789012345678,
  "Database_Path": "luigi.db",
  "Discipline_Delete_After_Seconds": 7200,
  "Discipline_Daily_Hour": 23,
  "Discipline_Daily_Minute": 15,
  "Discipline_At_Risk_Weekday": 3,
  "Discipline_At_Risk_Hour": 17,
  "Discipline_At_Risk_Minute": 0,
  "User_ID": 123456789012345678
}
```

`Database_Path` is optional and defaults to `<repo>/luigi.db`. The `LUIGI_DB_PATH`
environment variable, if set, overrides the config value.

### Optional: Postgres backend

LuigiBot can run against a shared Postgres server instead of the local SQLite
file. SQLite remains the default; Postgres is opt-in.

Precedence for every field: **env var > `config.json` > code default**.

| Purpose               | Env var                | `config.json` key | Notes                                  |
|-----------------------|------------------------|-------------------|----------------------------------------|
| Backend selector      | `LUIGI_DB_BACKEND`     | `DB_Backend`      | `sqlite` (default) or `postgres`       |
| Full SA URL (optional)| `LUIGI_DATABASE_URL`   | `Database_URL`    | e.g. `postgresql+psycopg://user@host/db` |
| Host                  | `LUIGI_PG_HOST`        | `PG_Host`         | default `127.0.0.1`                    |
| Port                  | `LUIGI_PG_PORT`        | `PG_Port`         | default `5432`                         |
| Database              | `LUIGI_PG_DB`          | `PG_Database`     | default `luigi_todo`                   |
| User                  | `LUIGI_PG_USER`        | `PG_User`         | default `luigi_app`                    |
| Password              | `LUIGI_PG_PASSWORD`    | *(not read)*      | **env-only by design**                 |

The password is intentionally **not** read from `config.json` — that file already
holds the Discord bot token and should not accumulate more secrets. Set
`LUIGI_PG_PASSWORD` in the process environment (or use `LUIGI_DATABASE_URL` with
the password embedded, if your deployment prefers a single URL secret).

Postgres runs against a fresh empty DB created by `init_db()`. Copying existing
SQLite data into Postgres is a separate operational step (throwaway script or
`pgloader`); it is not part of the bot code.

3. Run the bot. The database file and its schema are created automatically on first run.

```bash
python main.py
```

## Command Activation

- Prefix commands use `!L `.
- To-do commands are hybrid and can be run as slash or prefix commands.
- Discipline commands are prefix-only to reduce slash command clutter.

## Commands

### To-Do Commands

- `/hello`
- `/to_do_list` or `!L to_do_list`
- `/create_task` or `!L create_task`
- `!L edit_task <id> field=value [field=value ...]`
- `!L delete_task <id>`
- `!L tasks [field:value ...]`

Editable fields for `edit_task`: `task_name`, `priority`, `due_date`, `category` (alias `catagory`), `group`, `subgroup`, `link`, `status`, `estimated_time`.

- `due_date` accepts `today` / `tmw` / `wk` / `YYYYMMDD`, or `none` to clear.
- `status` must be one of: `Not Started`, `In Progress`, `Pending`, `Blocked`, `Hiatus`, `Completed`.
- Wrap multi-word values in double quotes (e.g. `task_name="Refactor parser"`).
- `<id>` is the number shown next to a task by `!L to_do_list`.

Filter syntax for `tasks` — combine any of:

- `task:<substring>` / `category:<substring>` / `group:<substring>` / `subgroup:<substring>`
- `priority:>=7` (operators: `>=`, `<=`, `>`, `<`, `=`; bare number = equals)
- `status:<substring>` (e.g. `status:progress`)
- `due:today` / `due:tmw` / `due:week` / `due:overdue` / `due:none` / `due:any` / `due:YYYYMMDD` (also accepts `>= <= > <`)
- `link:any` / `link:none` / `link:<substring>`
- `include:completed` to also include completed rows (open-only by default)

### Discipline Commands (Prefix Only)

- `!L create_discipline_task <task_name> <catagory> <frequency_per_week>`
- `!L discipline_list`
- `!L log_discipline_completion <task_name> [completed_date]`
- `!L today_completions [date]`
- `!L weekly_discipline_report [week_start]`
- `!L discipline_streaks`
- `!L discipline_progress [reference_date]`
- `!L discipline_category_rollup [week_start]`
- `!L at_risk [reference_date]`
- `!L discipline_heatmap [days] [reference_date]`

`completed_date` / `date` / `week_start` format: `YYYYMMDD` (for example, `20260512`).

## Quick Start Examples

Use these as copy/paste examples once the bot is running.

```text
# To-do (hybrid commands)
/to_do_list
!L to_do_list

/create_task task_name:Gym catagory:Health priority:7 due_date:today
!L create_task Gym Health None None None False None today 7 1.5

# Edit / delete an existing open task (id from `!L to_do_list`)
!L edit_task 3 priority=9 due_date=tmw
!L edit_task 3 task_name="Deep Work Block" link=https://example.com
!L delete_task 3

# Search / filter open tasks
!L tasks category:Health
!L tasks priority:>=7 due:week
!L tasks group:"100 percent" status:progress
!L tasks due:overdue
!L tasks include:completed task:gym

# Discipline (prefix-only commands)
!L create_discipline_task "Deep Work" Focus 5
!L discipline_list
!L log_discipline_completion "Deep Work"
!L today_completions
!L today_completions 20260512
!L weekly_discipline_report
!L weekly_discipline_report 20260512
!L discipline_progress
!L discipline_progress 20260512
!L discipline_category_rollup
!L discipline_category_rollup 20260512
!L at_risk
!L discipline_heatmap
!L discipline_heatmap 60
```

Tips:

- For prefix commands, wrap multi-word task names in double quotes.
- If you skip a date for `today_completions`, LuigiBot uses today.

## Task Interaction

When you run the to-do list command, LuigiBot shows numbered task buttons. Selecting a task opens action buttons:

- Complete
- Start
- Pause
- Weekend (defer the task to the upcoming Saturday)

## Scheduled Events (ET)

- 7:45 AM: Check and re-add due recurring to-do tasks
- 8:00 AM: Daily active to-do summary
- 11:00 PM: Tasks completed today summary + completed-task visual
- 11:15 PM: Discipline nightly reminder with numbered completion buttons
- 11:30 PM: 15-minute post check-in discipline goal-status snapshot
- 5:00 PM Thursday: Midweek at-risk discipline nudge (configurable via `Discipline_At_Risk_*` keys)

## Data Storage

All bot state lives in a single database. By default this is `luigi.db` (SQLite) at the
project root; setting `LUIGI_DB_BACKEND=postgres` points the same code at a shared
Postgres server instead (see [Optional: Postgres backend](#optional-postgres-backend)).
Every module reads and writes through `bot_modules/db.py` — nothing else touches the
database directly. This makes it safe for a future web UI (e.g. FastAPI) to open the
same database concurrently without stepping on the running bot.

### Runtime characteristics

- **SQLite:** WAL mode with `synchronous=NORMAL`, `foreign_keys=ON`, and
  `busy_timeout=30000`. PRAGMAs are applied on every new connection via a
  SQLAlchemy `connect` event listener. Concurrent readers (bot + external tools)
  do not block each other.
- **Postgres:** MVCC handles concurrency server-side; no PRAGMAs apply.
  The engine is created with `pool_pre_ping=True` so stale connections on a
  long-lived bot process are transparently retried.
- **Whole-DataFrame save pattern**: `db.save_tasks_df(df)` etc. run a
  transactional `DELETE` + bulk `INSERT` inside `_ENGINE.begin()`. Under
  Postgres MVCC this is safe for concurrent readers (they see the pre-txn
  snapshot until COMMIT). Surrogate `id` values are not stable across saves
  on either engine — a documented consequence of the whole-table replace.

### Column naming

- **SQL columns are `snake_case`** because `GROUP` is a reserved word and mixed-case
  identifiers are painful in raw SQL. `group` becomes `task_group`, `SUB-GROUP` becomes
  `sub_group`, `RELEVANT LINK` becomes `relevant_link`.
- **DataFrame columns preserve the bot's historical spellings** (including the
  `CATAGORY` typo, ALL-CAPS names, and the space in `RELEVANT LINK`). Mapping
  dictionaries in `db.py` translate between the two on read/write.
- **Dates and timestamps** are stored as ISO-8601 `TEXT` and parsed back into pandas
  `Timestamp` on read.
- **Booleans** are stored as `INTEGER` 0/1 and coerced to `bool` on read.

### Schema

Schema version is tracked in the `schema_version` table (currently `1`).

#### `tasks` — active and completed to-do items

| SQL column           | DataFrame column      | Type      | Notes                                                     |
| -------------------- | --------------------- | --------- | --------------------------------------------------------- |
| `id`                 | *(index)*             | INTEGER   | Primary key, autoincrement.                               |
| `task`               | `TASK`                | TEXT      | Required. Task name.                                      |
| `priority`           | `PRIORITY`            | INTEGER   | 1–10. Default 1.                                          |
| `status`             | `STATUS`              | TEXT      | `Not Started`, `In Progress`, `Pending`, `Blocked`, `Hiatus`, `Completed`. |
| `due_date`           | `DUE DATE`            | TEXT      | ISO date, or `NULL`.                                      |
| `relevant_link`      | `RELEVANT LINK`       | TEXT      | Optional URL.                                             |
| `catagory`           | `CATAGORY`            | TEXT      | Free-form category (typo preserved intentionally).        |
| `task_group`         | `GROUP`               | TEXT      | Free-form group.                                          |
| `sub_group`          | `SUB-GROUP`           | TEXT      | Free-form subgroup.                                       |
| `task_creation`      | `TASK CREATION`       | TEXT      | ISO timestamp set on insert.                              |
| `start_time`         | `START TIME`          | TEXT      | ISO timestamp when the task last moved to `In Progress`.  |
| `estimated_time`     | `ESTIMATED TIME`      | REAL      | Estimated hours.                                          |
| `logged_hours`       | `LOGGED HOURS`        | REAL      | Accumulated hours logged. Default 0.                      |
| `completed`          | `COMPLETED`           | INTEGER   | 0/1 boolean. Default 0.                                   |
| `completed_time`     | `COMPLETED TIME`      | TEXT      | ISO timestamp when task moved to `Completed`.             |
| `recurring`          | `RECURRING`           | INTEGER   | 0/1 boolean. Default 0.                                   |
| `recurring_interval` | `RECURRING INTERVAL`  | INTEGER   | Days between recurrences.                                 |

Indexes: `idx_tasks_status`, `idx_tasks_due`.

#### `recurring_tasks` — template rows re-added on their cadence

Same column shape as `tasks`, but `recurring` defaults to 1. The 7:45 AM scheduler
reads this table and appends due rows into `tasks`.

#### `discipline_list` — the active discipline tracker

| SQL column           | DataFrame column     | Type    | Notes                                             |
| -------------------- | -------------------- | ------- | ------------------------------------------------- |
| `id`                 | *(index)*            | INTEGER | Primary key, autoincrement.                       |
| `task`               | `TASK`               | TEXT    | Required. Discipline name (e.g. `Deep Work`).     |
| `catagory`           | `CATAGORY`           | TEXT    | Free-form category (e.g. `Focus`, `Health`).      |
| `frequency_per_week` | `FREQUENCY_PER_WEEK` | INTEGER | Weekly target count. Default 1.                   |
| `active`             | `ACTIVE`             | INTEGER | 0/1 boolean. Default 1.                           |
| `current_streak`     | `CURRENT_STREAK`     | INTEGER | Refreshed every time a completion is logged.      |

#### `discipline_completions` — long-format completion log (source of truth)

| SQL column       | DataFrame column | Type    | Notes                                        |
| ---------------- | ---------------- | ------- | -------------------------------------------- |
| `id`             | *(index)*        | INTEGER | Primary key, autoincrement.                  |
| `task`           | `TASK`           | TEXT    | Required. Matches a `discipline_list.task`.  |
| `catagory`       | `CATAGORY`       | TEXT    | Snapshot of category at log time.            |
| `completed_date` | `COMPLETED_DATE` | TEXT    | ISO date. Required.                          |
| `logged_at`      | `LOGGED_AT`      | TEXT    | ISO timestamp of the log call.               |

Constraint: `UNIQUE(task, completed_date)` — one completion per task per day.
Indexes: `idx_disc_comp_date`, `idx_disc_comp_task`.

The old wide-format history matrix (one row per day, one column per discipline, `True/False/NA`)
is **not** stored as a table. `db.read_discipline_history()` rebuilds it on demand by
pivoting this table, so every downstream visual and streak calculation keeps working
unchanged.

#### `follow_up_tasks` — pending follow-up task definitions

| SQL column         | DataFrame column   | Type    | Notes                                                    |
| ------------------ | ------------------ | ------- | -------------------------------------------------------- |
| `id`               | *(index)*          | INTEGER | Primary key, autoincrement.                              |
| `trigger_task`     | `TRIGGER_TASK`     | TEXT    | The task whose completion triggers the follow-up.        |
| `follow_up_task`   | `FOLLOW_UP_TASK`   | TEXT    | Task name to create when the trigger completes.          |
| `catagory`         | `CATAGORY`         | TEXT    | Category for the created task.                           |
| `task_group`       | `GROUP`            | TEXT    | Group for the created task.                              |
| `subgroup`         | `SUB-GROUP`        | TEXT    | Subgroup for the created task.                           |
| `relevant_link`    | `RELEVANT LINK`    | TEXT    | Optional URL.                                            |
| `priority`         | `PRIORITY`         | INTEGER | Priority for the created task. Default 1.                |
| `estimated_time`   | `ESTIMATED TIME`   | REAL    | Estimated hours for the created task.                    |
| `due_offset_days`  | `DUE_OFFSET_DAYS`  | INTEGER | Days after trigger completion to set the due date.       |
| `created`          | `CREATED`          | TEXT    | ISO timestamp when the follow-up definition was added.   |

#### `schema_version`

Single-row table with an `INTEGER` version. Bumping this in `db.py` alongside a
migration is how future schema changes will be gated.

### Backups

**SQLite:** while the bot is stopped, copy `luigi.db` (and the `.db-wal` /
`.db-shm` files if present) to any location. To back up while the bot is running,
use `sqlite3 luigi.db ".backup 'backup.db'"` — the online backup API is safe
against the WAL.

**Postgres:** use standard Postgres tooling (`pg_dump`, base backups, or your
managed provider's snapshot feature). The bot writes nothing that requires
custom backup handling.

## Notes

- Nightly discipline reminders auto-delete after `Discipline_Delete_After_Seconds`.
- Startup message includes command activation details so usage is visible at boot.

## Potential Future Features

- **Per-day quantity logging**: change the discipline history matrix from `True/False/NA` to `int/NA` so a single day can record multiple units (e.g. 2 deep-work blocks counts as 2 toward a weekly target of 5). This is a larger change — it requires migrating existing data, updating the button UI to support `+1` / `-1`, and switching all weekly aggregations from `nunique` to `sum`.
- **Natural-language task input**: a `!L nl <text>` command that parses free-form input like `Gym tomorrow 7p #Health !8 ~30m` into the existing task fields (`TASK`, `DUE_DATE`, `PRIORITY`, `CATAGORY`, `ESTIMATED_DURATION`, `LINK`, `RECURRING_FREQUENCY`). Tier 1 would be a regex/keyword parser (`#cat`, `!priority`, `~duration`, date/time words, URLs) with a Confirm/Cancel preview embed; Tier 2 could add a date library like `dateparser`; Tier 3 could route to an LLM for fully free-form text. Deferred — the structured `add_task` flow is currently sufficient.

## Potential Code Cleanups (Pylance Warnings)

VS Code/Pylance currently reports ~80 static-type warnings in `main.py`. The bot runs fine — these are type-checker complaints, not runtime errors. Most are duplicates of the same few root causes. Future cleanup options:

- **Rename the `tasks` command function to stop shadowing the `discord.ext.tasks` module.** The file does `from discord.ext import commands, tasks` at the top and later defines `async def tasks(ctx, ...)` for the `!L tasks` search command. After that `def`, Pylance thinks `tasks` is a `Command`, which cascades into errors on `@tasks.loop(minutes=1)` and on the original import line. Fix: rename the function (e.g. `search_tasks`) while keeping `@bot.command(name="tasks", ...)` so the user-facing command stays `!L tasks`.
- **Narrow the return type of `bot.get_channel(...)`.** Discord.py types it as `GuildChannel | Thread | PrivateChannel | None`, which includes `ForumChannel` and `CategoryChannel` (no `.send`). Every `await channel.send(...)` therefore produces 3 errors (one per non-messageable subclass) — roughly half of the total. Fix: add a small helper like `def as_messageable(ch) -> discord.abc.Messageable: ...` (or use `typing.cast`) around `bot.get_channel(...)` results, with a runtime `isinstance(ch, discord.abc.Messageable)` check.
- **Tighten `resolve_task_index_from_position` return narrowing.** The helper returns `(None, None)` on a miss. `edit_task` and `delete_task` guard with `if df_index is None: return`, but Pylance doesn't propagate that narrowing to `target_row`, so `target_row["TASK"]` is flagged. Fix: add `assert target_row is not None` after the guard, or annotate the helper's return type as an overload.
- **Handle optional `view` on the nightly discipline send.** `view = DisciplineTaskView(pending_tasks) if pending_tasks else None` is then passed as `view=view` — discord.py accepts `None` at runtime, but the stub overload doesn't. Fix: pass `view=view or discord.utils.MISSING`, or split into two `send(...)` calls based on whether `view` exists.
