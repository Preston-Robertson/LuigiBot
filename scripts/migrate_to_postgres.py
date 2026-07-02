#!/usr/bin/env python3
"""One-shot migration of LuigiBot to-do data into Postgres (luigi_todo).

Reads from EITHER the SQLite store or the legacy pickle store, writes to the
Postgres backend configured via LUIGI_PG_* env vars (see bot_modules/bot_config.py).

Safety:
  * Never deletes the source.
  * --dry-run reads + reports, writes nothing.
  * id columns are GENERATED ALWAYS AS IDENTITY -> we never send id.
  * discipline_completions insert uses ON CONFLICT (task, completed_date) DO NOTHING.

Usage:
  python scripts/migrate_to_postgres.py --source sqlite  --dry-run
  python scripts/migrate_to_postgres.py --source sqlite
  python scripts/migrate_to_postgres.py --source pickle  --dry-run
  python scripts/migrate_to_postgres.py --source pickle
"""
from __future__ import annotations

import argparse
import os
import sys

# Repo root must be on sys.path so `import bot_modules` works when this script
# is invoked from anywhere (Python only auto-adds the script's own directory).
_REPO_ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))
if _REPO_ROOT not in sys.path:
    sys.path.insert(0, _REPO_ROOT)

import pandas as pd
from sqlalchemy import URL, create_engine, text

EXPECTED = {
    "tasks": 18,
    "recurring_tasks": 4,
    "discipline_list": 6,
    "discipline_completions": 41,
    "follow_up_tasks": 0,
}

# SQL column order per table (snake_case), mirroring bot_modules/db.py.
TASK_SQL_COLS = [
    "task", "priority", "status", "due_date", "relevant_link", "catagory",
    "task_group", "sub_group", "task_creation", "start_time", "estimated_time",
    "logged_hours", "completed", "completed_time", "recurring", "recurring_interval",
]
DISCIPLINE_SQL_COLS = ["task", "catagory", "frequency_per_week", "active", "current_streak"]
COMPLETION_SQL_COLS = ["task", "catagory", "completed_date", "logged_at"]
FOLLOW_UP_SQL_COLS = [
    "trigger_task", "follow_up_task", "catagory", "task_group", "subgroup",
    "relevant_link", "priority", "estimated_time", "due_offset_days", "created",
]


def pg_engine():
    url = URL.create(
        "postgresql+psycopg",
        username=os.environ["LUIGI_PG_USER"],
        password=os.environ.get("LUIGI_PG_PASSWORD") or None,
        host=os.environ["LUIGI_PG_HOST"],
        port=int(os.environ.get("LUIGI_PG_PORT", "5432")),
        database=os.environ["LUIGI_PG_DB"],
    )
    return create_engine(url, future=True, pool_pre_ping=True)


# ---- Source readers ---------------------------------------------------------

def read_from_sqlite():
    """Use the bot's own db.py (SQLite backend) so column mapping is authoritative."""
    os.environ["LUIGI_DB_BACKEND"] = "sqlite"
    # Import AFTER forcing sqlite so bot_config picks it up.
    from bot_modules import db  # noqa: E402
    tasks = db.load_tasks_df()
    recurring = db.load_recurring_df()
    discipline = db.load_discipline_df()
    completions = db.load_discipline_completion_df()
    follow_ups = db.load_follow_ups()
    return tasks, recurring, discipline, completions, follow_ups


def read_from_pickle():
    """Load the legacy .pkl DataFrames directly (already in the bot's DF shape)."""
    from bot_modules import bot_config as cfg  # noqa: E402

    def _load(path):
        try:
            return pd.read_pickle(path)
        except FileNotFoundError:
            return pd.DataFrame()

    tasks = _load(cfg.path_for_to_do_list)
    recurring = _load(cfg.path_for_recurring_tasks)
    discipline = _load(cfg.path_for_discipline_list)
    completions = _load(cfg.path_for_discipline_completion_log)
    follow_ups = _load(cfg.path_for_follow_up_tasks)
    return tasks, recurring, discipline, completions, follow_ups


# ---- DF -> SQL param mapping (reuse db.py helpers where possible) ------------

def tasks_params(df):
    from bot_modules import db
    if df is None or df.empty:
        return []
    return [db._tasks_row_to_sql_params(row, TASK_SQL_COLS) for _, row in df.iterrows()]


def discipline_params(df):
    from bot_modules import db
    out = []
    if df is None or df.empty:
        return out
    for _, row in df.iterrows():
        out.append({
            "task": None if pd.isna(row.get("TASK")) else str(row.get("TASK")),
            "catagory": None if pd.isna(row.get("CATAGORY")) else str(row.get("CATAGORY")),
            "frequency_per_week": db._to_int_or_none(row.get("FREQUENCY_PER_WEEK")) or 1,
            "active": db._to_bool_int(row.get("ACTIVE") if not pd.isna(row.get("ACTIVE")) else True),
            "current_streak": db._to_int_or_none(row.get("CURRENT_STREAK")) or 0,
        })
    return out


