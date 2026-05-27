"""Follow-up task helpers.

When a trigger task is completed, automatically create one or more follow-up
tasks in the main to-do list (e.g. 'Do Dishes' -> 'Put up Dishes').

Mappings live in a separate pickle so the to-do dataframe stays unchanged.
"""
import datetime
import os

import pandas as pd

from .bot_config import path_for_follow_up_tasks, path_for_to_do_list
from .task_helpers import build_tracker_row, normalize_due_date


FOLLOW_UP_COLUMNS = [
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


def _empty_follow_up_df():
    return pd.DataFrame(columns=FOLLOW_UP_COLUMNS)


def load_follow_ups():
    """Return the follow-up mapping dataframe (creating an empty one if missing)."""
    if not os.path.exists(path_for_follow_up_tasks):
        return _empty_follow_up_df()
    try:
        df = pd.read_pickle(path_for_follow_up_tasks)
    except Exception:
        return _empty_follow_up_df()
    # Ensure all expected columns exist (forward-compatible).
    for col in FOLLOW_UP_COLUMNS:
        if col not in df.columns:
            df[col] = None
    return df.reset_index(drop=True)


def save_follow_ups(df):
    df = df.reset_index(drop=True)
    df.to_pickle(path_for_follow_up_tasks)


def add_follow_up(
    trigger_task,
    follow_up_task,
    catagory=None,
    group=None,
    subgroup=None,
    relevant_link=None,
    priority=1,
    estimated_time=None,
    due_offset_days=None,
):
    """Append a new follow-up mapping and persist. Returns the new row as a Series."""
    df = load_follow_ups()

    parsed_due_offset = None
    if due_offset_days not in (None, "", "None"):
        try:
            parsed_due_offset = int(due_offset_days)
        except (TypeError, ValueError):
            raise ValueError("due_offset_days must be an integer (days from completion).")

    try:
        parsed_priority = int(priority) if priority is not None else 1
    except (TypeError, ValueError):
        raise ValueError("priority must be an integer between 1 and 10.")

    parsed_estimated_time = None
    if estimated_time not in (None, "", "None"):
        try:
            parsed_estimated_time = float(estimated_time)
        except (TypeError, ValueError):
            raise ValueError("estimated_time must be numeric (hours).")

    new_row = {
        "TRIGGER_TASK": str(trigger_task).strip(),
        "FOLLOW_UP_TASK": str(follow_up_task).strip(),
        "CATAGORY": catagory,
        "GROUP": group,
        "SUBGROUP": subgroup,
        "RELEVANT_LINK": relevant_link,
        "PRIORITY": parsed_priority,
        "ESTIMATED_TIME": parsed_estimated_time,
        "DUE_OFFSET_DAYS": parsed_due_offset,
        "CREATED": pd.to_datetime(datetime.datetime.now().isoformat(" ", "seconds")),
    }
    df = pd.concat([df, pd.DataFrame([new_row])], ignore_index=True)
    save_follow_ups(df)
    return df.iloc[-1]


def delete_follow_up(position):
    """Delete a mapping by 1-based position as shown in `follow_ups` list. Returns the removed row."""
    df = load_follow_ups()
    if df.empty:
        raise ValueError("No follow-up mappings exist.")
    if position < 1 or position > len(df):
        raise ValueError(f"No follow-up mapping at position {position}. There are {len(df)} mapping(s).")
    removed = df.iloc[position - 1].copy()
    df = df.drop(index=df.index[position - 1]).reset_index(drop=True)
    save_follow_ups(df)
    return removed


def get_follow_ups_for(trigger_task_name):
    """Return mappings whose trigger matches the given task name (case-insensitive)."""
    df = load_follow_ups()
    if df.empty:
        return df
    target = str(trigger_task_name).strip().lower()
    mask = df["TRIGGER_TASK"].astype(str).str.strip().str.lower() == target
    return df[mask].copy()


def create_follow_up_tasks_for(trigger_task_name, source_row=None):
    """Create new to-do list rows for every mapping triggered by `trigger_task_name`.

    Falls back to fields from the just-completed `source_row` when a mapping does not
    specify them (so a follow-up inherits category/group from the original task).
    Returns a list of created task name strings.
    """
    mappings = get_follow_ups_for(trigger_task_name)
    if mappings.empty:
        return []

    try:
        to_do_list_df = pd.read_pickle(path_for_to_do_list)
    except FileNotFoundError:
        to_do_list_df = pd.DataFrame()

    created_names = []
    open_mask_col = (
        to_do_list_df["STATUS"].astype(str) != "Completed"
        if "STATUS" in to_do_list_df.columns
        else pd.Series([], dtype=bool)
    )
    open_task_names = (
        to_do_list_df.loc[open_mask_col, "TASK"].astype(str).str.strip().str.lower().tolist()
        if "TASK" in to_do_list_df.columns
        else []
    )

    for _, mapping in mappings.iterrows():
        follow_up_name = str(mapping["FOLLOW_UP_TASK"]).strip()
        if not follow_up_name:
            continue

        # Skip if an identical open follow-up already exists (avoid duplicates if user
        # completes the trigger task multiple times in quick succession).
        if follow_up_name.lower() in open_task_names:
            continue

        # Resolve fields with fallback to the completed source task.
        def _pick(mapping_value, source_key, default=None):
            if mapping_value is not None and not (isinstance(mapping_value, float) and pd.isna(mapping_value)):
                return mapping_value
            if source_row is not None and source_key in source_row.index:
                val = source_row.get(source_key)
                if val is not None and not (isinstance(val, float) and pd.isna(val)):
                    return val
            return default

        catagory = _pick(mapping.get("CATAGORY"), "CATAGORY", default="General")
        group = _pick(mapping.get("GROUP"), "GROUP")
        subgroup = _pick(mapping.get("SUBGROUP"), "SUB-GROUP")
        link = _pick(mapping.get("RELEVANT_LINK"), "RELEVANT LINK")
        estimated_time = mapping.get("ESTIMATED_TIME")
        if estimated_time is None or (isinstance(estimated_time, float) and pd.isna(estimated_time)):
            estimated_time = None

        priority = mapping.get("PRIORITY")
        try:
            priority = int(priority) if priority is not None and not pd.isna(priority) else 1
        except (TypeError, ValueError):
            priority = 1

        due_date = None
        offset = mapping.get("DUE_OFFSET_DAYS")
        if offset is not None and not (isinstance(offset, float) and pd.isna(offset)):
            try:
                due_date = datetime.datetime.now().date() + datetime.timedelta(days=int(offset))
            except (TypeError, ValueError):
                due_date = None

        new_row = build_tracker_row(
            task_name=follow_up_name,
            catagory=str(catagory) if catagory is not None else "General",
            group=group,
            subgroup=subgroup,
            relevant_link=link,
            recurring=False,
            recurring_interval=None,
            due_date=normalize_due_date(due_date) if due_date else None,
            priority=priority,
            estimated_time=estimated_time,
        )
        to_do_list_df = pd.concat([new_row, to_do_list_df], ignore_index=True)
        created_names.append(follow_up_name)
        open_task_names.append(follow_up_name.lower())

    if created_names:
        to_do_list_df.to_pickle(path_for_to_do_list)

    return created_names
