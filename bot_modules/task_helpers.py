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


# --- Edit / Delete Helpers ---

# Maps user-friendly field aliases (lowercased, normalized) -> dataframe column names.
EDITABLE_TASK_FIELDS = {
    "task_name": "TASK",
    "task": "TASK",
    "name": "TASK",
    "priority": "PRIORITY",
    "due_date": "DUE DATE",
    "due": "DUE DATE",
    "category": "CATAGORY",
    "catagory": "CATAGORY",
    "group": "GROUP",
    "subgroup": "SUB-GROUP",
    "sub_group": "SUB-GROUP",
    "sub-group": "SUB-GROUP",
    "link": "RELEVANT LINK",
    "relevant_link": "RELEVANT LINK",
    "status": "STATUS",
    "estimated_time": "ESTIMATED TIME",
    "estimate": "ESTIMATED TIME",
}

VALID_STATUS_VALUES = ["Not Started", "In Progress", "Pending", "Blocked", "Hiatus", "Completed"]


def get_open_tasks_sorted(to_do_list_df):
    """Returns the open-task dataframe in the same sort order shown in `to_do_list`."""
    filtered = to_do_list_df[to_do_list_df["STATUS"] != "Completed"]
    return filtered.sort_values(by=["PRIORITY", "DUE DATE"], ascending=[False, True])


def resolve_task_index_from_position(to_do_list_df, position_1_based):
    """Translate a 1-based id (as shown to the user) into the underlying dataframe index.

    Returns (df_index, row) or (None, None) if out of range.
    """
    sorted_open = get_open_tasks_sorted(to_do_list_df)
    pos = int(position_1_based) - 1
    if pos < 0 or pos >= len(sorted_open):
        return None, None
    return sorted_open.index[pos], sorted_open.iloc[pos]


def parse_field_value_pairs(raw):
    """Parse 'field=value field2="quoted value"' into a dict.

    Uses shlex so multi-word values can be quoted. Returns dict of {field_lower: value_str}.
    Raises ValueError on a token without '='.
    """
    import shlex

    pairs = {}
    if not raw:
        return pairs

    try:
        tokens = shlex.split(raw)
    except ValueError as exc:
        raise ValueError(f"Could not parse arguments ({exc}). Try quoting values with spaces.")

    # Allow 'field = value' separated by spaces by re-joining and re-splitting on '='.
    # First pass: simple key=value tokens.
    for tok in tokens:
        if "=" not in tok:
            raise ValueError(f"'{tok}' is not in field=value form.")
        key, _, value = tok.partition("=")
        pairs[key.strip().lower()] = value
    return pairs


def coerce_task_field_value(field_alias, raw_value):
    """Convert a user-supplied string into the right dtype for the given column.

    Returns the coerced value. Raises ValueError on invalid input.
    """
    column = EDITABLE_TASK_FIELDS.get(field_alias.lower())
    if column is None:
        raise ValueError(f"Unknown field '{field_alias}'. Allowed: {', '.join(sorted(set(EDITABLE_TASK_FIELDS)))}")

    value = raw_value
    if isinstance(value, str):
        value = value.strip()

    # Treat explicit "none"/"" as clearing the value where applicable.
    if isinstance(value, str) and value.lower() in ("none", "null", ""):
        cleared = True
    else:
        cleared = False

    if column == "PRIORITY":
        try:
            return int(value)
        except (TypeError, ValueError):
            raise ValueError("priority must be an integer (1-10).")

    if column == "DUE DATE":
        if cleared:
            return pd.NaT
        normalized = normalize_due_date(value)
        parsed = pd.to_datetime(normalized, errors="coerce")
        if pd.isna(parsed):
            raise ValueError("due_date must be today/tmw/wk or YYYYMMDD.")
        return parsed

    if column == "ESTIMATED TIME":
        if cleared:
            return None
        try:
            return float(value)
        except (TypeError, ValueError):
            raise ValueError("estimated_time must be a number (hours).")

    if column == "STATUS":
        match = next((s for s in VALID_STATUS_VALUES if s.lower() == str(value).lower()), None)
        if match is None:
            raise ValueError(f"status must be one of: {', '.join(VALID_STATUS_VALUES)}")
        return match

    # Free-text columns: TASK, CATAGORY, GROUP, SUB-GROUP, RELEVANT LINK
    if cleared and column != "TASK":
        return None
    if column == "TASK" and cleared:
        raise ValueError("task_name cannot be blank.")
    return value


