"""Persistence layer for LuigiBot (SQLite default, Postgres opt-in).

Single source of truth for all bot data. Every other module reads/writes
via the helpers here; nothing else should touch sqlite3, psycopg, or the
.pkl files.

Design notes
------------
- Runs on either SQLite (default) or Postgres via SQLAlchemy Core. Backend
  is selected once at import from `bot_config.db_backend` ("sqlite" |
  "postgres"). Public API is identical on both engines.
- Column names on the DataFrame side are preserved *exactly* as the bot
  already uses them (including the `CATAGORY` spelling and the `GROUP` /
  `SUB-GROUP` / `RELEVANT LINK` spacing). SQL columns are snake_case
  because `GROUP` is a reserved word.
- Dates/timestamps are stored as ISO-8601 TEXT and parsed back on read
  (same on both engines — deliberate, to keep the codepath uniform).
- Booleans are stored as INTEGER 0/1 on both engines (psycopg3 rejects
  int -> bool coercion, so native BOOLEAN would break the write path).
- `discipline_history` is *not* a table — it's rebuilt from the long
  `discipline_completions` table on demand.
- The four list tables (`tasks`, `recurring_tasks`, `discipline_list`,
  `follow_up_tasks`) use whole-DataFrame replace inside a single
  transaction. On Postgres this is MVCC-safe: concurrent readers see
  the pre-txn snapshot until COMMIT, never an empty table.
"""
from __future__ import annotations

import os
import threading
import uuid as _uuid
from typing import Iterable, Optional

import pandas as pd
from sqlalchemy import URL, create_engine, event, text
from sqlalchemy.engine import Engine

from .bot_config import (
    database_path,
    database_url,
    db_backend,
    pg_database,
    pg_host,
    pg_password,
    pg_port,
    pg_user,
)


SCHEMA_VERSION = 2

# Tables that use whole-DataFrame replace + carry a stable `uuid` (schema v2).
# `discipline_completions` is intentionally excluded (append-only with its own
# natural key `UNIQUE(task, completed_date)`).
_UUID_TABLES = ("tasks", "recurring_tasks", "discipline_list", "follow_up_tasks")

_INIT_LOCK = threading.Lock()
_INITIALIZED = False


# --- Engine construction -----------------------------------------------------

def _make_engine() -> Engine:
    """Build the SQLAlchemy engine for the configured backend.

    SQLite path uses URL.create so Windows absolute paths (C:\\...) are
    quoted safely. Postgres path prefers a full URL if the user supplied
    one; otherwise it assembles psycopg3 driver URL from discrete parts.
    """
    if db_backend == "postgres":
        if database_url:
            url = database_url
        else:
            url = URL.create(
                "postgresql+psycopg",
                username=pg_user,
                password=pg_password or None,
                host=pg_host,
                port=pg_port,
                database=pg_database,
            )
        # pool_pre_ping guards against stale connections on a long-lived bot.
        return create_engine(url, pool_pre_ping=True, future=True)

    # Default: SQLite
    url = URL.create("sqlite", database=database_path)
    engine = create_engine(url, future=True)

    @event.listens_for(engine, "connect")
    def _set_sqlite_pragmas(dbapi_conn, _record):  # noqa: ANN001
        cur = dbapi_conn.cursor()
        cur.execute("PRAGMA journal_mode=WAL")
        cur.execute("PRAGMA synchronous=NORMAL")
        cur.execute("PRAGMA foreign_keys=ON")
        cur.execute("PRAGMA busy_timeout=30000")
        cur.close()

    return engine


_ENGINE: Engine = _make_engine()
_IS_POSTGRES = db_backend == "postgres"


# --- Schema ------------------------------------------------------------------

def _id_ddl() -> str:
    """Dialect-specific auto-increment primary key column definition."""
    if _IS_POSTGRES:
        return "id INTEGER GENERATED ALWAYS AS IDENTITY PRIMARY KEY"
    return "id INTEGER PRIMARY KEY AUTOINCREMENT"


