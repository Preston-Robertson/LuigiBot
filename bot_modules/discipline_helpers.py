"""Discipline tracker data helpers — row builders, data processing, streaks, embeds.

Data persistence lives in `bot_modules.db` (SQLite). The `ensure_*` /
`read_discipline_history` / `set_discipline_cell` / `is_task_completed_on` /
`load_discipline_completion_df` names are kept for call-site compatibility;
they just delegate to the DB layer.
"""
import os
import datetime

import discord
import pandas as pd

from .bot_config import (
    command_prefix,
    path_for_discipline_list,
    path_for_discipline_completion_log,
    path_for_discipline_history,
)
from . import db


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
# Kept as callable functions for backward compatibility with existing call
# sites; the real work is `db.init_db()` (idempotent, cheap after first call).

def ensure_discipline_dataframe_exists():
    db.init_db()


def ensure_discipline_completion_log_exists():
    db.init_db()


# --- Discipline History Matrix (rebuilt from SQL on demand) ---
# The wide DatetimeIndex x task matrix is no longer stored — it's projected
# from `discipline_completions` in db.py. Downstream discipline code sees the
# same DataFrame shape it always has.

def ensure_discipline_history_exists():
    db.init_db()


def read_discipline_history():
    return db.read_discipline_history()


def write_discipline_history(history_df):
    """No-op — history is now derived from `discipline_completions` in SQL.

    Kept so any lingering callers don't crash; state changes go through
    `set_discipline_cell` / `db.append_discipline_completion` instead.
    """
    return None


def set_discipline_cell(task_name, date, value):
    return db.set_discipline_cell(task_name, date, value)


def is_task_completed_on(task_name, date, history_df=None):
    return db.is_task_completed_on(task_name, date, history_df=history_df)


def history_matrix_to_long_log(history_df, discipline_list_df=None):
    """Convert the wide matrix into the legacy long-format log (only True cells).

    Returns columns: TASK, CATAGORY, COMPLETED_DATE, LOGGED_AT.
    LOGGED_AT is set to midnight of COMPLETED_DATE (precise log time is no longer stored).
    """
    empty = pd.DataFrame(columns=["TASK", "CATAGORY", "COMPLETED_DATE", "LOGGED_AT"])
    if history_df is None or history_df.empty:
        return empty

    # Stack to (DATE, TASK) -> value, dropping NaN automatically.
    try:
        stacked = history_df.stack(future_stack=True).dropna()
    except TypeError:  # older pandas
        stacked = history_df.stack(dropna=True)
    if stacked.empty:
        return empty

    truthy = stacked[stacked.astype(bool)]
    if truthy.empty:
        return empty

    long_df = truthy.reset_index()
    long_df.columns = ["COMPLETED_DATE", "TASK", "_VAL"]
    long_df = long_df.drop(columns=["_VAL"])
    long_df["COMPLETED_DATE"] = pd.to_datetime(long_df["COMPLETED_DATE"]).dt.normalize()
    long_df["LOGGED_AT"] = long_df["COMPLETED_DATE"]
    long_df["TASK"] = long_df["TASK"].astype(str)

    if discipline_list_df is not None and not discipline_list_df.empty and "CATAGORY" in discipline_list_df.columns:
        cat_map = dict(
            zip(
                discipline_list_df["TASK"].astype(str).str.strip(),
                discipline_list_df["CATAGORY"].astype(str),
            )
        )
        long_df["CATAGORY"] = long_df["TASK"].map(cat_map).fillna("Discipline")
    else:
        long_df["CATAGORY"] = "Discipline"

    return long_df[["TASK", "CATAGORY", "COMPLETED_DATE", "LOGGED_AT"]]


def load_discipline_completion_df():
    """Return long-format completion DF straight from SQL."""
    return db.load_discipline_completion_df()


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


# --- Progress Bar Embed ---

def build_text_progress_bar(actual, target, width=10, filled_char="▰", empty_char="▱"):
    """Render a discrete text progress bar capped at width segments.

    `actual` may exceed `target`; the bar still caps at width but the caller can show overflow.
    """
    target_int = max(int(target), 1)
    actual_int = max(int(actual), 0)
    ratio = min(actual_int / target_int, 1.0)
    filled = int(round(ratio * width))
    filled = max(0, min(width, filled))
    return filled_char * filled + empty_char * (width - filled)


