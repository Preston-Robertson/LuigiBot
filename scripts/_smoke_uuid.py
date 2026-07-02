#!/usr/bin/env python3
"""Smoke tests for schema v2 (stable `uuid` on the four list tables).

Runs entirely against a throwaway SQLite DB in a temp dir so it can't touch
the production Postgres. Covers the four spec requirements:

  1. Fresh v2 DB: tables get uuid + unique index, schema_version=2.
  2. init_db() is idempotent (running twice leaves version=2, no error).
  3. Round-trip: load_* -> save_* -> load_* preserves each row's uuid for
     all four list tables (the key regression: uuids survive the whole-
     table rewrite).
  4. v1 -> v2 migration: simulate a v1 DB (no uuid columns, version=1),
     run init_db(), assert columns/indexes added, all rows backfilled, no
     null uuids, version=2, row counts unchanged.

Usage (from repo root):
  python scripts/_smoke_uuid.py
"""
from __future__ import annotations

import importlib
import os
import sys
import tempfile

# Repo root on sys.path so `bot_modules` imports work from anywhere.
_REPO_ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))
if _REPO_ROOT not in sys.path:
    sys.path.insert(0, _REPO_ROOT)

import pandas as pd  # noqa: E402
from sqlalchemy import text  # noqa: E402


def _fresh_db_env(tmp_dir: str) -> None:
    """Point the bot at a brand-new SQLite file and force a re-import of db.py."""
    db_path = os.path.join(tmp_dir, "luigi_smoke.db")
    if os.path.exists(db_path):
        os.remove(db_path)
    os.environ["LUIGI_DB_BACKEND"] = "sqlite"
    os.environ["LUIGI_DB_PATH"] = db_path
    # Purge cached modules so bot_config re-reads env.
    for mod in ("bot_modules.db", "bot_modules.bot_config", "bot_modules"):
        sys.modules.pop(mod, None)


def _fresh_import():
    """Return a freshly-imported bot_modules.db bound to the current env."""
    import bot_modules.db as db  # noqa: WPS433
    importlib.reload(db)
    return db


def _dispose(db) -> None:
    """Release the SQLite engine's file handle so Windows can rm the temp dir."""
    try:
        db._ENGINE.dispose()
    except Exception:
        pass


def _sample_task_row(name: str) -> dict:
    return {
        "TASK": name,
        "TASK CREATION": pd.Timestamp("2026-01-01 09:00:00"),
        "CATAGORY": "Test",
        "GROUP": "G1",
        "SUB-GROUP": "SG1",
        "RELEVANT LINK": None,
        "RECURRING": False,
        "RECURRING INTERVAL": None,
        "DUE DATE": pd.Timestamp("2026-02-01"),
        "PRIORITY": 3,
        "STATUS": "Not Started",
        "START TIME": None,
        "ESTIMATED TIME": 1.5,
        "LOGGED HOURS": 0.0,
        "COMPLETED": False,
        "COMPLETED TIME": None,
        # UUID intentionally omitted: save path must mint one.
    }


def _sample_discipline_row(name: str) -> dict:
    return {
        "TASK": name,
        "CATAGORY": "Discipline",
        "FREQUENCY_PER_WEEK": 3,
        "ACTIVE": True,
        "CURRENT_STREAK": 0,
    }


def _sample_follow_up_row(trigger: str, follow_up: str) -> dict:
    return {
        "TRIGGER_TASK": trigger,
        "FOLLOW_UP_TASK": follow_up,
        "CATAGORY": "Test",
        "GROUP": "G1",
        "SUBGROUP": "SG1",
        "RELEVANT_LINK": None,
        "PRIORITY": 2,
        "ESTIMATED_TIME": 0.5,
        "DUE_OFFSET_DAYS": 1,
        "CREATED": pd.Timestamp("2026-01-01 10:00:00"),
    }


def check(cond: bool, msg: str) -> None:
    if not cond:
        raise AssertionError(f"[FAIL] {msg}")
    print(f"  [ok] {msg}")


# --- Test 1 + 2: fresh v2 DB + idempotent init -------------------------------