def _ddl_statements() -> list[str]:
    """All DDL as individual statements. SA connections execute one at a time
    (unlike sqlite3.executescript), so keep these split."""
    id_col = _id_ddl()
    return [
        f"""
        CREATE TABLE IF NOT EXISTS tasks (
            {id_col},
            task               TEXT    NOT NULL,
            priority           INTEGER DEFAULT 1,
            status             TEXT    DEFAULT 'Not Started',
            due_date           TEXT,
            relevant_link      TEXT,
            catagory           TEXT,
            task_group         TEXT,
            sub_group          TEXT,
            task_creation      TEXT,
            start_time         TEXT,
            estimated_time     REAL,
            logged_hours       REAL    DEFAULT 0,
            completed          INTEGER DEFAULT 0,
            completed_time     TEXT,
            recurring          INTEGER DEFAULT 0,
            recurring_interval INTEGER,
            uuid               TEXT
        )
        """,
        "CREATE INDEX IF NOT EXISTS idx_tasks_status ON tasks(status)",
        "CREATE INDEX IF NOT EXISTS idx_tasks_due    ON tasks(due_date)",
        f"""
        CREATE TABLE IF NOT EXISTS recurring_tasks (
            {id_col},
            task               TEXT    NOT NULL,
            priority           INTEGER DEFAULT 1,
            status             TEXT    DEFAULT 'Not Started',
            due_date           TEXT,
            relevant_link      TEXT,
            catagory           TEXT,
            task_group         TEXT,
            sub_group          TEXT,
            task_creation      TEXT,
            start_time         TEXT,
            estimated_time     REAL,
            logged_hours       REAL    DEFAULT 0,
            completed          INTEGER DEFAULT 0,
            completed_time     TEXT,
            recurring          INTEGER DEFAULT 1,
            recurring_interval INTEGER,
            uuid               TEXT
        )
        """,
        f"""
        CREATE TABLE IF NOT EXISTS discipline_list (
            {id_col},
            task               TEXT    NOT NULL,
            catagory           TEXT,
            frequency_per_week INTEGER DEFAULT 1,
            active             INTEGER DEFAULT 1,
            current_streak     INTEGER DEFAULT 0,
            uuid               TEXT
        )
        """,
        f"""
        CREATE TABLE IF NOT EXISTS discipline_completions (
            {id_col},
            task           TEXT NOT NULL,
            catagory       TEXT,
            completed_date TEXT NOT NULL,
            logged_at      TEXT,
            UNIQUE(task, completed_date)
        )
        """,
        "CREATE INDEX IF NOT EXISTS idx_disc_comp_date ON discipline_completions(completed_date)",
        "CREATE INDEX IF NOT EXISTS idx_disc_comp_task ON discipline_completions(task)",
        f"""
        CREATE TABLE IF NOT EXISTS follow_up_tasks (
            {id_col},
            trigger_task    TEXT NOT NULL,
            follow_up_task  TEXT NOT NULL,
            catagory        TEXT,
            task_group      TEXT,
            subgroup        TEXT,
            relevant_link   TEXT,
            priority        INTEGER DEFAULT 1,
            estimated_time  REAL,
            due_offset_days INTEGER,
            created         TEXT,
            uuid            TEXT
        )
        """,
        "CREATE TABLE IF NOT EXISTS schema_version (version INTEGER NOT NULL)",
    ]


def _column_exists(conn, table: str, column: str) -> bool:
    """Dialect-agnostic column existence check (SQLite pragma / PG info_schema)."""
    if _IS_POSTGRES:
        row = conn.execute(
            text(
                "SELECT 1 FROM information_schema.columns "
                "WHERE table_schema = current_schema() "
                "  AND table_name = :t AND column_name = :c LIMIT 1"
            ),
            {"t": table, "c": column},
        ).first()
    else:
        row = conn.execute(
            text("SELECT 1 FROM pragma_table_info(:t) WHERE name = :c LIMIT 1"),
            {"t": table, "c": column},
        ).first()
    return row is not None


