"""Discipline tracker data helpers — row builders, data processing, streaks, embeds."""
import os
import datetime

import discord
import pandas as pd

from .bot_config import (
    command_prefix,
    path_for_discipline_list,
    path_for_discipline_completion_log,
)


# --- Row Builders ---

def build_discipline_row(task_name, catagory, frequency_per_week):
    return pd.DataFrame(
        {
            "TASK": [task_name],
            "CATAGORY": [catagory],
            "FREQUENCY_PER_WEEK": [int(frequency_per_week)],
            "ACTIVE": [True],
            "CURRENT_STREAK": [0],
        }
    )


def build_discipline_completion_row(task_name, catagory, completed_date):
    completed_dt = pd.to_datetime(completed_date)
    return pd.DataFrame(
        {
            "TASK": [task_name],
            "CATAGORY": [catagory],
            "COMPLETED_DATE": [completed_dt.normalize()],
            "LOGGED_AT": [pd.to_datetime(datetime.datetime.now().isoformat(' ', 'seconds'))],
        }
    )


# --- File Initialization ---

def ensure_discipline_dataframe_exists():
    os.makedirs(os.path.dirname(path_for_discipline_list), exist_ok=True)

    expected_cols = ["TASK", "CATAGORY", "FREQUENCY_PER_WEEK", "ACTIVE", "CURRENT_STREAK"]

    if os.path.exists(path_for_discipline_list):
        try:
            existing_df = pd.read_pickle(path_for_discipline_list)
            if set(expected_cols).issubset(existing_df.columns):
                existing_df = existing_df[expected_cols].copy()
                existing_df["FREQUENCY_PER_WEEK"] = pd.to_numeric(existing_df["FREQUENCY_PER_WEEK"], errors="coerce").fillna(1).astype(int)
                existing_df["FREQUENCY_PER_WEEK"] = existing_df["FREQUENCY_PER_WEEK"].clip(lower=1, upper=7)
                existing_df["ACTIVE"] = existing_df["ACTIVE"].astype(bool).fillna(True)
                existing_df["CURRENT_STREAK"] = pd.to_numeric(existing_df["CURRENT_STREAK"], errors="coerce").fillna(0).astype(int)
                existing_df.to_pickle(path_for_discipline_list)
                return

            migrated_df = pd.DataFrame(
                {
                    "TASK": existing_df["TASK"].astype(str) if "TASK" in existing_df.columns else pd.Series(dtype="object"),
                    "CATAGORY": existing_df["CATAGORY"].astype(str) if "CATAGORY" in existing_df.columns else "Discipline",
                    "FREQUENCY_PER_WEEK": 1,
                    "ACTIVE": True,
                    "CURRENT_STREAK": 0,
                }
            )
            migrated_df.to_pickle(path_for_discipline_list)
            return
        except Exception:
            pass

    pd.DataFrame(columns=expected_cols).to_pickle(path_for_discipline_list)


def ensure_discipline_completion_log_exists():
    os.makedirs(os.path.dirname(path_for_discipline_completion_log), exist_ok=True)

    expected_cols = ["TASK", "CATAGORY", "COMPLETED_DATE", "LOGGED_AT"]

    if os.path.exists(path_for_discipline_completion_log):
        try:
            existing_df = pd.read_pickle(path_for_discipline_completion_log)
            if set(expected_cols).issubset(existing_df.columns):
                existing_df = existing_df[expected_cols].copy()
                existing_df.to_pickle(path_for_discipline_completion_log)
                return
        except Exception:
            pass

    pd.DataFrame(columns=expected_cols).to_pickle(path_for_discipline_completion_log)


# --- Data Processing ---

def normalize_discipline_completion_df(completion_df):
    if completion_df.empty:
        return completion_df
    normalized = completion_df.copy()
    normalized["TASK"] = normalized["TASK"].astype(str).str.strip()
    normalized["COMPLETED_DATE"] = pd.to_datetime(normalized["COMPLETED_DATE"], errors="coerce").dt.normalize()
    return normalized.dropna(subset=["COMPLETED_DATE"])


def build_discipline_weekly_counts(discipline_df, completion_df, start_date, end_date):
    weekly_counts = {}
    weekly_counts_before_today = {}

    if not completion_df.empty:
        completion_df = normalize_discipline_completion_df(completion_df)
        weekly_df = completion_df[
            (completion_df["COMPLETED_DATE"] >= start_date)
            & (completion_df["COMPLETED_DATE"] <= end_date)
        ]

        if not weekly_df.empty:
            weekly_counts = weekly_df.groupby("TASK")["COMPLETED_DATE"].nunique().to_dict()

        before_today_df = completion_df[
            (completion_df["COMPLETED_DATE"] >= start_date)
            & (completion_df["COMPLETED_DATE"] < end_date)
        ]
        if not before_today_df.empty:
            weekly_counts_before_today = before_today_df.groupby("TASK")["COMPLETED_DATE"].nunique().to_dict()

    report_df = discipline_df.copy()
    report_df["TASK"] = report_df["TASK"].astype(str).str.strip()
    report_df["FREQUENCY_PER_WEEK"] = pd.to_numeric(report_df["FREQUENCY_PER_WEEK"], errors="coerce").fillna(1).astype(int)
    report_df["FREQUENCY_PER_WEEK"] = report_df["FREQUENCY_PER_WEEK"].clip(lower=1, upper=7)
    report_df["COMPLETIONS_THIS_WEEK"] = report_df["TASK"].map(weekly_counts).fillna(0).astype(int)
    report_df["COMPLETIONS_BEFORE_END_DATE"] = report_df["TASK"].map(weekly_counts_before_today).fillna(0).astype(int)

    return report_df.sort_values(by=["FREQUENCY_PER_WEEK", "TASK"], ascending=[False, True])


