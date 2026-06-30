"""Shared configuration loaded from config.json — imported by all modules."""
import json
from pathlib import Path

# Project root = parent of the bot_modules/ folder this file lives in.
# Anchoring paths here makes the bot cwd-independent and cross-platform.
_PROJECT_ROOT = Path(__file__).resolve().parent.parent
_TO_DO_DIR = _PROJECT_ROOT / "to_do_list"

with open(_PROJECT_ROOT / "config.json") as f:
    config = json.load(f)

command_prefix = "!L "

channel_id = config["Channel_ID"]
user_id = config["User_ID"]

path_for_to_do_list = str(_TO_DO_DIR / "to_do_list.pkl")
path_for_recurring_tasks = str(_TO_DO_DIR / "recurring_tasks.pkl")
path_for_follow_up_tasks = config.get("Follow_Up_Tasks_Path", str(_TO_DO_DIR / "follow_up_tasks.pkl"))
path_for_discipline_list = config.get("Discipline_List_Path", str(_TO_DO_DIR / "discipline_list.pkl"))
path_for_discipline_completion_log = config.get("Discipline_Completion_Log_Path", str(_TO_DO_DIR / "discipline_completion_log.pkl"))
path_for_discipline_history = config.get("Discipline_History_Path", str(_TO_DO_DIR / "discipline_history.pkl"))

discipline_delete_after_seconds = int(config.get("Discipline_Delete_After_Seconds", 7200))
discipline_daily_hour = int(config.get("Discipline_Daily_Hour", 23))
discipline_daily_minute = int(config.get("Discipline_Daily_Minute", 15))
discipline_at_risk_weekday = int(config.get("Discipline_At_Risk_Weekday", 3))  # 0=Mon ... 6=Sun
discipline_at_risk_hour = int(config.get("Discipline_At_Risk_Hour", 17))
discipline_at_risk_minute = int(config.get("Discipline_At_Risk_Minute", 0))