def _migrate_to_v2(conn) -> None:
    """Idempotent v1 -> v2 migration: add `uuid TEXT`, backfill, add unique index.

    Owns the uuid indexes for both fresh (v0 -> v2) and legacy (v1 -> v2) paths
    so DDL never tries to index a column that hasn't been ALTERed in yet. Safe
    to run repeatedly. Backfill is done in Python for dialect uniformity and
    runs BEFORE the unique index is created so legacy nulls don't collide.
    """
    # 1. Add the column where missing.
    for table in _UUID_TABLES:
        if not _column_exists(conn, table, "uuid"):
            conn.execute(text(f"ALTER TABLE {table} ADD COLUMN uuid TEXT"))
    # 2. Backfill NULL uuids row-by-row (dialect-uniform).
    for table in _UUID_TABLES:
        null_rows = conn.execute(
            text(f"SELECT id FROM {table} WHERE uuid IS NULL")
        ).all()
        for r in null_rows:
            conn.execute(
                text(f"UPDATE {table} SET uuid = :u WHERE id = :i"),
                {"u": str(_uuid.uuid4()), "i": r.id},
            )
    # 3. Ensure the unique index exists (no-op if DDL already created it).
    for table in _UUID_TABLES:
        conn.execute(
            text(f"CREATE UNIQUE INDEX IF NOT EXISTS idx_{table}_uuid ON {table}(uuid)")
        )


def init_db() -> None:
    """Create the DB (and parent dirs for SQLite) and all tables if missing. Idempotent."""
    global _INITIALIZED
    if _INITIALIZED:
        return
    with _INIT_LOCK:
        if _INITIALIZED:
            return
        if not _IS_POSTGRES:
            os.makedirs(
                os.path.dirname(os.path.abspath(database_path)) or ".",
                exist_ok=True,
            )
        with _ENGINE.begin() as conn:
            # On Postgres, CREATE INDEX (even IF NOT EXISTS) requires table
            # ownership. When the schema is pre-provisioned by a different
            # role (limited DML-only bot user), skip DDL entirely.
            skip_ddl = _IS_POSTGRES and conn.execute(
                text("SELECT to_regclass('public.tasks')")
            ).scalar() is not None
            if not skip_ddl:
                for stmt in _ddl_statements():
                    conn.execute(text(stmt))
            existing = conn.execute(
                text("SELECT version FROM schema_version LIMIT 1")
            ).first()
            current_version = int(existing.version) if existing is not None else 0
            if current_version < SCHEMA_VERSION:
                # Run migration (safe on fresh DBs too — becomes a no-op there).
                _migrate_to_v2(conn)
                if existing is None:
                    conn.execute(
                        text("INSERT INTO schema_version (version) VALUES (:v)"),
                        {"v": SCHEMA_VERSION},
                    )
                else:
                    conn.execute(
                        text("UPDATE schema_version SET version = :v"),
                        {"v": SCHEMA_VERSION},
                    )
        _INITIALIZED = True


# --- Column mappings (SQL <-> DataFrame) -------------------------------------
# The DataFrame side matches what the bot already expects; the SQL side is
# snake_case to avoid reserved-word collisions.

_TASKS_SQL_TO_DF = {
    "task": "TASK",
    "priority": "PRIORITY",
    "status": "STATUS",
    "due_date": "DUE DATE",
    "relevant_link": "RELEVANT LINK",
    "catagory": "CATAGORY",
    "task_group": "GROUP",
    "sub_group": "SUB-GROUP",
    "task_creation": "TASK CREATION",
    "start_time": "START TIME",
    "estimated_time": "ESTIMATED TIME",
    "logged_hours": "LOGGED HOURS",
    "completed": "COMPLETED",
    "completed_time": "COMPLETED TIME",
    "recurring": "RECURRING",
    "recurring_interval": "RECURRING INTERVAL",
    "uuid": "UUID",
}
_TASKS_DF_TO_SQL = {v: k for k, v in _TASKS_SQL_TO_DF.items()}

_TASKS_DATE_COLUMNS = ("DUE DATE", "TASK CREATION", "START TIME", "COMPLETED TIME")
_TASKS_BOOL_COLUMNS = ("COMPLETED", "RECURRING")
_TASKS_INT_COLUMNS = ("PRIORITY", "RECURRING INTERVAL")
_TASKS_FLOAT_COLUMNS = ("ESTIMATED TIME", "LOGGED HOURS")

_DISCIPLINE_SQL_TO_DF = {
    "task": "TASK",
    "catagory": "CATAGORY",
    "frequency_per_week": "FREQUENCY_PER_WEEK",
    "active": "ACTIVE",
    "current_streak": "CURRENT_STREAK",
    "uuid": "UUID",
}
_DISCIPLINE_DF_TO_SQL = {v: k for k, v in _DISCIPLINE_SQL_TO_DF.items()}