def apply_task_field_updates(to_do_list_df, df_index, field_value_pairs):
    """Apply a dict of {field_alias: raw_value} to the row at df_index.

    Returns a list of (column, coerced_value) actually applied.
    """
    applied = []
    for field_alias, raw_value in field_value_pairs.items():
        column = EDITABLE_TASK_FIELDS.get(field_alias.lower())
        if column is None:
            raise ValueError(f"Unknown field '{field_alias}'.")
        coerced = coerce_task_field_value(field_alias, raw_value)
        # Categorical columns (CATAGORY, STATUS) need careful assignment.
        if isinstance(to_do_list_df[column].dtype, pd.CategoricalDtype):
            existing_cats = list(to_do_list_df[column].cat.categories)
            if coerced not in existing_cats and coerced is not None and not (isinstance(coerced, float) and pd.isna(coerced)):
                to_do_list_df[column] = to_do_list_df[column].cat.add_categories([coerced])
        to_do_list_df.at[df_index, column] = coerced
        applied.append((column, coerced))
    return applied


# --- Search / Filter ---

# Maps user-facing filter keys to dataframe columns. None means "not a column" (special handling).
FILTERABLE_TASK_FIELDS = {
    "task": "TASK",
    "name": "TASK",
    "category": "CATAGORY",
    "catagory": "CATAGORY",
    "group": "GROUP",
    "subgroup": "SUB-GROUP",
    "sub_group": "SUB-GROUP",
    "sub-group": "SUB-GROUP",
    "link": "RELEVANT LINK",
    "priority": "PRIORITY",
    "status": "STATUS",
    "due": "DUE DATE",
    "due_date": "DUE DATE",
    "include": None,  # special: include:completed
}


def _parse_priority_token(expr):
    """Return a callable f(value) -> bool for a priority filter expression."""
    expr = expr.strip()
    for op in (">=", "<=", ">", "<", "="):
        if expr.startswith(op):
            try:
                threshold = int(expr[len(op):])
            except ValueError:
                raise ValueError(f"priority value after '{op}' must be an integer.")
            if op == ">=":
                return lambda v, t=threshold: v >= t
            if op == "<=":
                return lambda v, t=threshold: v <= t
            if op == ">":
                return lambda v, t=threshold: v > t
            if op == "<":
                return lambda v, t=threshold: v < t
            return lambda v, t=threshold: v == t
    try:
        threshold = int(expr)
    except ValueError:
        raise ValueError("priority must be an integer or use one of >= <= > < =.")
    return lambda v, t=threshold: v == t


def _parse_due_token(expr):
    """Return a callable f(due_value) -> bool for a due-date filter expression."""
    import datetime as _dt

    expr = expr.strip().lower()
    today = pd.to_datetime(_dt.datetime.now().date()).normalize()

    if expr in ("none", "null", ""):
        return lambda v: pd.isna(pd.to_datetime(v, errors="coerce"))
    if expr == "any":
        return lambda v: not pd.isna(pd.to_datetime(v, errors="coerce"))
    if expr in ("today", "td"):
        return lambda v: pd.to_datetime(v, errors="coerce").normalize() == today if not pd.isna(pd.to_datetime(v, errors="coerce")) else False
    if expr in ("tomorrow", "tmw"):
        tmw = today + pd.Timedelta(days=1)
        return lambda v: pd.to_datetime(v, errors="coerce").normalize() == tmw if not pd.isna(pd.to_datetime(v, errors="coerce")) else False
    if expr in ("week", "wk"):
        week_end = today + pd.Timedelta(days=7)
        def in_week(v):
            parsed = pd.to_datetime(v, errors="coerce")
            if pd.isna(parsed):
                return False
            d = parsed.normalize()
            return today <= d <= week_end
        return in_week
    if expr == "overdue":
        def is_overdue(v):
            parsed = pd.to_datetime(v, errors="coerce")
            if pd.isna(parsed):
                return False
            return parsed.normalize() < today
        return is_overdue

    for op in (">=", "<=", ">", "<", "="):
        if expr.startswith(op):
            try:
                threshold = pd.to_datetime(expr[len(op):]).normalize()
            except Exception:
                raise ValueError(f"due value after '{op}' must be YYYYMMDD.")
            if op == ">=":
                return lambda v, t=threshold: (not pd.isna(pd.to_datetime(v, errors="coerce"))) and pd.to_datetime(v).normalize() >= t
            if op == "<=":
                return lambda v, t=threshold: (not pd.isna(pd.to_datetime(v, errors="coerce"))) and pd.to_datetime(v).normalize() <= t
            if op == ">":
                return lambda v, t=threshold: (not pd.isna(pd.to_datetime(v, errors="coerce"))) and pd.to_datetime(v).normalize() > t
            if op == "<":
                return lambda v, t=threshold: (not pd.isna(pd.to_datetime(v, errors="coerce"))) and pd.to_datetime(v).normalize() < t
            return lambda v, t=threshold: (not pd.isna(pd.to_datetime(v, errors="coerce"))) and pd.to_datetime(v).normalize() == t

    try:
        target = pd.to_datetime(expr).normalize()
    except Exception:
        raise ValueError("due must be today/tmw/wk/overdue/none/any, or YYYYMMDD with optional >= <= > < =.")
    return lambda v, t=target: (not pd.isna(pd.to_datetime(v, errors="coerce"))) and pd.to_datetime(v).normalize() == t


