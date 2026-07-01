"""Shared configuration loaded from config.json — imported by all modules."""
import json
import os
from pathlib import PurePosixPath, PureWindowsPath, Path

# Project root = parent of the bot_modules/ folder this file lives in.
# Anchoring paths here makes the bot cwd-independent and cross-platform.
_PROJECT_ROOT = Path(__file__).resolve().parent.parent
_TO_DO_DIR = _PROJECT_ROOT / "to_do_list"


def _normalize_path(raw, default_relative):
    """Accept any path string (Windows or POSIX style) from config and return
    an absolute path anchored to the project root if it was relative. This
    keeps the bot working even if config.json carries legacy `to_do_list\\x.pkl`
    entries on a Linux host."""
    if not raw:
        return str(_PROJECT_ROOT / default_relative)
    # Split on either separator so we don't depend on the host OS.
    parts = PureWindowsPath(raw).parts if "\\" in raw else PurePosixPath(raw).parts
    candidate = Path(*parts)
    if not candidate.is_absolute():
        candidate = _PROJECT_ROOT / candidate
    return str(candidate)


with open(_PROJECT_ROOT / "config.json") as f:
    config = json.load(f)

command_prefix = "!L "

channel_id = config["Channel_ID"]
user_id = config["User_ID"]

path_for_to_do_list = str(_TO_DO_DIR / "to_do_list.pkl")
path_for_recurring_tasks = str(_TO_DO_DIR / "recurring_tasks.pkl")
path_for_follow_up_tasks = _normalize_path(config.get("Follow_Up_Tasks_Path"), "to_do_list/follow_up_tasks.pkl")
path_for_discipline_list = _normalize_path(config.get("Discipline_List_Path"), "to_do_list/discipline_list.pkl")
path_for_discipline_completion_log = _normalize_path(config.get("Discipline_Completion_Log_Path"), "to_do_list/discipline_completion_log.pkl")
path_for_discipline_history = _normalize_path(config.get("Discipline_History_Path"), "to_do_list/discipline_history.pkl")

# SQLite database. Env var LUIGI_DB_PATH wins, then config.json "Database_Path",
# then project-local default (<repo>/luigi.db) so dev works out of the box.
# On the Linux host, override via config.json to e.g. "/mnt/luigi/luigi.db".
database_path = os.environ.get(
    "LUIGI_DB_PATH",
    _normalize_path(config.get("Database_Path"), "luigi.db"),
)

# --- Database backend selection ---------------------------------------------
# "sqlite" (default) keeps existing behavior. Set to "postgres" to point db.py
# at a shared Postgres server. Precedence per field: env var > config.json > default.
db_backend = os.environ.get(
    "LUIGI_DB_BACKEND", config.get("DB_Backend", "sqlite")
).strip().lower()

# Full SQLAlchemy URL wins if provided (env or config). Otherwise db.py
# assembles one from the discrete PG_* fields below.
database_url = os.environ.get("LUIGI_DATABASE_URL", config.get("Database_URL"))

pg_host = os.environ.get("LUIGI_PG_HOST", config.get("PG_Host", "127.0.0.1"))
pg_port = int(os.environ.get("LUIGI_PG_PORT", config.get("PG_Port", 5432)))
pg_database = os.environ.get("LUIGI_PG_DB", config.get("PG_Database", "luigi_todo"))
pg_user = os.environ.get("LUIGI_PG_USER", config.get("PG_User", "luigi_app"))
# Password is env-only by design. Do NOT read it from config.json — that file
# already holds the Discord bot token and should not accumulate more secrets.
pg_password = os.environ.get("LUIGI_PG_PASSWORD", "")

discipline_delete_after_seconds = int(config.get("Discipline_Delete_After_Seconds", 7200))
discipline_daily_hour = int(config.get("Discipline_Daily_Hour", 23))
discipline_daily_minute = int(config.get("Discipline_Daily_Minute", 15))
discipline_at_risk_weekday = int(config.get("Discipline_At_Risk_Weekday", 3))  # 0=Mon ... 6=Sun
discipline_at_risk_hour = int(config.get("Discipline_At_Risk_Hour", 17))
discipline_at_risk_minute = int(config.get("Discipline_At_Risk_Minute", 0))