_COMPLETIONS_SQL_TO_DF = {
    "task": "TASK",
    "catagory": "CATAGORY",
    "completed_date": "COMPLETED_DATE",
    "logged_at": "LOGGED_AT",
}
_COMPLETIONS_DF_TO_SQL = {v: k for k, v in _COMPLETIONS_SQL_TO_DF.items()}

_FOLLOW_UP_SQL_TO_DF = {
    "trigger_task": "TRIGGER_TASK",
    "follow_up_task": "FOLLOW_UP_TASK",
    "catagory": "CATAGORY",
    "task_group": "GROUP",
    "subgroup": "SUBGROUP",
    "relevant_link": "RELEVANT_LINK",
    "priority": "PRIORITY",
    "estimated_time": "ESTIMATED_TIME",
    "due_offset_days": "DUE_OFFSET_DAYS",
    "created": "CREATED",
    "uuid": "UUID",
}
_FOLLOW_UP_DF_TO_SQL = {v: k for k, v in _FOLLOW_UP_SQL_TO_DF.items()}

FOLLOW_UP_DF_COLUMNS = [
    "TRIGGER_TASK",
    "FOLLOW_UP_TASK",
    "CATAGORY",
    "GROUP",
    "SUBGROUP",
    "RELEVANT_LINK",
    "PRIORITY",
    "ESTIMATED_TIME",
    "DUE_OFFSET_DAYS",
    "CREATED",
    "UUID",
]

TASK_DF_COLUMNS = [
    "TASK",
    "TASK CREATION",
    "CATAGORY",
    "GROUP",
    "SUB-GROUP",
    "RELEVANT LINK",
    "RECURRING",
    "RECURRING INTERVAL",
    "DUE DATE",
    "PRIORITY",
    "STATUS",
    "START TIME",
    "ESTIMATED TIME",
    "LOGGED HOURS",
    "COMPLETED",
    "COMPLETED TIME",
    "UUID",
]

DISCIPLINE_DF_COLUMNS = ["TASK", "CATAGORY", "FREQUENCY_PER_WEEK", "ACTIVE", "CURRENT_STREAK", "UUID"]
COMPLETION_DF_COLUMNS = ["TASK", "CATAGORY", "COMPLETED_DATE", "LOGGED_AT"]


# --- Serialization helpers ---------------------------------------------------

def _iso_or_none(value):
    """Serialize a scalar to ISO string / int / float / None for the DB."""
    if value is None:
        return None
    try:
        if pd.isna(value):
            return None
    except (TypeError, ValueError):
        pass
    if isinstance(value, (pd.Timestamp,)):
        return value.isoformat(sep=" ")
    if isinstance(value, (bool,)):
        return 1 if value else 0
    if hasattr(value, "isoformat"):
        return value.isoformat()
    return value


def _to_bool_int(value) -> int:
    if value is None:
        return 0
    try:
        if pd.isna(value):
            return 0
    except (TypeError, ValueError):
        pass
    return 1 if bool(value) else 0


def _to_int_or_none(value):
    if value is None:
        return None
    try:
        if pd.isna(value):
            return None
    except (TypeError, ValueError):
        pass
    try:
        return int(value)
    except (TypeError, ValueError):
        return None


def _to_float_or_none(value):
    if value is None:
        return None
    try:
        if pd.isna(value):
            return None
    except (TypeError, ValueError):
        pass
    try:
        return float(value)
    except (TypeError, ValueError):
        return None


def _uuid_or_new(value) -> str:
    """Return an existing uuid string, or mint a fresh uuid4 if missing/blank.

    This is what makes uuids survive the whole-table-rewrite save pattern: rows
    coming back from `load_*` carry their uuid, and rows built fresh by the bot
    (no uuid yet) get one minted on first save.
    """
    if value is None:
        return str(_uuid.uuid4())
    try:
        if pd.isna(value):
            return str(_uuid.uuid4())
    except (TypeError, ValueError):
        pass
    s = str(value).strip()
    return s if s else str(_uuid.uuid4())