def _parse_link_token(expr):
    expr = expr.strip().lower()
    if expr in ("none", "null", "no"):
        return lambda v: (v is None) or pd.isna(v) or str(v).strip().lower() in ("", "none", "nan")
    if expr in ("any", "has", "yes"):
        return lambda v: (v is not None) and (not pd.isna(v)) and str(v).strip().lower() not in ("", "none", "nan")
    needle = expr
    return lambda v: needle in str(v).lower() if v is not None and not pd.isna(v) else False


def parse_task_filter_tokens(raw):
    """Parse 'field:expr field:expr ...' into a list of (field_alias_lower, expr_str).

    Uses shlex so values can be quoted. Raises ValueError on malformed tokens.
    """
    import shlex

    if not raw:
        return []

    try:
        tokens = shlex.split(raw)
    except ValueError as exc:
        raise ValueError(f"Could not parse filters ({exc}). Try quoting values with spaces.")

    parsed = []
    for tok in tokens:
        if ":" not in tok:
            raise ValueError(f"'{tok}' is not in field:value form.")
        key, _, value = tok.partition(":")
        parsed.append((key.strip().lower(), value))
    return parsed


def filter_tasks(to_do_list_df, filter_tokens):
    """Apply a list of (field, expr) filters to a to-do dataframe.

    By default excludes Completed rows; pass ('include', 'completed') to include them.
    Returns the filtered dataframe in the same sort order as the to-do list view.
    """
    include_completed = False
    column_filters = []
    for field, expr in filter_tokens:
        if field not in FILTERABLE_TASK_FIELDS:
            raise ValueError(f"Unknown filter field '{field}'. Allowed: {', '.join(sorted(set(FILTERABLE_TASK_FIELDS)))}")
        if field == "include":
            if expr.strip().lower() == "completed":
                include_completed = True
                continue
            raise ValueError("include: only supports 'completed'.")
        column_filters.append((FILTERABLE_TASK_FIELDS[field], field, expr))

    df = to_do_list_df.copy()
    if not include_completed:
        df = df[df["STATUS"] != "Completed"]

    for column, field_alias, expr in column_filters:
        if column == "PRIORITY":
            predicate = _parse_priority_token(expr)
            numeric = pd.to_numeric(df[column], errors="coerce")
            df = df[numeric.apply(lambda v: False if pd.isna(v) else predicate(int(v)))]
        elif column == "DUE DATE":
            predicate = _parse_due_token(expr)
            df = df[df[column].apply(predicate)]
        elif column == "RELEVANT LINK":
            predicate = _parse_link_token(expr)
            df = df[df[column].apply(predicate)]
        elif column == "STATUS":
            needle = expr.strip().lower()
            df = df[df[column].astype(str).str.lower().str.contains(needle, na=False)]
        else:
            # Generic substring match on string columns.
            needle = expr.strip().lower()
            df = df[df[column].astype(str).str.lower().str.contains(needle, na=False)]

    return df.sort_values(by=["PRIORITY", "DUE DATE"], ascending=[False, True])
