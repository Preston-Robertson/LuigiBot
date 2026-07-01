"""SQLite persistence layer for LuigiBot.

Single source of truth for all bot data. Every other module reads/writes
via the helpers here; nothing else should touch sqlite3 or the .pkl files.

Design notes
------------
- WAL mode + busy_timeout so future readers (web UI) don't collide with the bot.
- Whole-DataFrame load/save helpers mirror the old `pd.read_pickle` /
  `pd.to_pickle` call sites so the bot refactor is a near-mechanical rename.
- Column names on the DataFrame side are preserved *exactly* as the bot
  already uses them (including the `CATAGORY` spelling and the `GROUP` /
  `SUB-GROUP` / `RELEVANT LINK` spacing). SQL columns are snake_case
  because `GROUP` is a reserved word.
- Dates/timestamps are stored as ISO-8601 TEXT and parsed back on read.
- `discipline_history` is *not* a table — it's rebuilt from the long
  `discipline_completions` table on demand, so downstream matrix code keeps
  working unchanged.
"""
from __future__ import annotations

import os
import sqlite3
import threading
from contextlib import contextmanager
from typing import Iterable, Optional

import pandas as pd

from .bot_config import database_path


SCHEMA_VERSION = 1

_INIT_LOCK = threading.Lock()
_INITIALIZED = False


# --- Connection management ---------------------------------------------------

@contextmanager
def get_connection():
    """Yield a sqlite3 connection with WAL + row_factory set up. Auto-commits.

    We open a fresh connection per call (cheap for SQLite) so this is safe to
    use from discord.py's asyncio callbacks — no cross-thread cursor sharing.
    """
    conn = sqlite3.connect(database_path, timeout=30, isolation_level=None)
    conn.row_factory = sqlite3.Row
    # PRAGMAs are cheap and idempotent per connection.
    conn.execute("PRAGMA journal_mode=WAL")
    conn.execute("PRAGMA synchronous=NORMAL")
    conn.execute("PRAGMA foreign_keys=ON")
    conn.execute("PRAGMA busy_timeout=30000")
    try:
        yield conn
    finally:
        conn.close()


# --- Schema ------------------------------------------------------------------

_TASKS_SQL = """
CREATE TABLE IF NOT EXISTS tasks (
    id                 INTEGER PRIMARY KEY AUTOINCREMENT,
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
    recurring_interval INTEGER
);
CREATE INDEX IF NOT EXISTS idx_tasks_status ON tasks(status);
CREATE INDEX IF NOT EXISTS idx_tasks_due    ON tasks(due_date);
"""

_RECURRING_SQL = """
CREATE TABLE IF NOT EXISTS recurring_tasks (
    id                 INTEGER PRIMARY KEY AUTOINCREMENT,
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
    recurring_interval INTEGER
);
"""

_DISCIPLINE_LIST_SQL = """
CREATE TABLE IF NOT EXISTS discipline_list (
    id                 INTEGER PRIMARY KEY AUTOINCREMENT,
    task               TEXT    NOT NULL,
    catagory           TEXT,
    frequency_per_week INTEGER DEFAULT 1,
    active             INTEGER DEFAULT 1,
    current_streak     INTEGER DEFAULT 0
);
"""

_DISCIPLINE_COMPLETIONS_SQL = """
CREATE TABLE IF NOT EXISTS discipline_completions (
    id             INTEGER PRIMARY KEY AUTOINCREMENT,
    task           TEXT NOT NULL,
    catagory       TEXT,
    completed_date TEXT NOT NULL,
    logged_at      TEXT,
    UNIQUE(task, completed_date)
);
CREATE INDEX IF NOT EXISTS idx_disc_comp_date ON discipline_completions(completed_date);
CREATE INDEX IF NOT EXISTS idx_disc_comp_task ON discipline_completions(task);
"""

_FOLLOW_UPS_SQL = """
CREATE TABLE IF NOT EXISTS follow_up_tasks (
    id              INTEGER PRIMARY KEY AUTOINCREMENT,
    trigger_task    TEXT NOT NULL,
    follow_up_task  TEXT NOT NULL,
    catagory        TEXT,
    task_group      TEXT,
    subgroup        TEXT,
    relevant_link   TEXT,
    priority        INTEGER DEFAULT 1,
    estimated_time  REAL,
    due_offset_days INTEGER,
    created         TEXT
);
"""

_SCHEMA_VERSION_SQL = """
CREATE TABLE IF NOT EXISTS schema_version (version INTEGER NOT NULL);
"""