def _tasks_row_to_sql_params(row: pd.Series, sql_columns: Iterable[str]) -> dict:
    """Convert a task-shaped Series -> dict keyed by SQL column names."""
    out: dict = {}
    for sql_col in sql_columns:
        df_col = _TASKS_SQL_TO_DF[sql_col]
        value = row.get(df_col)
        if sql_col == "uuid":
            out[sql_col] = _uuid_or_new(value)
        elif df_col in _TASKS_BOOL_COLUMNS:
            out[sql_col] = _to_bool_int(value)
        elif df_col in _TASKS_INT_COLUMNS:
            out[sql_col] = _to_int_or_none(value)
        elif df_col in _TASKS_FLOAT_COLUMNS:
            out[sql_col] = _to_float_or_none(value)
        elif df_col in _TASKS_DATE_COLUMNS:
            out[sql_col] = _iso_or_none(
                pd.to_datetime(value, errors="coerce") if value is not None else None
            )
        else:
            v = _iso_or_none(value)
            out[sql_col] = None if v is None else str(v)
    return out


def _empty_task_df() -> pd.DataFrame:
    return pd.DataFrame(columns=TASK_DF_COLUMNS)


def _empty_discipline_df() -> pd.DataFrame:
    return pd.DataFrame(columns=DISCIPLINE_DF_COLUMNS)


def _empty_completion_df() -> pd.DataFrame:
    return pd.DataFrame(columns=COMPLETION_DF_COLUMNS)


def _empty_follow_up_df() -> pd.DataFrame:
    return pd.DataFrame(columns=FOLLOW_UP_DF_COLUMNS)


# --- Tasks -------------------------------------------------------------------

_TASKS_SQL_COLS = list(_TASKS_SQL_TO_DF.keys())


def _read_task_table(table_name: str) -> pd.DataFrame:
    init_db()
    with _ENGINE.connect() as conn:
        df = pd.read_sql_query(text(f"SELECT * FROM {table_name}"), conn)
    if df.empty:
        return _empty_task_df()
    if "id" in df.columns:
        df = df.drop(columns=["id"])
    df = df.rename(columns=_TASKS_SQL_TO_DF)
    for col in _TASKS_DATE_COLUMNS:
        if col in df.columns:
            df[col] = pd.to_datetime(df[col], errors="coerce")
    for col in _TASKS_BOOL_COLUMNS:
        if col in df.columns:
            df[col] = df[col].fillna(0).astype(int).astype(bool)
    if "PRIORITY" in df.columns:
        df["PRIORITY"] = pd.to_numeric(df["PRIORITY"], errors="coerce").fillna(1).astype(int)
    if "RECURRING INTERVAL" in df.columns:
        df["RECURRING INTERVAL"] = pd.to_numeric(df["RECURRING INTERVAL"], errors="coerce")
    for col in _TASKS_FLOAT_COLUMNS:
        if col in df.columns:
            df[col] = pd.to_numeric(df[col], errors="coerce")
    for col in TASK_DF_COLUMNS:
        if col not in df.columns:
            df[col] = None
    return df[TASK_DF_COLUMNS].reset_index(drop=True)


def _write_task_table(table_name: str, df: pd.DataFrame) -> None:
    """Atomically replace the contents of `table_name` with `df`.

    Whole-DataFrame replace inside one transaction. On Postgres, MVCC keeps
    concurrent readers on the pre-txn snapshot until COMMIT — no partial
    reads. Surrogate `id`s are not stable across saves (same as SQLite).
    """
    init_db()
    cols = _TASKS_SQL_COLS
    col_list = ", ".join(cols)
    placeholders = ", ".join(f":{c}" for c in cols)
    insert_sql = text(f"INSERT INTO {table_name} ({col_list}) VALUES ({placeholders})")
    with _ENGINE.begin() as conn:
        conn.execute(text(f"DELETE FROM {table_name}"))
        if df is not None and not df.empty:
            params = [_tasks_row_to_sql_params(row, cols) for _, row in df.iterrows()]
            conn.execute(insert_sql, params)


def load_tasks_df() -> pd.DataFrame:
    """Drop-in replacement for `pd.read_pickle(path_for_to_do_list)`."""
    return _read_task_table("tasks")


def save_tasks_df(df: pd.DataFrame) -> None:
    """Drop-in replacement for `df.to_pickle(path_for_to_do_list)`."""
    _write_task_table("tasks", df)