def build_discipline_progress_embed(discipline_df, completion_df, reference_date=None, bar_width=10):
    """Embed showing weekly progress (X/Y + text bar + percent) for every active discipline."""
    if reference_date is None:
        reference_day = pd.to_datetime(datetime.datetime.now().date()).normalize()
    else:
        reference_day = pd.to_datetime(reference_date).normalize()

    week_start = reference_day - pd.Timedelta(days=int(reference_day.weekday()))
    week_end = week_start + pd.Timedelta(days=6)

    active_df = get_active_discipline_df(discipline_df)

    embed = discord.Embed(
        title=f"Discipline Weekly Progress ({week_start.strftime('%m/%d')} - {week_end.strftime('%m/%d')})",
        description="Partial-credit view: how far along you are toward each weekly target.",
        color=0x2ECC71,
    )

    if active_df.empty:
        embed.add_field(
            name="No Tracked Items",
            value=f"Use {command_prefix}create_discipline_task to start tracking.",
            inline=False,
        )
        return embed

    insight_df = build_discipline_insight_df(
        active_df, completion_df, week_start, week_end, reference_date=reference_day
    )
    # Sort: at-risk first, then by lowest completion percent, then by frequency.
    insight_df = insight_df.copy()
    insight_df["_PERCENT"] = insight_df.apply(
        lambda r: (int(r["COMPLETIONS_THIS_WEEK"]) / max(int(r["FREQUENCY_PER_WEEK"]), 1)),
        axis=1,
    )
    sorted_df = insight_df.sort_values(
        by=["AT_RISK_THIS_WEEK", "_PERCENT", "FREQUENCY_PER_WEEK"],
        ascending=[False, True, False],
    )

    total_target = int(sorted_df["FREQUENCY_PER_WEEK"].sum())
    total_actual = int(sorted_df["COMPLETIONS_THIS_WEEK"].sum())
    overall_percent = round(min(total_actual / total_target, 1) * 100, 1) if total_target > 0 else 0.0

    count = 0
    for _, row in sorted_df.iterrows():
        if count >= 20:
            break
        task_name = str(row["TASK"])
        target = int(row["FREQUENCY_PER_WEEK"])
        actual = int(row["COMPLETIONS_THIS_WEEK"])
        percent = round(min(actual / target, 1) * 100, 1) if target > 0 else 0.0
        overflow = actual - target
        bar = build_text_progress_bar(actual, target, width=bar_width)

        overflow_tag = f" (+{overflow} over)" if overflow > 0 else ""
        at_risk_tag = " ⚠️ at risk" if bool(row["AT_RISK_THIS_WEEK"]) else ""
        completed_today_tag = " ✅ today" if bool(row["COMPLETED_TODAY"]) else ""

        value = (
            f"`{bar}` {actual}/{target} ({percent}%){overflow_tag}\n"
            f"Category: {row['CATAGORY']}{at_risk_tag}{completed_today_tag}\n"
            f"Streak: {int(row['CURRENT_STREAK'])} day(s) | Best: {int(row['LONGEST_STREAK'])}"
        )
        embed.add_field(name=f"{count + 1}. {task_name}", value=value, inline=False)
        count += 1

    overall_bar = build_text_progress_bar(total_actual, total_target, width=bar_width)
    embed.add_field(
        name="Overall",
        value=f"`{overall_bar}` {total_actual}/{total_target} ({overall_percent}%)",
        inline=False,
    )

    alert_summary = build_discipline_alert_summary(insight_df, for_current_week=True)
    embed.set_footer(text=alert_summary or "On pace this week.")
    return embed


# --- Category Rollup ---

def build_discipline_category_rollup_df(discipline_df, completion_df, week_start, week_end):
    """Aggregate active disciplines by category for a single week.

    Returns columns: CATAGORY, TASK_COUNT, TARGET_SUM, ACTUAL_SUM, ADHERENCE_PERCENT (0-100, capped at 100).
    """
    active_df = get_active_discipline_df(discipline_df)
    empty = pd.DataFrame(columns=["CATAGORY", "TASK_COUNT", "TARGET_SUM", "ACTUAL_SUM", "ADHERENCE_PERCENT"])
    if active_df.empty:
        return empty

    weekly_counts_df = build_discipline_weekly_counts(active_df, completion_df, week_start, week_end)
    weekly_counts_df = weekly_counts_df.copy()
    weekly_counts_df["CATAGORY"] = weekly_counts_df["CATAGORY"].astype(str)

    grouped = weekly_counts_df.groupby("CATAGORY", as_index=False).agg(
        TASK_COUNT=("TASK", "nunique"),
        TARGET_SUM=("FREQUENCY_PER_WEEK", "sum"),
        ACTUAL_SUM=("COMPLETIONS_THIS_WEEK", "sum"),
    )
    grouped["TARGET_SUM"] = grouped["TARGET_SUM"].astype(int)
    grouped["ACTUAL_SUM"] = grouped["ACTUAL_SUM"].astype(int)
    grouped["ADHERENCE_PERCENT"] = grouped.apply(
        lambda r: round(min(r["ACTUAL_SUM"] / r["TARGET_SUM"], 1) * 100, 1) if r["TARGET_SUM"] > 0 else 0.0,
        axis=1,
    )
    return grouped.sort_values(by=["ADHERENCE_PERCENT", "TARGET_SUM"], ascending=[True, False]).reset_index(drop=True)