def completion_params(df):
    out = []
    if df is None or df.empty:
        return out
    for _, row in df.iterrows():
        cd = row.get("COMPLETED_DATE")
        if pd.isna(cd):
            continue
        cd = pd.to_datetime(cd).date().isoformat()
        la = row.get("LOGGED_AT")
        la = None if pd.isna(la) else pd.to_datetime(la).isoformat(sep=" ")
        cat = row.get("CATAGORY")
        cat = "Discipline" if pd.isna(cat) else str(cat)
        out.append({
            "task": str(row.get("TASK")).strip(),
            "catagory": cat,
            "completed_date": cd,
            "logged_at": la,
        })
    return out


def follow_up_params(df):
    from bot_modules import db
    out = []
    if df is None or df.empty:
        return out
    for _, row in df.iterrows():
        out.append({
            "trigger_task": None if pd.isna(row.get("TRIGGER_TASK")) else str(row.get("TRIGGER_TASK")),
            "follow_up_task": None if pd.isna(row.get("FOLLOW_UP_TASK")) else str(row.get("FOLLOW_UP_TASK")),
            "catagory": None if pd.isna(row.get("CATAGORY")) else str(row.get("CATAGORY")),
            "task_group": None if pd.isna(row.get("GROUP")) else str(row.get("GROUP")),
            "subgroup": None if pd.isna(row.get("SUBGROUP")) else str(row.get("SUBGROUP")),
            "relevant_link": None if pd.isna(row.get("RELEVANT_LINK")) else str(row.get("RELEVANT_LINK")),
            "priority": db._to_int_or_none(row.get("PRIORITY")) or 1,
            "estimated_time": db._to_float_or_none(row.get("ESTIMATED_TIME")),
            "due_offset_days": db._to_int_or_none(row.get("DUE_OFFSET_DAYS")),
            "created": db._iso_or_none(pd.to_datetime(row.get("CREATED"), errors="coerce")
                                       if row.get("CREATED") is not None else None),
        })
    return out


# ---- Writers ----------------------------------------------------------------

def bulk_insert(conn, table, cols, params):
    if not params:
        return 0
    col_list = ", ".join(cols)
    ph = ", ".join(f":{c}" for c in cols)
    conn.execute(text(f"INSERT INTO {table} ({col_list}) VALUES ({ph})"), params)
    return len(params)


def insert_completions(conn, params):
    if not params:
        return 0
    sql = text(
        "INSERT INTO discipline_completions (task, catagory, completed_date, logged_at) "
        "VALUES (:task, :catagory, :completed_date, :logged_at) "
        "ON CONFLICT (task, completed_date) DO NOTHING"
    )
    inserted = 0
    for p in params:
        r = conn.execute(sql, p)
        inserted += r.rowcount if r.rowcount and r.rowcount > 0 else 0
    return inserted


def count(conn, table):
    return int(conn.execute(text(f"SELECT COUNT(*) FROM {table}")).scalar() or 0)


# ---- Main -------------------------------------------------------------------

def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--source", choices=["sqlite", "pickle"], required=True)
    ap.add_argument("--dry-run", action="store_true")
    ap.add_argument("--truncate-first", action="store_true",
                    help="TRUNCATE the 5 data tables before load (for re-runs).")
    args = ap.parse_args()

    reader = read_from_sqlite if args.source == "sqlite" else read_from_pickle
    tasks, recurring, discipline, completions, follow_ups = reader()

    src_counts = {
        "tasks": 0 if tasks is None else len(tasks),
        "recurring_tasks": 0 if recurring is None else len(recurring),
        "discipline_list": 0 if discipline is None else len(discipline),
        "discipline_completions": 0 if completions is None else len(completions),
        "follow_up_tasks": 0 if follow_ups is None else len(follow_ups),
    }
    print(f"SOURCE ({args.source}) row counts: {src_counts}")
    print(f"EXPECTED               row counts: {EXPECTED}")

    if args.dry_run:
        mismatches = {k: (src_counts[k], EXPECTED[k]) for k in EXPECTED if src_counts[k] != EXPECTED[k]}
        if mismatches:
            print("DRY-RUN: source vs expected MISMATCH:", mismatches)
        else:
            print("DRY-RUN: source counts match expected. No data written.")
        return 0

    eng = pg_engine()
    with eng.begin() as conn:
        if args.truncate_first:
            conn.execute(text(
                "TRUNCATE tasks, recurring_tasks, discipline_list, "
                "discipline_completions, follow_up_tasks RESTART IDENTITY"
            ))
        bulk_insert(conn, "tasks", TASK_SQL_COLS, tasks_params(tasks))
        bulk_insert(conn, "recurring_tasks", TASK_SQL_COLS, tasks_params(recurring))
        bulk_insert(conn, "discipline_list", DISCIPLINE_SQL_COLS, discipline_params(discipline))
        insert_completions(conn, completion_params(completions))
        bulk_insert(conn, "follow_up_tasks", FOLLOW_UP_SQL_COLS, follow_up_params(follow_ups))

    # Validate
    with eng.connect() as conn:
        final = {t: count(conn, t) for t in EXPECTED}
    print(f"POSTGRES final row counts: {final}")

    ok = all(final[t] == EXPECTED[t] for t in EXPECTED)
    if not ok:
        print("FAIL: post-migration counts do not match expected.")
        print("      (Re-run with --truncate-first after fixing the source selection.)")
        return 1
    print("SUCCESS: all row counts match expected.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