def load_recurring_df() -> pd.DataFrame:
    """Drop-in replacement for `pd.read_pickle(path_for_recurring_tasks)`."""
    return _read_task_table("recurring_tasks")


def save_recurring_df(df: pd.DataFrame) -> None:
    """Drop-in replacement for `df.to_pickle(path_for_recurring_tasks)`."""
    _write_task_table("recurring_tasks", df)


# --- Discipline list ---------------------------------------------------------

def load_discipline_df() -> pd.DataFrame:
    init_db()
    with _ENGINE.connect() as conn:
        df = pd.read_sql_query(text("SELECT * FROM discipline_list"), conn)
    if df.empty:
        return _empty_discipline_df()
    if "id" in df.columns:
        df = df.drop(columns=["id"])
    df = df.rename(columns=_DISCIPLINE_SQL_TO_DF)
    if "FREQUENCY_PER_WEEK" in df.columns:
        df["FREQUENCY_PER_WEEK"] = (
            pd.to_numeric(df["FREQUENCY_PER_WEEK"], errors="coerce")
            .fillna(1)
            .clip(lower=1, upper=7)
            .astype(int)
        )
    if "ACTIVE" in df.columns:
        df["ACTIVE"] = df["ACTIVE"].fillna(1).astype(int).astype(bool)
    if "CURRENT_STREAK" in df.columns:
        df["CURRENT_STREAK"] = pd.to_numeric(df["CURRENT_STREAK"], errors="coerce").fillna(0).astype(int)
    for col in DISCIPLINE_DF_COLUMNS:
        if col not in df.columns:
            df[col] = None
    return df[DISCIPLINE_DF_COLUMNS].reset_index(drop=True)


def save_discipline_df(df: pd.DataFrame) -> None:
    init_db()
    insert_sql = text(
        "INSERT INTO discipline_list "
        "(task, catagory, frequency_per_week, active, current_streak, uuid) "
        "VALUES (:task, :catagory, :frequency_per_week, :active, :current_streak, :uuid)"
    )
    with _ENGINE.begin() as conn:
        conn.execute(text("DELETE FROM discipline_list"))
        if df is not None and not df.empty:
            params = []
            for _, row in df.iterrows():
                params.append(
                    {
                        "task": None if pd.isna(row.get("TASK")) else str(row.get("TASK")),
                        "catagory": None if pd.isna(row.get("CATAGORY")) else str(row.get("CATAGORY")),
                        "frequency_per_week": _to_int_or_none(row.get("FREQUENCY_PER_WEEK")) or 1,
                        "active": _to_bool_int(
                            row.get("ACTIVE") if not pd.isna(row.get("ACTIVE")) else True
                        ),
                        "current_streak": _to_int_or_none(row.get("CURRENT_STREAK")) or 0,
                        "uuid": _uuid_or_new(row.get("UUID")),
                    }
                )
            conn.execute(insert_sql, params)


# --- Discipline completions & history matrix --------------------------------

def _catagory_for_task(conn, task_name: str) -> Optional[str]:
    row = conn.execute(
        text(
            "SELECT catagory FROM discipline_list "
            "WHERE lower(trim(task)) = lower(trim(:t)) LIMIT 1"
        ),
        {"t": task_name},
    ).first()
    if row is None:
        return None
    return row.catagory


# Dialect-specific upsert for discipline_completions. Both variants are no-ops
# on duplicate (task, completed_date), and both return rowcount=1 on insert,
# 0 on skip.
_APPEND_COMPLETION_SQL = text(
    "INSERT INTO discipline_completions (task, catagory, completed_date, logged_at) "
    "VALUES (:task, :catagory, :completed_date, :logged_at) "
    "ON CONFLICT (task, completed_date) DO NOTHING"
    if db_backend == "postgres"
    else
    "INSERT OR IGNORE INTO discipline_completions (task, catagory, completed_date, logged_at) "
    "VALUES (:task, :catagory, :completed_date, :logged_at)"
)