def test_fresh_and_idempotent() -> None:
    print("\n== Test 1+2: fresh v2 DB + idempotent init ==")
    with tempfile.TemporaryDirectory(ignore_cleanup_errors=True) as tmp:
        _fresh_db_env(tmp)
        db = _fresh_import()

        db.init_db()
        with db._ENGINE.connect() as conn:
            version = conn.execute(text("SELECT version FROM schema_version")).scalar()
            check(version == 2, f"schema_version == 2 after fresh init (got {version})")
            for table in db._UUID_TABLES:
                cols = [r.name for r in conn.execute(text(f"PRAGMA table_info({table})")).all()]
                check("uuid" in cols, f"{table} has uuid column")
                idx = conn.execute(
                    text(
                        "SELECT name FROM sqlite_master "
                        "WHERE type='index' AND name=:i"
                    ),
                    {"i": f"idx_{table}_uuid"},
                ).scalar()
                check(idx == f"idx_{table}_uuid", f"{table} has unique index idx_{table}_uuid")

        # Second call must be a no-op (no error, still v2).
        db._INITIALIZED = False  # force the guard to re-enter
        db.init_db()
        with db._ENGINE.connect() as conn:
            version = conn.execute(text("SELECT version FROM schema_version")).scalar()
            check(version == 2, f"schema_version still 2 after second init (got {version})")
        _dispose(db)


# --- Test 3: round-trip preserves uuid across whole-table rewrite ------------

def test_round_trip_preserves_uuid() -> None:
    print("\n== Test 3: round-trip preserves uuid (the key regression) ==")
    with tempfile.TemporaryDirectory(ignore_cleanup_errors=True) as tmp:
        _fresh_db_env(tmp)
        db = _fresh_import()

        # Tasks: bot builds rows WITHOUT uuid. Save mints one. Reload -> re-save
        # -> reload must yield the same uuid on the same logical row.
        df1 = pd.DataFrame([_sample_task_row("alpha"), _sample_task_row("beta")])
        db.save_tasks_df(df1)
        loaded_a = db.load_tasks_df().sort_values("TASK").reset_index(drop=True)
        check("UUID" in loaded_a.columns, "load_tasks_df returns UUID column")
        check(loaded_a["UUID"].notna().all(), "no null uuids after save/load")

        # Second write cycle: send the loaded DF back in (uuids present).
        db.save_tasks_df(loaded_a)
        loaded_b = db.load_tasks_df().sort_values("TASK").reset_index(drop=True)
        check(
            list(loaded_a["UUID"]) == list(loaded_b["UUID"]),
            "task uuids survive a whole-table rewrite",
        )

        # Recurring — same helper under the hood, but exercise it explicitly.
        df1 = pd.DataFrame([_sample_task_row("rec-1")])
        db.save_recurring_df(df1)
        loaded_a = db.load_recurring_df()
        uuid_before = loaded_a["UUID"].iloc[0]
        db.save_recurring_df(loaded_a)
        loaded_b = db.load_recurring_df()
        check(loaded_b["UUID"].iloc[0] == uuid_before, "recurring uuid survives rewrite")

        # Discipline list.
        df1 = pd.DataFrame([_sample_discipline_row("Push-ups"), _sample_discipline_row("Read")])
        db.save_discipline_df(df1)
        loaded_a = db.load_discipline_df().sort_values("TASK").reset_index(drop=True)
        check(loaded_a["UUID"].notna().all(), "discipline uuids minted on first save")
        db.save_discipline_df(loaded_a)
        loaded_b = db.load_discipline_df().sort_values("TASK").reset_index(drop=True)
        check(
            list(loaded_a["UUID"]) == list(loaded_b["UUID"]),
            "discipline uuids survive a whole-table rewrite",
        )

        # Follow-ups.
        df1 = pd.DataFrame([_sample_follow_up_row("Do Dishes", "Put up Dishes")])
        db.save_follow_ups(df1)
        loaded_a = db.load_follow_ups()
        uuid_before = loaded_a["UUID"].iloc[0]
        db.save_follow_ups(loaded_a)
        loaded_b = db.load_follow_ups()
        check(loaded_b["UUID"].iloc[0] == uuid_before, "follow-up uuid survives rewrite")
        _dispose(db)


# --- Test 4: v1 -> v2 migration is non-destructive ---------------------------

