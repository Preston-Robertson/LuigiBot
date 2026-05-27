"""Shared configuration loaded from config.json — imported by all modules."""
import json
import os

with open("config.json") as f:
    config = json.load(f)

command_prefix = "!L "

channel_id = config["Channel_ID"]
user_id = config["User_ID"]

path_for_to_do_list = "to_do_list\\to_do_list.pkl"
path_for_recurring_tasks = "to_do_list\\recurring_tasks.pkl"
path_for_discipline_list = config.get("Discipline_List_Path", "to_do_list\\discipline_list.pkl")
path_for_discipline_completion_log = config.get("Discipline_Completion_Log_Path", "to_do_list\\discipline_completion_log.pkl")
path_for_discipline_history = config.get("Discipline_History_Path", "to_do_list\\discipline_history.pkl")

discipline_delete_after_seconds = int(config.get("Discipline_Delete_After_Seconds", 7200))
discipline_daily_hour = int(config.get("Discipline_Daily_Hour", 23))
discipline_daily_minute = int(config.get("Discipline_Daily_Minute", 15))
discipline_at_risk_weekday = int(config.get("Discipline_At_Risk_Weekday", 3))  # 0=Mon ... 6=Sun
discipline_at_risk_hour = int(config.get("Discipline_At_Risk_Hour", 17))
discipline_at_risk_minute = int(config.get("Discipline_At_Risk_Minute", 0))