def init_db() -> None:
    """Create the DB file (and parent dirs) and all tables if missing. Idempotent."""
    global _INITIALIZED
    if _INITIALIZED:
        return
    with _INIT_LOCK:
        if _INITIALIZED:
            return
        os.makedirs(os.path.dirname(os.path.abspath(database_path)) or ".", exist_ok=True)
        with get_connection() as conn:
            for stmt in (
                _TASKS_SQL,
                _RECURRING_SQL,
                _DISCIPLINE_LIST_SQL,
                _DISCIPLINE_COMPLETIONS_SQL,
                _FOLLOW_UPS_SQL,
                _SCHEMA_VERSION_SQL,
            ):
                conn.executescript(stmt)
            existing = conn.execute("SELECT version FROM schema_version LIMIT 1").fetchone()
            if existing is None:
                conn.execute("INSERT INTO schema_version (version) VALUES (?)", (SCHEMA_VERSION,))
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
]

DISCIPLINE_DF_COLUMNS = ["TASK", "CATAGORY", "FREQUENCY_PER_WEEK", "ACTIVE", "CURRENT_STREAK"]
COMPLETION_DF_COLUMNS = ["TASK", "CATAGORY", "COMPLETED_DATE", "LOGGED_AT"]


# --- Serialization helpers ---------------------------------------------------

def _iso_or_none(value):
    """Serialize a scalar to ISO string / int / float / None for SQLite."""
    if value is None:
        return None
    # pandas NA / NaT / NaN
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


def _tasks_row_to_sql_params(row: pd.Series, sql_columns: Iterable[str]) -> tuple:
    """Convert a task-shaped Series -> tuple of SQL-safe values in `sql_columns` order."""
    out = []
    for sql_col in sql_columns:
        df_col = _TASKS_SQL_TO_DF[sql_col]
        value = row.get(df_col)
        if df_col in _TASKS_BOOL_COLUMNS:
            out.append(_to_bool_int(value))
        elif df_col in _TASKS_INT_COLUMNS:
            out.append(_to_int_or_none(value))
        elif df_col in _TASKS_FLOAT_COLUMNS:
            out.append(_to_float_or_none(value))
        elif df_col in _TASKS_DATE_COLUMNS:
            out.append(_iso_or_none(pd.to_datetime(value, errors="coerce") if value is not None else None))
        else:
            v = _iso_or_none(value)
            out.append(None if v is None else str(v))
    return tuple(out)


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
    with get_connection() as conn:
        df = pd.read_sql_query(f"SELECT * FROM {table_name}", conn)
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
    # Return columns in the canonical DataFrame order the bot expects.
    for col in TASK_DF_COLUMNS:
        if col not in df.columns:
            df[col] = None
    return df[TASK_DF_COLUMNS].reset_index(drop=True)


def _write_task_table(table_name: str, df: pd.DataFrame) -> None:
    """Atomically replace the contents of `table_name` with `df`.

    We take the whole-DataFrame approach (delete + bulk insert in one txn) so
    all the existing read-modify-write pickle call sites keep working with a
    trivial rename. Fine for these small tables.
    """
    init_db()
    with get_connection() as conn:
        conn.execute("BEGIN")
        try:
            conn.execute(f"DELETE FROM {table_name}")
            if df is not None and not df.empty:
                cols = _TASKS_SQL_COLS
                placeholders = ",".join(["?"] * len(cols))
                col_list = ",".join(cols)
                params = [_tasks_row_to_sql_params(row, cols) for _, row in df.iterrows()]
                conn.executemany(
                    f"INSERT INTO {table_name} ({col_list}) VALUES ({placeholders})",
                    params,
                )
            conn.execute("COMMIT")
        except Exception:
            conn.execute("ROLLBACK")
            raise


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
    with get_connection() as conn:
        df = pd.read_sql_query("SELECT * FROM discipline_list", conn)
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
    with get_connection() as conn:
        conn.execute("BEGIN")
        try:
            conn.execute("DELETE FROM discipline_list")
            if df is not None and not df.empty:
                params = []
                for _, row in df.iterrows():
                    params.append(
                        (
                            None if pd.isna(row.get("TASK")) else str(row.get("TASK")),
                            None if pd.isna(row.get("CATAGORY")) else str(row.get("CATAGORY")),
                            _to_int_or_none(row.get("FREQUENCY_PER_WEEK")) or 1,
                            _to_bool_int(row.get("ACTIVE") if not pd.isna(row.get("ACTIVE")) else True),
                            _to_int_or_none(row.get("CURRENT_STREAK")) or 0,
                        )
                    )
                conn.executemany(
                    "INSERT INTO discipline_list (task, catagory, frequency_per_week, active, current_streak) "
                    "VALUES (?, ?, ?, ?, ?)",
                    params,
                )
            conn.execute("COMMIT")
        except Exception:
            conn.execute("ROLLBACK")
            raise


# --- Discipline completions & history matrix --------------------------------

def _catagory_for_task(conn, task_name: str) -> Optional[str]:
    row = conn.execute(
        "SELECT catagory FROM discipline_list WHERE lower(trim(task)) = lower(trim(?)) LIMIT 1",
        (task_name,),
    ).fetchone()
    if row is None:
        return None
    return row["catagory"]