def test_v1_to_v2_migration() -> None:
    print("\n== Test 4: v1 -> v2 migration is non-destructive ==")
    with tempfile.TemporaryDirectory(ignore_cleanup_errors=True) as tmp:
        _fresh_db_env(tmp)
        db = _fresh_import()

        # Fabricate a v1 DB: create the four list tables WITHOUT uuid, write
        # schema_version=1, insert known row counts.
        with db._ENGINE.begin() as conn:
            conn.execute(text("""
                CREATE TABLE tasks (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    task TEXT NOT NULL, priority INTEGER, status TEXT,
                    due_date TEXT, relevant_link TEXT, catagory TEXT,
                    task_group TEXT, sub_group TEXT, task_creation TEXT,
                    start_time TEXT, estimated_time REAL, logged_hours REAL,
                    completed INTEGER, completed_time TEXT,
                    recurring INTEGER, recurring_interval INTEGER
                )
            """))
            conn.execute(text("""
                CREATE TABLE recurring_tasks (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    task TEXT NOT NULL, priority INTEGER, status TEXT,
                    due_date TEXT, relevant_link TEXT, catagory TEXT,
                    task_group TEXT, sub_group TEXT, task_creation TEXT,
                    start_time TEXT, estimated_time REAL, logged_hours REAL,
                    completed INTEGER, completed_time TEXT,
                    recurring INTEGER, recurring_interval INTEGER
                )
            """))
            conn.execute(text("""
                CREATE TABLE discipline_list (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    task TEXT NOT NULL, catagory TEXT,
                    frequency_per_week INTEGER, active INTEGER, current_streak INTEGER
                )
            """))
            conn.execute(text("""
                CREATE TABLE follow_up_tasks (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    trigger_task TEXT NOT NULL, follow_up_task TEXT NOT NULL,
                    catagory TEXT, task_group TEXT, subgroup TEXT,
                    relevant_link TEXT, priority INTEGER, estimated_time REAL,
                    due_offset_days INTEGER, created TEXT
                )
            """))
            conn.execute(text("CREATE TABLE schema_version (version INTEGER NOT NULL)"))
            conn.execute(text("INSERT INTO schema_version (version) VALUES (1)"))
            # 18/4/6/0 like production (skip completions - not part of scope).
            for i in range(18):
                conn.execute(text("INSERT INTO tasks (task) VALUES (:t)"), {"t": f"t{i}"})
            for i in range(4):
                conn.execute(text("INSERT INTO recurring_tasks (task) VALUES (:t)"), {"t": f"r{i}"})
            for i in range(6):
                conn.execute(text("INSERT INTO discipline_list (task) VALUES (:t)"), {"t": f"d{i}"})

        # Record counts before migration.
        with db._ENGINE.connect() as conn:
            counts_before = {
                t: conn.execute(text(f"SELECT COUNT(*) FROM {t}")).scalar()
                for t in db._UUID_TABLES
            }

        # Trigger migration.
        db._INITIALIZED = False
        db.init_db()

        with db._ENGINE.connect() as conn:
            version = conn.execute(text("SELECT version FROM schema_version")).scalar()
            check(version == 2, f"schema_version == 2 after migration (got {version})")
            for table in db._UUID_TABLES:
                cols = [r.name for r in conn.execute(text(f"PRAGMA table_info({table})")).all()]
                check("uuid" in cols, f"{table} has uuid column after migration")
                count_after = conn.execute(text(f"SELECT COUNT(*) FROM {table}")).scalar()
                check(
                    count_after == counts_before[table],
                    f"{table} row count unchanged: {counts_before[table]} -> {count_after}",
                )
                nulls = conn.execute(
                    text(f"SELECT COUNT(*) FROM {table} WHERE uuid IS NULL")
                ).scalar()
                check(nulls == 0, f"{table} has zero null uuids after backfill")
                idx = conn.execute(
                    text("SELECT name FROM sqlite_master WHERE type='index' AND name=:i"),
                    {"i": f"idx_{table}_uuid"},
                ).scalar()
                check(idx is not None, f"{table} has unique uuid index after migration")

        # Second init is a clean no-op (already at v2).
        db._INITIALIZED = False
        db.init_db()
        with db._ENGINE.connect() as conn:
            version = conn.execute(text("SELECT version FROM schema_version")).scalar()
            check(version == 2, f"still v2 after second init (got {version})")
        _dispose(db)


if __name__ == "__main__":
    test_fresh_and_idempotent()
    test_round_trip_preserves_uuid()
    test_v1_to_v2_migration()
    print("\nAll UUID smoke tests passed.")