# --- At-Risk Nudge Embed ---

def build_discipline_at_risk_embed(discipline_df, completion_df, reference_date=None):
    """Embed surfacing disciplines that won't hit weekly frequency at current pace.

    Tiers:
      - At risk (hard): REMAINING > AVAILABLE_DAYS_LEFT (mathematically impossible to hit target).
      - Tight (soft): REMAINING == AVAILABLE_DAYS_LEFT (must complete every remaining day).
    """
    if reference_date is None:
        reference_day = pd.to_datetime(datetime.datetime.now().date()).normalize()
    else:
        reference_day = pd.to_datetime(reference_date).normalize()

    week_start = reference_day - pd.Timedelta(days=int(reference_day.weekday()))
    week_end = week_start + pd.Timedelta(days=6)
    days_left = (week_end - reference_day).days + 1  # includes today

    active_df = get_active_discipline_df(discipline_df)

    embed = discord.Embed(
        title=f"Midweek Discipline Check ({reference_day.strftime('%a %m/%d')})",
        description=(
            f"Week {week_start.strftime('%m/%d')} - {week_end.strftime('%m/%d')} | "
            f"Days remaining (incl. today): {days_left}"
        ),
        color=0xED4245,
    )

    if active_df.empty:
        embed.add_field(
            name="No Tracked Items",
            value=f"Use {command_prefix}create_discipline_task to start tracking.",
            inline=False,
        )
        return embed

    insight_df = build_discipline_insight_df(
        active_df, completion_df, week_start, week_end, reference_date=reference_day
    )

    at_risk_df = insight_df[insight_df["AT_RISK_THIS_WEEK"]].copy()
    tight_df = insight_df[
        (~insight_df["AT_RISK_THIS_WEEK"])
        & (insight_df["REMAINING_THIS_WEEK"] > 0)
        & (insight_df["REMAINING_THIS_WEEK"] == insight_df["AVAILABLE_DAYS_LEFT"])
    ].copy()
    on_pace_count = int(
        (
            (~insight_df["AT_RISK_THIS_WEEK"])
            & ~(
                (insight_df["REMAINING_THIS_WEEK"] > 0)
                & (insight_df["REMAINING_THIS_WEEK"] == insight_df["AVAILABLE_DAYS_LEFT"])
            )
        ).sum()
    )

    if at_risk_df.empty and tight_df.empty:
        embed.add_field(
            name="✅ All clear",
            value="Every active discipline is on pace to hit its weekly target.",
            inline=False,
        )
        embed.set_footer(text=f"On pace: {on_pace_count} | Tracked: {len(insight_df)}")
        return embed

    if not at_risk_df.empty:
        sorted_at_risk = at_risk_df.sort_values(
            by=["REMAINING_THIS_WEEK", "FREQUENCY_PER_WEEK"], ascending=[False, False]
        )
        lines = []
        for _, row in sorted_at_risk.head(15).iterrows():
            target = int(row["FREQUENCY_PER_WEEK"])
            actual = int(row["COMPLETIONS_THIS_WEEK"])
            remaining = int(row["REMAINING_THIS_WEEK"])
            available = int(row["AVAILABLE_DAYS_LEFT"])
            short_by = remaining - available
            lines.append(
                f"• **{row['TASK']}** ({row['CATAGORY']}): {actual}/{target} — needs {remaining} more in {available} day(s) "
                f"(short by {short_by})"
            )
        embed.add_field(
            name=f"❌ At Risk ({len(at_risk_df)})",
            value="\n".join(lines) if lines else "—",
            inline=False,
        )

    if not tight_df.empty:
        sorted_tight = tight_df.sort_values(
            by=["REMAINING_THIS_WEEK", "FREQUENCY_PER_WEEK"], ascending=[False, False]
        )
        lines = []
        for _, row in sorted_tight.head(15).iterrows():
            target = int(row["FREQUENCY_PER_WEEK"])
            actual = int(row["COMPLETIONS_THIS_WEEK"])
            remaining = int(row["REMAINING_THIS_WEEK"])
            available = int(row["AVAILABLE_DAYS_LEFT"])
            lines.append(
                f"• **{row['TASK']}** ({row['CATAGORY']}): {actual}/{target} — must hit each of the next {available} day(s) "
                f"(needs {remaining})"
            )
        embed.add_field(
            name=f"⚠️ Tight ({len(tight_df)})",
            value="\n".join(lines) if lines else "—",
            inline=False,
        )

    embed.set_footer(
        text=(
            f"At risk: {len(at_risk_df)} | Tight: {len(tight_df)} | On pace: {on_pace_count} | "
            f"Tracked: {len(insight_df)}"
        )
    )
    return embed