def append_discipline_completion(task_name: str, completed_date, catagory: Optional[str] = None) -> bool:
    """Insert a completion row. Returns True if a new row was inserted, False if duplicate."""
    init_db()
    completed_ts = pd.to_datetime(completed_date).normalize()
    date_str = completed_ts.date().isoformat()
    logged_at = pd.Timestamp.now().isoformat(sep=" ", timespec="seconds")
    with get_connection() as conn:
        if catagory is None:
            catagory = _catagory_for_task(conn, task_name) or "Discipline"
        cur = conn.execute(
            "INSERT OR IGNORE INTO discipline_completions (task, catagory, completed_date, logged_at) "
            "VALUES (?, ?, ?, ?)",
            (str(task_name).strip(), catagory, date_str, logged_at),
        )
        return cur.rowcount > 0


def delete_discipline_completion(task_name: str, completed_date) -> bool:
    """Remove a completion row. Returns True if a row was removed."""
    init_db()
    completed_ts = pd.to_datetime(completed_date).normalize()
    date_str = completed_ts.date().isoformat()
    with get_connection() as conn:
        cur = conn.execute(
            "DELETE FROM discipline_completions WHERE task = ? AND completed_date = ?",
            (str(task_name).strip(), date_str),
        )
        return cur.rowcount > 0


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
    with get_connection() as conn:
        row = conn.execute(
            "SELECT 1 FROM discipline_completions "
            "WHERE lower(trim(task)) = lower(trim(?)) AND completed_date = ? LIMIT 1",
            (task_name, date_str),
        ).fetchone()
    return row is not None


def load_discipline_completion_df() -> pd.DataFrame:
    """Return the long-format completion DataFrame the bot uses for weekly/streak math."""
    init_db()
    with get_connection() as conn:
        df = pd.read_sql_query(
            "SELECT task, catagory, completed_date, logged_at FROM discipline_completions "
            "ORDER BY completed_date ASC",
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

    Downstream discipline code (streaks, heatmap, category rollups) reads this
    matrix — we preserve the same shape it had when it was a pickle.
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

    # object dtype so we can hold True / False / pd.NA together
    history_df = pd.DataFrame(False, index=all_dates, columns=tasks_sorted, dtype="object")

    # Mark cells before a task's first completion as NA (task wasn't tracked yet).
    first_seen = long_df.groupby("TASK")["COMPLETED_DATE"].min()
    for task, first_date in first_seen.items():
        history_df.loc[history_df.index < first_date, task] = pd.NA

    for _, row in long_df.iterrows():
        history_df.at[row["COMPLETED_DATE"], row["TASK"]] = True

    return history_df


# --- Follow-up task mappings -------------------------------------------------

def load_follow_ups() -> pd.DataFrame:
    init_db()
    with get_connection() as conn:
        df = pd.read_sql_query("SELECT * FROM follow_up_tasks ORDER BY id ASC", conn)
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
    with get_connection() as conn:
        conn.execute("BEGIN")
        try:
            conn.execute("DELETE FROM follow_up_tasks")
            if df is not None and not df.empty:
                params = []
                for _, row in df.iterrows():
                    params.append(
                        (
                            None if pd.isna(row.get("TRIGGER_TASK")) else str(row.get("TRIGGER_TASK")),
                            None if pd.isna(row.get("FOLLOW_UP_TASK")) else str(row.get("FOLLOW_UP_TASK")),
                            None if pd.isna(row.get("CATAGORY")) else (str(row.get("CATAGORY")) if row.get("CATAGORY") is not None else None),
                            None if pd.isna(row.get("GROUP")) else (str(row.get("GROUP")) if row.get("GROUP") is not None else None),
                            None if pd.isna(row.get("SUBGROUP")) else (str(row.get("SUBGROUP")) if row.get("SUBGROUP") is not None else None),
                            None if pd.isna(row.get("RELEVANT_LINK")) else (str(row.get("RELEVANT_LINK")) if row.get("RELEVANT_LINK") is not None else None),
                            _to_int_or_none(row.get("PRIORITY")) or 1,
                            _to_float_or_none(row.get("ESTIMATED_TIME")),
                            _to_int_or_none(row.get("DUE_OFFSET_DAYS")),
                            _iso_or_none(pd.to_datetime(row.get("CREATED"), errors="coerce") if row.get("CREATED") is not None else None),
                        )
                    )
                conn.executemany(
                    "INSERT INTO follow_up_tasks "
                    "(trigger_task, follow_up_task, catagory, task_group, subgroup, "
                    " relevant_link, priority, estimated_time, due_offset_days, created) "
                    "VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
                    params,
                )
            conn.execute("COMMIT")
        except Exception:
            conn.execute("ROLLBACK")
            raise


# --- Introspection helpers (used by migration script + tests) ---------------

def table_row_count(table_name: str) -> int:
    init_db()
    with get_connection() as conn:
        row = conn.execute(f"SELECT COUNT(*) AS n FROM {table_name}").fetchone()
    return int(row["n"] or 0)