def append_discipline_completion(task_name: str, completed_date, catagory: Optional[str] = None) -> bool:
    """Insert a completion row. Returns True if a new row was inserted, False if duplicate."""
    init_db()
    completed_ts = pd.to_datetime(completed_date).normalize()
    date_str = completed_ts.date().isoformat()
    logged_at = pd.Timestamp.now().isoformat(sep=" ", timespec="seconds")
    with _ENGINE.begin() as conn:
        if catagory is None:
            catagory = _catagory_for_task(conn, task_name) or "Discipline"
        result = conn.execute(
            _APPEND_COMPLETION_SQL,
            {
                "task": str(task_name).strip(),
                "catagory": catagory,
                "completed_date": date_str,
                "logged_at": logged_at,
            },
        )
        return result.rowcount > 0


def delete_discipline_completion(task_name: str, completed_date) -> bool:
    """Remove a completion row. Returns True if a row was removed."""
    init_db()
    completed_ts = pd.to_datetime(completed_date).normalize()
    date_str = completed_ts.date().isoformat()
    with _ENGINE.begin() as conn:
        result = conn.execute(
            text(
                "DELETE FROM discipline_completions "
                "WHERE task = :task AND completed_date = :d"
            ),
            {"task": str(task_name).strip(), "d": date_str},
        )
        return result.rowcount > 0


def set_discipline_cell(task_name: str, date, value) -> pd.DataFrame:
    """Mark/unmark task on date. Returns the refreshed wide history matrix."""
    if bool(value):
        append_discipline_completion(task_name, date)
    else:
        delete_discipline_completion(task_name, date)
    return read_discipline_history()


def is_task_completed_on(task_name: str, date, history_df: Optional[pd.DataFrame] = None) -> bool:
    """True iff a completion row exists for (task, date). `history_df` kept for
    backward compatibility with the old matrix-based signature."""
    if history_df is not None:
        task_name_stripped = str(task_name).strip()
        date_normalized = pd.to_datetime(date).normalize()
        if task_name_stripped not in history_df.columns or date_normalized not in history_df.index:
            return False
        val = history_df.at[date_normalized, task_name_stripped]
        try:
            if pd.isna(val):
                return False
        except (TypeError, ValueError):
            pass
        return bool(val)

    init_db()
    date_str = pd.to_datetime(date).normalize().date().isoformat()
    with _ENGINE.connect() as conn:
        row = conn.execute(
            text(
                "SELECT 1 FROM discipline_completions "
                "WHERE lower(trim(task)) = lower(trim(:t)) AND completed_date = :d LIMIT 1"
            ),
            {"t": task_name, "d": date_str},
        ).first()
    return row is not None


def load_discipline_completion_df() -> pd.DataFrame:
    """Return the long-format completion DataFrame the bot uses for weekly/streak math."""
    init_db()
    with _ENGINE.connect() as conn:
        df = pd.read_sql_query(
            text(
                "SELECT task, catagory, completed_date, logged_at "
                "FROM discipline_completions ORDER BY completed_date ASC"
            ),
            conn,
        )
    if df.empty:
        return _empty_completion_df()
    df = df.rename(columns=_COMPLETIONS_SQL_TO_DF)
    df["COMPLETED_DATE"] = pd.to_datetime(df["COMPLETED_DATE"], errors="coerce").dt.normalize()
    df["LOGGED_AT"] = pd.to_datetime(df["LOGGED_AT"], errors="coerce")
    df["TASK"] = df["TASK"].astype(str).str.strip()
    if "CATAGORY" not in df.columns:
        df["CATAGORY"] = "Discipline"
    else:
        df["CATAGORY"] = df["CATAGORY"].fillna("Discipline")
    return df[COMPLETION_DF_COLUMNS].reset_index(drop=True)


def _empty_history_df() -> pd.DataFrame:
    return pd.DataFrame(index=pd.DatetimeIndex([], name="DATE"))


def read_discipline_history() -> pd.DataFrame:
    """Rebuild the wide history matrix (DatetimeIndex x task columns) from
    the long completions table. True where a completion row exists, pd.NA
    before that task's first-ever completion, False otherwise.
    """
    long_df = load_discipline_completion_df()
    if long_df.empty:
        return _empty_history_df()

    long_df = long_df.dropna(subset=["COMPLETED_DATE", "TASK"])
    if long_df.empty:
        return _empty_history_df()

    min_date = long_df["COMPLETED_DATE"].min()
    max_date = long_df["COMPLETED_DATE"].max()
    today = pd.Timestamp(pd.Timestamp.now().date())
    if today > max_date:
        max_date = today

    all_dates = pd.date_range(min_date, max_date, freq="D", name="DATE")
    tasks_sorted = sorted(long_df["TASK"].unique())

    history_df = pd.DataFrame(False, index=all_dates, columns=tasks_sorted, dtype="object")

    first_seen = long_df.groupby("TASK")["COMPLETED_DATE"].min()
    for task, first_date in first_seen.items():
        history_df.loc[history_df.index < first_date, task] = pd.NA

    for _, row in long_df.iterrows():
        history_df.at[row["COMPLETED_DATE"], row["TASK"]] = True

    return history_df