def get_active_discipline_df(discipline_list_df):
    filtered_df = discipline_list_df.copy()

    if filtered_df.empty:
        return filtered_df

    if "ACTIVE" in filtered_df.columns:
        filtered_df = filtered_df[filtered_df["ACTIVE"] == True]

    return filtered_df.sort_values(by=["FREQUENCY_PER_WEEK", "TASK"], ascending=[False, True])


def get_task_completed_today(task_name, completion_log_df, target_date):
    target_date_normalized = pd.to_datetime(target_date).normalize()
    matching = completion_log_df[
        (completion_log_df["TASK"].astype(str).str.lower() == str(task_name).strip().lower())
        & (completion_log_df["COMPLETED_DATE"] == target_date_normalized)
    ]
    return not matching.empty


# --- Streak & Consistency ---

def calculate_streak_metrics(completion_dates, reference_date):
    normalized_dates = sorted(
        {
            pd.to_datetime(date_value).normalize()
            for date_value in completion_dates
            if not pd.isna(date_value)
        }
    )

    if not normalized_dates:
        return 0, 0

    longest_streak = 1
    running_streak = 1
    for current_date, next_date in zip(normalized_dates, normalized_dates[1:]):
        if next_date - current_date == pd.Timedelta(days=1):
            running_streak += 1
        else:
            longest_streak = max(longest_streak, running_streak)
            running_streak = 1

    longest_streak = max(longest_streak, running_streak)

    current_streak = 0
    reference_day = pd.to_datetime(reference_date).normalize()
    date_set = set(normalized_dates)
    cursor = reference_day
    while cursor in date_set:
        current_streak += 1
        cursor -= pd.Timedelta(days=1)

    return current_streak, longest_streak


def calculate_consistency_score(completion_dates, frequency_per_week, reference_date, lookback_days=28):
    target_per_week = max(1, min(int(frequency_per_week), 7))
    window_end = pd.to_datetime(reference_date).normalize()
    window_start = window_end - pd.Timedelta(days=lookback_days - 1)

    normalized_dates = {
        pd.to_datetime(date_value).normalize()
        for date_value in completion_dates
        if not pd.isna(date_value)
    }
    actual_count = sum(1 for date_value in normalized_dates if window_start <= date_value <= window_end)

    expected_count = max((target_per_week / 7) * lookback_days, 1)
    return round(min(actual_count / expected_count, 1) * 100, 1)


def calculate_streak(task_name, completion_df, reference_date=None):
    """Calculate current streak for a task based on completion log."""
    if reference_date is None:
        reference_date = pd.to_datetime(datetime.datetime.now().date()).normalize()
    else:
        reference_date = pd.to_datetime(reference_date).normalize()

    if completion_df.empty:
        return 0

    task_completions = completion_df[completion_df["TASK"].astype(str).str.lower() == str(task_name).strip().lower()].copy()
    if task_completions.empty:
        return 0

    task_completions["COMPLETED_DATE"] = pd.to_datetime(task_completions["COMPLETED_DATE"]).dt.normalize()
    unique_dates = sorted(task_completions["COMPLETED_DATE"].unique(), reverse=True)

    if not unique_dates:
        return 0

    streak = 0
    current_date = reference_date

    for completion_date in unique_dates:
        if completion_date == current_date:
            streak += 1
            current_date = current_date - pd.Timedelta(days=1)
        else:
            break

    return streak


# --- Insight Builder ---

