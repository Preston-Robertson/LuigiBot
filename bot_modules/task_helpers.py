"""To-do list helpers — row builder, date normalization, series builder, task embeds."""
import datetime

import discord
import pandas as pd

from .bot_config import path_for_to_do_list


# --- Row Builder ---

def build_tracker_row(
    task_name,
    catagory,
    group=None,
    subgroup=None,
    relevant_link=None,
    recurring=False,
    recurring_interval=None,
    due_date=None,
    priority=1,
    estimated_time=None,
):
    return pd.DataFrame(
        {
            "TASK": task_name,
            "TASK CREATION": pd.to_datetime(datetime.datetime.now().isoformat(' ', 'seconds')),
            "CATAGORY": pd.Categorical([catagory]),
            "GROUP": group,
            "SUB-GROUP": subgroup,
            "RELEVANT LINK": relevant_link,
            "RECURRING": recurring,
            "RECURRING INTERVAL": recurring_interval,
            "DUE DATE": pd.to_datetime(due_date),
            "PRIORITY": priority,
            "STATUS": pd.Categorical(
                ["Not Started"],
                categories=[
                    "Not Started",
                    "In Progress",
                    "Pending",
                    "Blocked",
                    "Hiatus",
                    "Completed",
                ],
                ordered=True,
            ),
            "START TIME": None,
            "ESTIMATED TIME": estimated_time,
            "LOGGED HOURS": 0,
            "COMPLETED": False,
            "COMPLETED TIME": None,
        }
    )


# --- Date Normalization ---

def normalize_due_date(due_date):
    if due_date == "Today" or due_date == "today" or due_date == "td" or due_date == "TD":
        return datetime.datetime.now().date()
    if due_date == "Tomorrow" or due_date == "tomorrow" or due_date == "tmw" or due_date == "TMw":
        return datetime.datetime.now().date() + datetime.timedelta(days=1)
    if due_date == "Week" or due_date == "week" or due_date == "WK" or due_date == "wk":
        return datetime.datetime.now().date() + datetime.timedelta(weeks=1)
    return due_date


# --- Series Builder ---

def build_completed_task_series(to_do_list_df, end_date, days=7):
    date_index = pd.date_range(end=pd.to_datetime(end_date).normalize(), periods=days, freq="D")

    if to_do_list_df.empty or "COMPLETED TIME" not in to_do_list_df.columns:
        return pd.Series([0] * len(date_index), index=date_index, dtype="int64")

    completed_times = pd.to_datetime(to_do_list_df["COMPLETED TIME"], errors="coerce").dt.normalize()
    completed_times = completed_times.dropna()

    if completed_times.empty:
        return pd.Series([0] * len(date_index), index=date_index, dtype="int64")

    completion_counts = completed_times.value_counts().sort_index()
    return completion_counts.reindex(date_index, fill_value=0).astype(int)


# --- Task Utilities ---

def get_open_task_mask(to_do_list_df, task_name):
    return (to_do_list_df["TASK"] == task_name) & (to_do_list_df["STATUS"] != "Completed")


def load_latest_task_row(task_name):
    to_do_list_df = pd.read_pickle(path_for_to_do_list)
    task_df = to_do_list_df[to_do_list_df["TASK"] == task_name].copy()
    if task_df.empty:
        return None

    task_df["COMPLETED TIME SORT"] = pd.to_datetime(task_df["COMPLETED TIME"], errors="coerce")
    task_df["TASK CREATION SORT"] = pd.to_datetime(task_df["TASK CREATION"], errors="coerce")
    task_df = task_df.sort_values(by=["COMPLETED TIME SORT", "TASK CREATION SORT"], ascending=[False, False])
    return task_df.iloc[0]


def pause_task_tracking(to_do_list_df, task_mask, now_timestamp):
    if task_mask.sum() == 0:
        return False

    current_status = str(to_do_list_df.loc[task_mask, "STATUS"].iloc[0])
    if current_status != "In Progress":
        return False

    start_time = pd.to_datetime(to_do_list_df.loc[task_mask, "START TIME"].iloc[0], errors="coerce")
    if pd.isna(start_time):
        return False

    existing_hours = pd.to_numeric(to_do_list_df.loc[task_mask, "LOGGED HOURS"], errors="coerce").fillna(0)
    additional_hours = round((now_timestamp - start_time).total_seconds() / 3600, 3)
    to_do_list_df.loc[task_mask, "LOGGED HOURS"] = existing_hours + additional_hours
    to_do_list_df.loc[task_mask, "START TIME"] = pd.NaT
    return True


# --- Embed Builders ---

def format_task_due_value(due_value):
    parsed_due = pd.to_datetime(due_value, errors="coerce")
    if pd.isna(parsed_due):
        return "No due date"
    return parsed_due.strftime("%m/%d/%Y %I:%M %p") if parsed_due.time() != datetime.time.min else parsed_due.strftime("%m/%d/%Y")


def build_task_detail_embed(row):
    embed = discord.Embed(title=str(row["TASK"]), color=0x00FF00)
    priority = row["PRIORITY"]
    task_creation = row["TASK CREATION"]
    task_completion = row.get("COMPLETED TIME")
    catagory = row.get("CATAGORY")
    group = row.get("GROUP")
    subgroup = row.get("SUB-GROUP")
    starttime = row.get("START TIME")
    estimated_time = row.get("ESTIMATED TIME")
    logged_hours = row.get("LOGGED HOURS")
    status = row["STATUS"]
    due = format_task_due_value(row.get("DUE DATE"))
    link = row.get("RELEVANT LINK")
    link_md = f"[LINK]({link})" if link and str(link) not in ("None", "nan") else "No link"

    lines = [
        f"Priority: {priority}",
        f"Due: {due}",
    ]

    if catagory is not None:
        lines.append(f"Category: {catagory}")
    if group is not None:
        lines.append(f"Group: {group}")
    lines.extend(
        [
            f"Subgroup: {subgroup}",
            f"Start Time: {starttime}",
            f"Estimated Time: {estimated_time}",
            f"Logged Hours: {logged_hours}",
            f"Task Created: {task_creation}",
        ]
    )
    if not pd.isna(pd.to_datetime(task_completion, errors="coerce")):
        lines.append(f"Task Completed: {task_completion}")
    lines.append(link_md)

    embed.add_field(name=status, value="\n".join(lines), inline=False)
    return embed