# --- Follow-up task mappings -------------------------------------------------

def load_follow_ups() -> pd.DataFrame:
    init_db()
    with _ENGINE.connect() as conn:
        df = pd.read_sql_query(
            text("SELECT * FROM follow_up_tasks ORDER BY id ASC"), conn
        )
    if df.empty:
        return _empty_follow_up_df()
    if "id" in df.columns:
        df = df.drop(columns=["id"])
    df = df.rename(columns=_FOLLOW_UP_SQL_TO_DF)
    if "PRIORITY" in df.columns:
        df["PRIORITY"] = pd.to_numeric(df["PRIORITY"], errors="coerce").fillna(1).astype(int)
    if "DUE_OFFSET_DAYS" in df.columns:
        df["DUE_OFFSET_DAYS"] = pd.to_numeric(df["DUE_OFFSET_DAYS"], errors="coerce")
    if "ESTIMATED_TIME" in df.columns:
        df["ESTIMATED_TIME"] = pd.to_numeric(df["ESTIMATED_TIME"], errors="coerce")
    if "CREATED" in df.columns:
        df["CREATED"] = pd.to_datetime(df["CREATED"], errors="coerce")
    for col in FOLLOW_UP_DF_COLUMNS:
        if col not in df.columns:
            df[col] = None
    return df[FOLLOW_UP_DF_COLUMNS].reset_index(drop=True)


def save_follow_ups(df: pd.DataFrame) -> None:
    init_db()
    insert_sql = text(
        "INSERT INTO follow_up_tasks "
        "(trigger_task, follow_up_task, catagory, task_group, subgroup, "
        " relevant_link, priority, estimated_time, due_offset_days, created, uuid) "
        "VALUES (:trigger_task, :follow_up_task, :catagory, :task_group, :subgroup, "
        " :relevant_link, :priority, :estimated_time, :due_offset_days, :created, :uuid)"
    )
    with _ENGINE.begin() as conn:
        conn.execute(text("DELETE FROM follow_up_tasks"))
        if df is not None and not df.empty:
            params = []
            for _, row in df.iterrows():
                params.append(
                    {
                        "trigger_task": None if pd.isna(row.get("TRIGGER_TASK")) else str(row.get("TRIGGER_TASK")),
                        "follow_up_task": None if pd.isna(row.get("FOLLOW_UP_TASK")) else str(row.get("FOLLOW_UP_TASK")),
                        "catagory": None if pd.isna(row.get("CATAGORY")) else str(row.get("CATAGORY")),
                        "task_group": None if pd.isna(row.get("GROUP")) else str(row.get("GROUP")),
                        "subgroup": None if pd.isna(row.get("SUBGROUP")) else str(row.get("SUBGROUP")),
                        "relevant_link": None if pd.isna(row.get("RELEVANT_LINK")) else str(row.get("RELEVANT_LINK")),
                        "priority": _to_int_or_none(row.get("PRIORITY")) or 1,
                        "estimated_time": _to_float_or_none(row.get("ESTIMATED_TIME")),
                        "due_offset_days": _to_int_or_none(row.get("DUE_OFFSET_DAYS")),
                        "created": _iso_or_none(
                            pd.to_datetime(row.get("CREATED"), errors="coerce")
                            if row.get("CREATED") is not None
                            else None
                        ),
                        "uuid": _uuid_or_new(row.get("UUID")),
                    }
                )
            conn.execute(insert_sql, params)


# --- Introspection helpers (used by migration script + tests) ---------------

def table_row_count(table_name: str) -> int:
    init_db()
    with _ENGINE.connect() as conn:
        row = conn.execute(text(f"SELECT COUNT(*) AS n FROM {table_name}")).first()
    return int(row.n or 0)