def build_discipline_insight_df(discipline_df, completion_df, start_date, end_date, reference_date=None):
    reference_day = pd.to_datetime(reference_date if reference_date is not None else end_date).normalize()
    normalized_completion_df = normalize_discipline_completion_df(completion_df)
    report_df = build_discipline_weekly_counts(discipline_df, normalized_completion_df, start_date, end_date).copy()

    if normalized_completion_df.empty:
        report_df["CURRENT_STREAK"] = 0
        report_df["LONGEST_STREAK"] = 0
        report_df["CONSISTENCY_SCORE"] = 0.0
        report_df["COMPLETED_TODAY"] = False
    else:
        completion_dates_by_task = (
            normalized_completion_df.groupby("TASK")["COMPLETED_DATE"].apply(list).to_dict()
        )
        report_df["CURRENT_STREAK"] = report_df["TASK"].map(
            lambda task_name: calculate_streak_metrics(
                completion_dates_by_task.get(str(task_name).strip(), []),
                reference_day,
            )[0]
        )
        report_df["LONGEST_STREAK"] = report_df["TASK"].map(
            lambda task_name: calculate_streak_metrics(
                completion_dates_by_task.get(str(task_name).strip(), []),
                reference_day,
            )[1]
        )
        report_df["CONSISTENCY_SCORE"] = report_df.apply(
            lambda row: calculate_consistency_score(
                completion_dates_by_task.get(str(row["TASK"]).strip(), []),
                row["FREQUENCY_PER_WEEK"],
                reference_day,
            ),
            axis=1,
        )
        report_df["COMPLETED_TODAY"] = report_df["TASK"].apply(
            lambda task_name: get_task_completed_today(task_name, normalized_completion_df, reference_day)
        )

    report_df["REMAINING_THIS_WEEK"] = (
        report_df["FREQUENCY_PER_WEEK"] - report_df["COMPLETIONS_THIS_WEEK"]
    ).clip(lower=0)

    if reference_day > pd.to_datetime(end_date).normalize():
        available_days = 0
    else:
        days_remaining_including_today = (pd.to_datetime(end_date).normalize() - reference_day).days + 1
        available_days = days_remaining_including_today - report_df["COMPLETED_TODAY"].astype(int)
        available_days = available_days.clip(lower=0)

    report_df["AVAILABLE_DAYS_LEFT"] = available_days
    report_df["AT_RISK_THIS_WEEK"] = report_df["REMAINING_THIS_WEEK"] > report_df["AVAILABLE_DAYS_LEFT"]
    report_df["MISSED_TARGET"] = report_df["COMPLETIONS_THIS_WEEK"] < report_df["FREQUENCY_PER_WEEK"]

    return report_df


# --- Alert & Embed Builders ---

def build_discipline_alert_summary(report_df, for_current_week=True):
    if report_df.empty:
        return ""

    if for_current_week:
        flagged_df = report_df[report_df["AT_RISK_THIS_WEEK"]]
        prefix = "At risk this week"
    else:
        flagged_df = report_df[report_df["MISSED_TARGET"]]
        prefix = "Missed target"

    if flagged_df.empty:
        return "No missed-target alerts."

    task_names = flagged_df["TASK"].astype(str).tolist()
    preview = ", ".join(task_names[:4])
    suffix = "..." if len(task_names) > 4 else ""
    return f"{prefix}: {preview}{suffix}"


def build_discipline_daily_embed(discipline_df, completion_log_df, now_est):
    embed = discord.Embed(
        title=f"Discipline Tracker - {now_est.strftime('%m/%d/%Y')}",
        description="End-of-day reminder: log what you completed today.",
        color=0x2ECC71,
    )

    if discipline_df.empty:
        embed.add_field(name="No Tracked Items", value=f"Use {command_prefix}create_discipline_task to add items to track.", inline=False)
        return embed

    today = pd.to_datetime(now_est.date()).normalize()
    pending_tasks = []
    logged_tasks = []

    for _, row in discipline_df.iterrows():
        task_name = str(row["TASK"])
        if get_task_completed_today(task_name, completion_log_df, today):
            logged_tasks.append(task_name)
        else:
            pending_tasks.append(row)

    if not pending_tasks:
        embed.add_field(
            name="All Done!",
            value=f"You've logged all {len(logged_tasks)} discipline items for today.",
            inline=False,
        )
        if logged_tasks:
            embed.set_footer(text="Logged: " + ", ".join(logged_tasks[:5]) + ("..." if len(logged_tasks) > 5 else ""))
        return embed

    count = 0
    for row in pending_tasks:
        if count >= 20:
            break
        task_name = str(row["TASK"])
        value = f"Category: {row['CATAGORY']}\nFrequency/Week: {row['FREQUENCY_PER_WEEK']}"
        embed.add_field(name=f"{count + 1}. {task_name}", value=value, inline=False)
        count += 1

    pending_count = len(pending_tasks)
    logged_count = len(logged_tasks)

    week_start = today - pd.Timedelta(days=int(today.weekday()))
    week_end = week_start + pd.Timedelta(days=6)
    insight_df = build_discipline_insight_df(discipline_df, completion_log_df, week_start, week_end, reference_date=today)
    streak_leader_df = insight_df.sort_values(by=["CURRENT_STREAK", "LONGEST_STREAK", "TASK"], ascending=[False, False, True])
    if not streak_leader_df.empty and int(streak_leader_df.iloc[0]["CURRENT_STREAK"]) > 0:
        leader = streak_leader_df.iloc[0]
        embed.add_field(
            name="Streak Leader",
            value=(
                f"{leader['TASK']}\n"
                f"Current: {int(leader['CURRENT_STREAK'])} day(s)\n"
                f"Best: {int(leader['LONGEST_STREAK'])} day(s)"
            ),
            inline=False,
        )

    alert_summary = build_discipline_alert_summary(insight_df, for_current_week=True)
    embed.add_field(name="Weekly Alert", value=alert_summary, inline=False)
    embed.set_footer(text=f"Pending: {pending_count} | Logged: {logged_count} | Use {command_prefix}log_discipline_completion to log")

    return embed
