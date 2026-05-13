#%%
# IMPORTING LIBRARIES

# Discord
import asyncio
import discord
from discord.ext import commands, tasks

# General
import json
import os
import datetime
import pytz
from io import BytesIO

# For Slash Commands
from discord import app_commands
from discord import interactions

# For Data 
import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt
import pandas as pd
import warnings
warnings.simplefilter(action='ignore', category=FutureWarning)

from required_functions import extract_task_name
# test push



#%%
# CONFIG // INTIALIZING

# Loading BOT secrets
with open(f'config.json') as f:
    config = json.load(f)


# Set-up the TCGbothelper channel and command
command_prefix = "!L "
bot = commands.Bot(command_prefix=command_prefix, intents=discord.Intents.all())

channel_id = config['Channel_ID']
user_id = config['User_ID']

path_for_to_do_list = "to_do_list\\to_do_list.pkl"
path_for_recurring_tasks = "to_do_list\\recurring_tasks.pkl"
path_for_discipline_list = config.get("Discipline_List_Path", "to_do_list\\discipline_list.pkl")
path_for_discipline_completion_log = config.get("Discipline_Completion_Log_Path", "to_do_list\\discipline_completion_log.pkl")

discipline_delete_after_seconds = int(config.get("Discipline_Delete_After_Seconds", 7200))
discipline_daily_hour = int(config.get("Discipline_Daily_Hour", 23))
discipline_daily_minute = int(config.get("Discipline_Daily_Minute", 15))

last_discipline_daily_date = None
last_todo_visual_date = None
last_todo_weekly_visual_date = None


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


def normalize_due_date(due_date):
    if due_date == "Today" or due_date == "today" or due_date == "td" or due_date == "TD":
        return datetime.datetime.now().date()
    if due_date == "Tomorrow" or due_date == "tomorrow" or due_date == "tmw" or due_date == "TMw":
        return datetime.datetime.now().date() + datetime.timedelta(days=1)
    if due_date == "Week" or due_date == "week" or due_date == "WK" or due_date == "wk":
        return datetime.datetime.now().date() + datetime.timedelta(weeks=1)
    return due_date


def build_discipline_row(task_name, catagory, frequency_per_week):
    return pd.DataFrame(
        {
            "TASK": [task_name],
            "CATAGORY": [catagory],
            "FREQUENCY_PER_WEEK": [int(frequency_per_week)],
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


def ensure_discipline_dataframe_exists():
    os.makedirs(os.path.dirname(path_for_discipline_list), exist_ok=True)

    expected_cols = ["TASK", "CATAGORY", "FREQUENCY_PER_WEEK"]

    if os.path.exists(path_for_discipline_list):
        try:
            existing_df = pd.read_pickle(path_for_discipline_list)
            if set(expected_cols).issubset(existing_df.columns):
                existing_df = existing_df[expected_cols].copy()
                existing_df["FREQUENCY_PER_WEEK"] = pd.to_numeric(existing_df["FREQUENCY_PER_WEEK"], errors="coerce").fillna(1).astype(int)
                existing_df["FREQUENCY_PER_WEEK"] = existing_df["FREQUENCY_PER_WEEK"].clip(lower=1, upper=7)
                existing_df.to_pickle(path_for_discipline_list)
                return

            migrated_df = pd.DataFrame(
                {
                    "TASK": existing_df["TASK"].astype(str) if "TASK" in existing_df.columns else pd.Series(dtype="object"),
                    "CATAGORY": existing_df["CATAGORY"].astype(str) if "CATAGORY" in existing_df.columns else "Discipline",
                    "FREQUENCY_PER_WEEK": 1,
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


def get_discipline_channel():
    discipline_channel_id = config.get("Channel_ID_discipline")
    if discipline_channel_id:
        return bot.get_channel(discipline_channel_id)
    if config.get("Channel_ID_to_do"):
        return bot.get_channel(config["Channel_ID_to_do"])
    return bot.get_channel(channel_id)


def get_todo_channel():
    to_do_channel_id = config.get("Channel_ID_to_do")
    if to_do_channel_id:
        return bot.get_channel(to_do_channel_id)
    return bot.get_channel(channel_id)


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


def render_completed_task_bar_chart(completion_series, chart_title, subtitle=None, highlight_index=None):
    labels = [dt.strftime("%a\n%m/%d") for dt in completion_series.index]
    values = completion_series.values.tolist()

    fig, ax = plt.subplots(figsize=(9, 4.5), dpi=150)
    bar_colors = ["#8FB8FF"] * len(values)

    if highlight_index is not None and 0 <= highlight_index < len(bar_colors):
        bar_colors[highlight_index] = "#2E6DFF"

    bars = ax.bar(range(len(values)), values, color=bar_colors, width=0.7)

    ax.set_title(chart_title, fontsize=14, fontweight="bold", pad=12)
    if subtitle:
        ax.text(0.5, 1.01, subtitle, ha="center", va="bottom", transform=ax.transAxes, fontsize=10, color="#444444")

    ax.set_xticks(range(len(labels)))
    ax.set_xticklabels(labels, fontsize=9)
    ax.set_ylabel("Tasks Completed", fontsize=10)
    ax.grid(axis="y", linestyle="--", alpha=0.25)
    ax.set_axisbelow(True)

    for bar in bars:
        height = int(bar.get_height())
        ax.annotate(
            str(height),
            xy=(bar.get_x() + bar.get_width() / 2, height),
            xytext=(0, 3),
            textcoords="offset points",
            ha="center",
            va="bottom",
            fontsize=9,
            color="#1C1C1C",
        )

    for spine in ["top", "right"]:
        ax.spines[spine].set_visible(False)

    fig.tight_layout()
    image_buffer = BytesIO()
    fig.savefig(image_buffer, format="png", bbox_inches="tight")
    plt.close(fig)
    image_buffer.seek(0)
    return image_buffer


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


def render_discipline_daily_goal_status_chart(status_df, chart_title, subtitle=None):
    labels = status_df["TASK"].astype(str).tolist()
    values = status_df["GOAL_MET_BINARY"].astype(int).tolist()

    fig, ax = plt.subplots(figsize=(max(10, len(labels) * 0.75), 4.8), dpi=150)

    x_positions = range(len(labels))
    for idx, (_, row) in enumerate(status_df.iterrows()):
        status_code = row["STATUS_CODE"]
        if status_code == "met_today":
            ax.bar(idx, 1, color="#2E86DE", width=0.65)
        elif status_code == "met_before_today":
            ax.bar(idx, 1, color="#27AE60", width=0.65)
        elif status_code == "done_today_not_met":
            ax.bar(idx, 0.15, color="#F39C12", width=0.65)
        else:
            ax.bar(idx, 0.02, facecolor="none", edgecolor="#95A5A6", linewidth=1.5, width=0.65)

    ax.set_ylim(0, 1.15)
    ax.set_xticks(list(x_positions))
    ax.set_xticklabels(labels, rotation=30, ha="right", fontsize=9)
    ax.set_yticks([0, 1])
    ax.set_yticklabels(["Need", "Met"], fontsize=9)
    ax.set_ylabel("Weekly Goal Status", fontsize=10)
    ax.set_title(chart_title, fontsize=14, fontweight="bold", pad=12)

    if subtitle:
        ax.text(0.5, 1.01, subtitle, ha="center", va="bottom", transform=ax.transAxes, fontsize=10, color="#444444")

    ax.grid(axis="y", linestyle="--", alpha=0.2)
    ax.set_axisbelow(True)
    for spine in ["top", "right"]:
        ax.spines[spine].set_visible(False)

    legend_handles = [
        plt.Rectangle((0, 0), 1, 1, color="#2E86DE", label="Reached Goal Today"),
        plt.Rectangle((0, 0), 1, 1, color="#27AE60", label="Goal Already Met"),
        plt.Rectangle((0, 0), 1, 1, color="#F39C12", label="Done Today (Not Met Yet)"),
        plt.Rectangle((0, 0), 1, 1, facecolor="none", edgecolor="#95A5A6", label="Needs Completion"),
    ]
    ax.legend(handles=legend_handles, loc="upper left", bbox_to_anchor=(1.01, 1.0), fontsize=8)

    fig.tight_layout()
    image_buffer = BytesIO()
    fig.savefig(image_buffer, format="png", bbox_inches="tight")
    plt.close(fig)
    image_buffer.seek(0)
    return image_buffer


def render_discipline_weekly_progress_chart(report_df, chart_title, subtitle=None):
    labels = report_df["TASK"].astype(str).tolist()
    actual = report_df["COMPLETIONS_THIS_WEEK"].astype(int).tolist()
    target = report_df["FREQUENCY_PER_WEEK"].astype(int).tolist()

    fig, ax = plt.subplots(figsize=(max(10, len(labels) * 0.75), 4.8), dpi=150)
    x_positions = list(range(len(labels)))
    width = 0.38

    bars_target = ax.bar([x - width / 2 for x in x_positions], target, width=width, color="#D5DBDB", label="Target")
    actual_colors = ["#27AE60" if a >= t else "#E74C3C" for a, t in zip(actual, target)]
    bars_actual = ax.bar([x + width / 2 for x in x_positions], actual, width=width, color=actual_colors, label="Actual")

    ax.set_xticks(x_positions)
    ax.set_xticklabels(labels, rotation=30, ha="right", fontsize=9)
    ax.set_ylabel("Days Completed This Week", fontsize=10)
    ax.set_title(chart_title, fontsize=14, fontweight="bold", pad=12)

    if subtitle:
        ax.text(0.5, 1.01, subtitle, ha="center", va="bottom", transform=ax.transAxes, fontsize=10, color="#444444")

    max_y = max(target + actual) if (target or actual) else 1
    ax.set_ylim(0, max_y + 1)
    ax.grid(axis="y", linestyle="--", alpha=0.2)
    ax.set_axisbelow(True)
    ax.legend(fontsize=9)

    for bars in [bars_target, bars_actual]:
        for bar in bars:
            height = int(bar.get_height())
            ax.annotate(
                str(height),
                xy=(bar.get_x() + bar.get_width() / 2, height),
                xytext=(0, 3),
                textcoords="offset points",
                ha="center",
                va="bottom",
                fontsize=8,
            )

    for spine in ["top", "right"]:
        ax.spines[spine].set_visible(False)

    fig.tight_layout()
    image_buffer = BytesIO()
    fig.savefig(image_buffer, format="png", bbox_inches="tight")
    plt.close(fig)
    image_buffer.seek(0)
    return image_buffer


def get_active_discipline_df(discipline_list_df):
    filtered_df = discipline_list_df.copy()

    if filtered_df.empty:
        return filtered_df

    return filtered_df.sort_values(by=["FREQUENCY_PER_WEEK", "TASK"], ascending=[False, True])


def get_task_completed_today(task_name, completion_log_df, target_date):
    target_date_normalized = pd.to_datetime(target_date).normalize()
    matching = completion_log_df[
        (completion_log_df["TASK"].astype(str).str.lower() == str(task_name).strip().lower())
        & (completion_log_df["COMPLETED_DATE"] == target_date_normalized)
    ]
    return not matching.empty


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
    embed.set_footer(text=f"Pending: {pending_count} | Logged: {logged_count} | Use {command_prefix}log_discipline_completion to log")

    return embed

# --- Button Views ---

class TaskSelectButton(discord.ui.Button):
    def __init__(self, index):
        super().__init__(label=str(index + 1), style=discord.ButtonStyle.secondary)
        self.index = index

    async def callback(self, interaction: discord.Interaction):
        to_do_list_df = pd.read_pickle(path_for_to_do_list)
        filtered_df = to_do_list_df[to_do_list_df["STATUS"] != "Completed"]
        sorted_df = filtered_df.sort_values(by=["PRIORITY", "DUE DATE"], ascending=[False, True])
        if self.index >= len(sorted_df):
            await interaction.response.send_message("Task no longer exists.", ephemeral=True)
            return
        task_df = sorted_df.iloc[[self.index]]

        for _, row in task_df.astype(str).iterrows():
            task_name = row["TASK"]
            embed = discord.Embed(title=task_name, color=0x00FF00)
            priority = row["PRIORITY"]
            task_creation = row["TASK CREATION"]
            subgroup = row["SUB-GROUP"]
            starttime = row["START TIME"]
            estimated_time = row["ESTIMATED TIME"]
            logged_hours = row["LOGGED HOURS"]
            status = row["STATUS"]
            due = row["DUE DATE"] if row["DUE DATE"] != "NaT" else "No due date"
            link = row["RELEVANT LINK"]
            link_md = f"[LINK]({link})" if link and link not in ("None", "nan") else "No link"
            value = f"""Priority: {priority}\nDue: {due}\nSubgroup: {subgroup}\nStart Time: {starttime}\nEstimated Time: {estimated_time}\nLogged Hours: {logged_hours}\nTask Created: {task_creation}\n{link_md}\n"""
            embed.add_field(name=status, value=value, inline=False)

        await interaction.response.send_message(embed=embed, view=TaskActionView(task_name))


class TaskSelectView(discord.ui.View):
    """Numbered buttons for selecting a task from the to-do list."""
    def __init__(self, task_count):
        super().__init__(timeout=60)
        for i in range(min(task_count, 9)):
            self.add_item(TaskSelectButton(index=i))


class TaskActionView(discord.ui.View):
    """Buttons to Complete, Start, or Pause a task."""
    def __init__(self, task_name):
        super().__init__(timeout=None)
        self.task_name = task_name

    @discord.ui.button(label="Complete", style=discord.ButtonStyle.success, emoji="✅")
    async def complete_task(self, interaction: discord.Interaction, button: discord.ui.Button):
        task_name = self.task_name
        to_do_list_df = pd.read_pickle(path_for_to_do_list)
        the_filter = (to_do_list_df["TASK"] == task_name) & (to_do_list_df["STATUS"] != "Completed")

        try:
            filtered_df = to_do_list_df[the_filter]
        except Exception as e:
            await interaction.response.send_message(f"Something went wrong: {e}", ephemeral=True)
            return

        to_do_list_df.loc[the_filter, "COMPLETED TIME"] = pd.to_datetime(datetime.datetime.now().isoformat(' ', 'seconds'))
        if pd.isna(to_do_list_df.loc[the_filter]["LOGGED HOURS"].iloc[0]) == False:
            time_delta = filtered_df["COMPLETED TIME"] - filtered_df["START TIME"] + pd.Timedelta(hours=filtered_df["LOGGED HOURS"].iloc[0])
            to_do_list_df.loc[the_filter, "LOGGED HOURS"].iloc[0] = time_delta
        else:
            time_delta = filtered_df["COMPLETED TIME"] - filtered_df["START TIME"]
            to_do_list_df.loc[the_filter, "LOGGED HOURS"].iloc[0] = time_delta

        to_do_list_df.loc[the_filter, "STATUS"] = "Completed"
        to_do_list_df.to_pickle(path_for_to_do_list)

        try:
            to_do_list_df = pd.read_pickle(path_for_to_do_list)
            task_df = to_do_list_df[to_do_list_df["TASK"] == task_name].sort_values(by=["COMPLETED TIME"], ascending=[False])

            for _, row in task_df.astype(str).iterrows():
                embed = discord.Embed(title=row["TASK"], color=0x00FF00)
                priority = row["PRIORITY"]
                task_creation = row["TASK CREATION"]
                task_completion = row["COMPLETED TIME"]
                catagory = row["CATAGORY"]
                group = row["GROUP"]
                subgroup = row["SUB-GROUP"]
                starttime = row["START TIME"]
                estimated_time = row["ESTIMATED TIME"]
                logged_hours = row["LOGGED HOURS"]
                status = row["STATUS"]
                due = row["DUE DATE"] if row["DUE DATE"] != "NaT" else "No due date"
                link = row["RELEVANT LINK"]
                link_md = f"[LINK]({link})" if link and link not in ("None", "nan") else "No link"
                value = f"""Priority: {priority}\nDue: {due}\n Category: {catagory}\nGroup: {group}\nSubgroup: {subgroup}\nStart Time: {starttime}\nEstimated Time: {estimated_time}\nLogged Hours: {logged_hours}\nTask Created: {task_creation}\nTask Completed: {task_completion}\n{link_md}\n"""
                embed.add_field(name=status, value=value, inline=False)

            await interaction.response.edit_message(embed=embed, view=None)
            msg = await interaction.original_response()
            await msg.delete(delay=60)

        except Exception as e:
            await interaction.response.send_message(f"Error completing task '{task_name}': {e}", ephemeral=True)

    @discord.ui.button(label="Start", style=discord.ButtonStyle.primary, emoji="▶️")
    async def start_task(self, interaction: discord.Interaction, button: discord.ui.Button):
        task_name = self.task_name
        to_do_list_df = pd.read_pickle(path_for_to_do_list)
        the_filter = (to_do_list_df["TASK"] == task_name) & (to_do_list_df["STATUS"] != "Completed")

        to_do_list_df.loc[the_filter, "START TIME"] = pd.to_datetime(datetime.datetime.now().isoformat(' ', 'seconds'))
        to_do_list_df.loc[the_filter, "STATUS"] = "In Progress"
        to_do_list_df.to_pickle(path_for_to_do_list)
        await interaction.response.edit_message(content=f"Updated '{task_name}' to 'In Progress'", embed=None, view=None)
        msg = await interaction.original_response()
        await msg.delete(delay=30)

    @discord.ui.button(label="Pause", style=discord.ButtonStyle.secondary, emoji="⏸️")
    async def pause_task(self, interaction: discord.Interaction, button: discord.ui.Button):
        task_name = self.task_name
        to_do_list_df = pd.read_pickle(path_for_to_do_list)
        the_filter = (to_do_list_df["TASK"] == task_name) & (to_do_list_df["STATUS"] != "Completed")

        if to_do_list_df.loc[the_filter, "STATUS"].iloc[0] == 'In Progress':
            now = datetime.datetime.now()
            start = to_do_list_df.loc[the_filter, "START TIME"].iloc[0]
            logged_hours = round((now - start).total_seconds() / 3600, 3)
            to_do_list_df.loc[the_filter, "LOGGED HOURS"] = to_do_list_df.loc[the_filter, "LOGGED HOURS"] + logged_hours

        to_do_list_df.loc[the_filter, "STATUS"] = "Hiatus"
        to_do_list_df.to_pickle(path_for_to_do_list)
        await interaction.response.edit_message(content=f"Updated '{task_name}' to 'Hiatus'", embed=None, view=None)
        msg = await interaction.original_response()
        await msg.delete(delay=30)


# --- Discipline Tracker Button Views ---

class DisciplineTaskButton(discord.ui.Button):
    def __init__(self, index, task_name):
        super().__init__(label=str(index + 1), style=discord.ButtonStyle.secondary)
        self.index = index
        self.task_name = task_name

    async def callback(self, interaction: discord.Interaction):
        ensure_discipline_dataframe_exists()
        ensure_discipline_completion_log_exists()

        today = pd.to_datetime(datetime.datetime.now().date()).normalize()
        completion_df = pd.read_pickle(path_for_discipline_completion_log)
        is_logged = get_task_completed_today(self.task_name, completion_df, today)

        if is_logged:
            completion_df_filtered = completion_df[
                ~((completion_df["TASK"].astype(str).str.lower() == str(self.task_name).strip().lower())
                  & (completion_df["COMPLETED_DATE"] == today))
            ]
            completion_df_filtered.to_pickle(path_for_discipline_completion_log)
            await interaction.response.send_message(
                f"✅ Marked '{self.task_name}' as incomplete for today.",
                ephemeral=True,
                delete_after=30,
            )
        else:
            discipline_df = pd.read_pickle(path_for_discipline_list)
            task_match = discipline_df[discipline_df["TASK"].astype(str).str.lower() == str(self.task_name).strip().lower()]
            if not task_match.empty:
                task_row = task_match.iloc[0]
                catagory = str(task_row["CATAGORY"])
                completion_row = build_discipline_completion_row(self.task_name, catagory, today)
                updated_df = pd.concat([completion_df, completion_row], ignore_index=True)
                updated_df.to_pickle(path_for_discipline_completion_log)
                await interaction.response.send_message(
                    f"✅ Logged '{self.task_name}' as completed for today.",
                    ephemeral=True,
                    delete_after=30,
                )
            else:
                await interaction.response.send_message(
                    f"❌ Task not found. Use {command_prefix}discipline_list to view tracked items.",
                    ephemeral=True,
                    delete_after=30,
                )


class DisciplineTaskView(discord.ui.View):
    """Numbered buttons for logging discipline task completions."""
    def __init__(self, pending_tasks):
        super().__init__(timeout=300)
        self.pending_tasks = pending_tasks
        for i, task_row in enumerate(pending_tasks):
            if i >= 9:
                break
            task_name = str(task_row["TASK"])
            self.add_item(DisciplineTaskButton(index=i, task_name=task_name))


# %%
# Bot Start-up Process

@bot.event
async def on_ready():
    #print("Hello World!")
    luigi_channel = bot.get_channel(channel_id)

    # Sync slash commands
    try: 
        # Try Syncing the bot commands from local python
        synced = await bot.tree.sync()
        print(f"Synced {len(synced)} command(s)")

    except Exception as e:
        print(f"Error syncing commands: {e}")
    
    ensure_discipline_dataframe_exists()
    ensure_discipline_completion_log_exists()
    send_daily_message.start()

    if luigi_channel:
        # Create a comprehensive command list embed
        embed = discord.Embed(
            title="🤖 LuigiBot Startup — Available Commands",
            description="All commands and their functions",
            color=0x1E90FF,
        )

        embed.add_field(
            name="📋 To-Do List Commands",
            value=(
                "`/hello` — Greeting test command\n"
                f"`/to_do_list` or `{command_prefix}to_do_list` — View active to-do items (sorted by priority & due date)\n"
                f"`/create_task` or `{command_prefix}create_task` — Create a new to-do task with metadata (priority, due date, estimated time, etc.)\n"
                f"`{command_prefix}to_do_completion_visual` — Post a 7-day completed-task bar chart to the to-do channel\n"
                f"`{command_prefix}to_do_weekly_visual [week_end]` — Post an end-of-week bar chart to the to-do channel (optional YYYYMMDD)\n"
            ),
            inline=False,
        )

        embed.add_field(
            name="🎯 Discipline Tracker Commands",
            value=(
                f"`{command_prefix}create_discipline_task` — Add a discipline item (task name, category, frequency/week 1-7)\n"
                f"`{command_prefix}discipline_list` — View all tracked discipline items\n"
                f"`{command_prefix}log_discipline_completion` — Log completion of a discipline task (for data collection)\n"
                f"`{command_prefix}today_completions` — View today's logged discipline completions (or any date)\n"
                f"`{command_prefix}weekly_discipline_summary` — Weekly progress report vs frequency targets\n"
                f"`{command_prefix}daily_discipline_visual` — Post today's discipline goal-status visual to the discipline channel\n"
                f"`{command_prefix}weekly_discipline_visual [week_start]` — Post weekly discipline progress visual to the discipline channel\n"
            ),
            inline=False,
        )

        embed.set_footer(text=f"Use slash commands or '{command_prefix}' prefix commands as listed above. Nightly reminders have interactive buttons!")

        await luigi_channel.send(embed=embed)
    else:
        print("Channel not found.")
    # Once bot start-up is done, it will send command list


#%%
# HELLO COMMAND
@bot.tree.command(name = "hello", description= "Typical test command")
async def hello(interaction: discord.Interaction):
    await interaction.response.send_message(f"Hey {interaction.user.mention}!")







#%%
# This Command Outputs the To-Do List

@bot.hybrid_command(name = "to_do_list", description= "The current list of non-completed to-do list action items")
#@app_commands.describe(to_do_list = "Please copy and paste the QR codes with no changes")
async def to_do_list(ctx):

    to_do_list_df = pd.read_pickle(path_for_to_do_list)

    filtered_df = to_do_list_df[to_do_list_df["STATUS"] != "Completed"]


    # Build a single embed, each task as a field (renders well on mobile & desktop)
    embed = discord.Embed(title="To Do List", color=0x00FF00)
    count = 0
    for _, row in filtered_df.loc[:, ["TASK", "PRIORITY", "STATUS", "DUE DATE", "RELEVANT LINK"]].sort_values(by=["PRIORITY", "DUE DATE"], ascending=[False, True]).astype(str).iterrows():
        if count >= 9:
            break  # Discord embed field limit
        task_name = row["TASK"]
        priority = row["PRIORITY"]
        status = row["STATUS"]
        if row["DUE DATE"] != "NaT":
            due = row["DUE DATE"]
        else:
            due = "No due date"
        link = row["RELEVANT LINK"]
        link_md = f"[LINK]({link})" if link and link not in ("None", "nan") else "No link"
        value = f"Priority: {priority}\nStatus: {status}\nDue: {due}\n{link_md}\n"
        embed.add_field(name=f'{count+1}. {task_name}', value=value, inline=False)

        count += 1
    
    await ctx.channel.send(embed=embed, view=TaskSelectView(count), delete_after=60)



#%% 


@tasks.loop(minutes=1)

# This command outputs the To-Do List Summary at 12:45 AM EST daily
async def send_daily_message():
    global last_discipline_daily_date
    global last_todo_visual_date
    global last_todo_weekly_visual_date

    est = pytz.timezone('US/Eastern')
    now = datetime.datetime.now(est)


    if now.hour == 7 and now.minute == 45:

        recurring_pd = pd.read_pickle(path_for_recurring_tasks)
        to_do_list_df = pd.read_pickle(path_for_to_do_list)
        active_df = to_do_list_df[to_do_list_df["STATUS"] != "Completed"]
        completed_df = to_do_list_df[to_do_list_df["STATUS"] == "Completed"]

        for _, row in recurring_pd.iterrows():
            task_name = row["TASK"]
            if task_name not in active_df["TASK"].values:
                latest = completed_df[completed_df["TASK"] == task_name]["COMPLETED TIME"].max()
                if pd.isna(latest) or datetime.datetime.now() - latest >= pd.Timedelta(days=int(row["RECURRING INTERVAL"])):
                    new_task = row.copy()
                    new_task["TASK CREATION"] = pd.to_datetime(datetime.datetime.now().isoformat(' ', 'seconds'))
                    new_task["STATUS"] = "Not Started"
                    new_task["START TIME"] = None
                    new_task["LOGGED HOURS"] = 0
                    new_task["COMPLETED"] = False
                    new_task["COMPLETED TIME"] = None
                    to_do_list_df = pd.concat([to_do_list_df, pd.DataFrame([new_task])])
        to_do_list_df.to_pickle(path_for_to_do_list)


    if now.hour == 8 and now.minute == 0:
        
        try: 
            to_do_list_channel = bot.get_channel(config['Channel_ID_to_do'])
        except:
            to_do_list_channel = bot.get_channel(channel_id)

        if to_do_list_channel:
            to_do_list_df = pd.read_pickle(path_for_to_do_list)

            filtered_df = to_do_list_df[to_do_list_df["STATUS"] != "Completed"]

            embed = discord.Embed(title="To Do List", color=0x00FF00)
            count = 0
            for _, row in filtered_df.loc[:, ["TASK", "PRIORITY", "STATUS", "DUE DATE", "RELEVANT LINK"]].sort_values(by=["PRIORITY", "DUE DATE"], ascending=[False, True]).astype(str).iterrows():
                task_name = row["TASK"]
                priority = row["PRIORITY"]
                status = row["STATUS"]
                if row["DUE DATE"] != "NaT":
                    due = row["DUE DATE"]
                else:
                    due = "No due date"
                link = row["RELEVANT LINK"]
                link_md = f"[LINK]({link})" if link and link not in ("None", "nan") else "No link"
                value = f"Priority: {priority}\nStatus: {status}\nDue: {due}\n{link_md}\n"
                embed.add_field(name=f'{count+1}. {task_name}', value=value, inline=False)
                count += 1
            await to_do_list_channel.send(f"<@{user_id}>, Daily To-Do List Summary:")
            await to_do_list_channel.send(embed=embed)


    if now.hour == 23 and now.minute == 0:
        
        try: 
            to_do_list_channel = bot.get_channel(config['Channel_ID_to_do'])
        except:
            to_do_list_channel = bot.get_channel(channel_id)

        if to_do_list_channel:
            to_do_list_df = pd.read_pickle(path_for_to_do_list)

            filtered_df = to_do_list_df[
                (to_do_list_df["STATUS"] == "Completed")
                & (to_do_list_df["COMPLETED TIME"] >= pd.Timestamp.now() - pd.Timedelta(hours=24))
            ]

            embed = discord.Embed(title="Tasks Completed Today", color=0x00FF00)
            count = 0
            for _, row in filtered_df.loc[:, ["TASK", "PRIORITY", "STATUS", "DUE DATE", "RELEVANT LINK"]].sort_values(by=["PRIORITY", "DUE DATE"], ascending=[False, True]).astype(str).iterrows():
                task_name = row["TASK"]
                priority = row["PRIORITY"]
                status = row["STATUS"]
                if row["DUE DATE"] != "NaT":
                    due = row["DUE DATE"]
                else:
                    due = "No due date"
                link = row["RELEVANT LINK"]
                link_md = f"[LINK]({link})" if link and link not in ("None", "nan") else "No link"
                value = f"Priority: {priority}\nStatus: {status}\nDue: {due}\n{link_md}\n"
                embed.add_field(name=f'{count+1}. {task_name}', value=value, inline=False)
                count += 1
            await to_do_list_channel.send(f"<@{user_id}>, Task Completed Today: {datetime.datetime.now().strftime('%m/%d/%Y')}")
            await to_do_list_channel.send(embed=embed)

    if now.hour == discipline_daily_hour and now.minute == discipline_daily_minute:
        if last_discipline_daily_date != now.date():
            discipline_channel = get_discipline_channel()
            if discipline_channel:
                try:
                    discipline_list_df = pd.read_pickle(path_for_discipline_list)
                    discipline_df = get_active_discipline_df(discipline_list_df)
                    completion_log_df = pd.read_pickle(path_for_discipline_completion_log)
                    embed = build_discipline_daily_embed(discipline_df, completion_log_df, now)
                    
                    today = pd.to_datetime(now.date()).normalize()
                    pending_tasks = []
                    for _, row in discipline_df.iterrows():
                        task_name = str(row["TASK"])
                        if not get_task_completed_today(task_name, completion_log_df, today):
                            pending_tasks.append(row)
                    
                    view = DisciplineTaskView(pending_tasks) if pending_tasks else None
                    
                    await discipline_channel.send(
                        f"<@{user_id}> Discipline check-in ({now.strftime('%I:%M %p ET')}):",
                        delete_after=discipline_delete_after_seconds,
                    )
                    await discipline_channel.send(
                        embed=embed,
                        view=view,
                        delete_after=discipline_delete_after_seconds,
                    )
                except Exception as e:
                    print(f"Error sending discipline daily tracker: {e}")
            last_discipline_daily_date = now.date()

    visual_trigger_total_minutes = (discipline_daily_hour * 60 + discipline_daily_minute + 15) % (24 * 60)
    visual_trigger_hour, visual_trigger_minute = divmod(visual_trigger_total_minutes, 60)

    if now.hour == visual_trigger_hour and now.minute == visual_trigger_minute:
        if last_todo_visual_date != now.date():
            to_do_list_channel = get_todo_channel()
            if to_do_list_channel:
                try:
                    to_do_list_df = pd.read_pickle(path_for_to_do_list)
                    completion_series = build_completed_task_series(to_do_list_df, end_date=now.date(), days=7)

                    today_total = int(completion_series.iloc[-1]) if not completion_series.empty else 0
                    week_total = int(completion_series.sum())
                    avg_daily = round(float(completion_series.mean()), 1) if len(completion_series) > 0 else 0

                    daily_subtitle = f"Today: {today_total} | Last 7 days: {week_total} | Avg/day: {avg_daily}"
                    daily_chart = render_completed_task_bar_chart(
                        completion_series=completion_series,
                        chart_title="To-Do Completion Trend (7 Days)",
                        subtitle=daily_subtitle,
                        highlight_index=len(completion_series) - 1,
                    )

                    await to_do_list_channel.send(f"<@{user_id}>, 15-minute post check-in completion snapshot:")
                    await to_do_list_channel.send(file=discord.File(fp=daily_chart, filename="todo_completion_7_day.png"))
                except Exception as e:
                    print(f"Error sending to-do completion trend chart: {e}")

            last_todo_visual_date = now.date()

        if now.weekday() == 6 and last_todo_weekly_visual_date != now.date():
            to_do_list_channel = get_todo_channel()
            if to_do_list_channel:
                try:
                    to_do_list_df = pd.read_pickle(path_for_to_do_list)
                    weekly_series = build_completed_task_series(to_do_list_df, end_date=now.date(), days=7)
                    weekly_total = int(weekly_series.sum())
                    weekly_avg = round(float(weekly_series.mean()), 1) if len(weekly_series) > 0 else 0

                    weekly_subtitle = f"Week total: {weekly_total} | Avg/day: {weekly_avg}"
                    weekly_chart = render_completed_task_bar_chart(
                        completion_series=weekly_series,
                        chart_title="Sunday End-of-Week Report",
                        subtitle=weekly_subtitle,
                        highlight_index=None,
                    )

                    await to_do_list_channel.send(f"<@{user_id}>, End-of-week completion report:")
                    await to_do_list_channel.send(file=discord.File(fp=weekly_chart, filename="todo_completion_end_of_week.png"))
                except Exception as e:
                    print(f"Error sending Sunday end-of-week chart: {e}")

            last_todo_weekly_visual_date = now.date()




#%%
# This command adds to the To-Do List

@bot.hybrid_command(name = "create_task", description = "Create a task for the to-do list")
@app_commands.describe(
        task_name = "The name of the task",
        catagory = "The catagory of the task, i.e. Video Games",
        group = "The group/overall objective that this task falls under. i.e. 100 percent goal",
        subgroup = "The sub-group that this task falls under, i.e. Complete Dark Souls",
        relevant_link = "Any relevant links that pertain to the topic", 
        recurring = "True if this event is reoccuring [False is assumed]",
        recurring_interval = "How often does this occur in days? Only needed if recurring is True",
        due_date = "Is there a due date, format = 20130102, or use Today (td), Tomorrow (tmw), Week (wk)",
        priority = "Scale out of 10, 10 is emergency priority, base is 1",
        estimated_time = "Estimated time to complete in active work hours",
)
async def create_task(ctx,
                      task_name,
                      catagory,
                      group = None,
                      subgroup = None,
                      relevant_link = None,
                      recurring = False,
                      recurring_interval = None,
                      due_date = None,
                      priority = 1,
                      estimated_time = None):
    

    
    due_date = normalize_due_date(due_date)

    to_list_pd = build_tracker_row(
        task_name=task_name,
        catagory=catagory,
        group=group,
        subgroup=subgroup,
        relevant_link=relevant_link,
        recurring=recurring,
        recurring_interval=recurring_interval,
        due_date=due_date,
        priority=priority,
        estimated_time=estimated_time,
    )
    
    if recurring and not recurring_interval:
        await ctx.send("Please provide a recurring interval in days for this recurring task.", delete_after=30)
        return
    
    if recurring_interval and not recurring:
        await ctx.send("Recurring interval provided but recurring is not set to True. Please set recurring to True if you want to use recurring interval.", delete_after=30)
        return
    
    if recurring and recurring_interval:
        try:
            recurring_interval = int(recurring_interval)
        except ValueError:
            await ctx.send("Recurring interval must be an integer representing days.", delete_after=30)
            return
        
        try:
            recurring_pd = pd.read_pickle(path_for_recurring_tasks)
        except FileNotFoundError:
            recurring_pd = pd.DataFrame()
        combine_recurring = pd.concat([recurring_pd, to_list_pd])
        try: 
            combine_recurring.to_pickle(path_for_recurring_tasks)
            await ctx.send("Added to recurring tasks")
        except Exception as e:
            await ctx.send(f"Something went wrong: {e}")
    
    to_do_list_df = pd.read_pickle(path_for_to_do_list)

    combine = pd.concat([to_list_pd, to_do_list_df])

    try: 
        combine.to_pickle(path_for_to_do_list)
        await ctx.send("Added", delete_after=60)
    except Exception as e:
        await ctx.send(f"Something went wrong: {e}")


@bot.command(name="to_do_completion_visual", help="Post a 7-day to-do completion bar chart to the to-do channel")
async def to_do_completion_visual(ctx):
    to_do_list_channel = get_todo_channel()
    if not to_do_list_channel:
        await ctx.send("To-do channel not found. Please verify Channel_ID_to_do in config.", delete_after=60)
        return

    try:
        to_do_list_df = pd.read_pickle(path_for_to_do_list)
        completion_series = build_completed_task_series(to_do_list_df, end_date=datetime.datetime.now().date(), days=7)

        today_total = int(completion_series.iloc[-1]) if not completion_series.empty else 0
        week_total = int(completion_series.sum())
        avg_daily = round(float(completion_series.mean()), 1) if len(completion_series) > 0 else 0

        subtitle = f"Today: {today_total} | Last 7 days: {week_total} | Avg/day: {avg_daily}"
        chart = render_completed_task_bar_chart(
            completion_series=completion_series,
            chart_title="To-Do Completion Trend (7 Days)",
            subtitle=subtitle,
            highlight_index=len(completion_series) - 1,
        )

        await to_do_list_channel.send(f"<@{user_id}>, On-demand 7-day completion snapshot:")
        await to_do_list_channel.send(file=discord.File(fp=chart, filename="todo_completion_7_day.png"))

        if ctx.channel.id != to_do_list_channel.id:
            await ctx.send("Posted the visual in the to-do channel.", delete_after=30)
    except Exception as e:
        await ctx.send(f"Could not generate to-do completion visual: {e}", delete_after=60)


@bot.command(name="to_do_weekly_visual", help="Post an end-of-week to-do completion bar chart to the to-do channel")
async def to_do_weekly_visual(ctx, week_end=None):
    to_do_list_channel = get_todo_channel()
    if not to_do_list_channel:
        await ctx.send("To-do channel not found. Please verify Channel_ID_to_do in config.", delete_after=60)
        return

    if week_end in (None, ""):
        end_date = pd.to_datetime(datetime.datetime.now().date()).normalize()
    else:
        try:
            end_date = pd.to_datetime(week_end).normalize()
        except Exception:
            await ctx.send("Invalid week_end format. Use YYYYMMDD (e.g., 20260517).", delete_after=60)
            return

    try:
        to_do_list_df = pd.read_pickle(path_for_to_do_list)
        weekly_series = build_completed_task_series(to_do_list_df, end_date=end_date, days=7)

        weekly_total = int(weekly_series.sum())
        weekly_avg = round(float(weekly_series.mean()), 1) if len(weekly_series) > 0 else 0

        subtitle = f"Week ending {pd.to_datetime(end_date).strftime('%m/%d/%Y')} | Total: {weekly_total} | Avg/day: {weekly_avg}"
        chart = render_completed_task_bar_chart(
            completion_series=weekly_series,
            chart_title="To-Do End-of-Week Report",
            subtitle=subtitle,
            highlight_index=None,
        )

        await to_do_list_channel.send(f"<@{user_id}>, On-demand weekly completion report:")
        await to_do_list_channel.send(file=discord.File(fp=chart, filename="todo_completion_end_of_week.png"))

        if ctx.channel.id != to_do_list_channel.id:
            await ctx.send("Posted the weekly visual in the to-do channel.", delete_after=30)
    except Exception as e:
        await ctx.send(f"Could not generate weekly to-do visual: {e}", delete_after=60)


@bot.command(name = "create_discipline_task", help = "Create a task in the separate discipline tracker")
async def create_discipline_task(
    ctx,
    task_name,
    catagory,
    frequency_per_week,
):
    ensure_discipline_dataframe_exists()

    try:
        frequency_per_week = int(frequency_per_week)
    except ValueError:
        await ctx.send("frequency_per_week must be a number between 1 and 7.", delete_after=60)
        return

    if frequency_per_week < 1 or frequency_per_week > 7:
        await ctx.send("frequency_per_week must be between 1 and 7.", delete_after=60)
        return

    discipline_row = build_discipline_row(
        task_name=task_name,
        catagory=catagory,
        frequency_per_week=frequency_per_week,
    )

    try:
        discipline_df = pd.read_pickle(path_for_discipline_list)
    except FileNotFoundError:
        discipline_df = discipline_row.iloc[0:0]

    updated_df = pd.concat([discipline_row, discipline_df], ignore_index=True)

    try:
        updated_df.to_pickle(path_for_discipline_list)
        await ctx.send("Added to separate discipline tracker.", delete_after=60)
    except Exception as e:
        await ctx.send(f"Something went wrong: {e}")


@bot.command(name = "discipline_list", help= "The separate discipline tracker list")
async def discipline_list(ctx):
    ensure_discipline_dataframe_exists()
    discipline_df = pd.read_pickle(path_for_discipline_list)
    filtered_df = get_active_discipline_df(discipline_df)

    embed = discord.Embed(title="Discipline Tracker", color=0x2ECC71)
    count = 0
    for _, row in filtered_df.loc[:, ["TASK", "CATAGORY", "FREQUENCY_PER_WEEK"]].astype(str).iterrows():
        if count >= 20:
            break
        task_name = row["TASK"]
        value = f"Category: {row['CATAGORY']}\nFrequency/Week: {row['FREQUENCY_PER_WEEK']}\n"
        embed.add_field(name=f"{count+1}. {task_name}", value=value, inline=False)
        count += 1

    if count == 0:
        embed.add_field(name="No Tracked Items", value="No discipline tasks are currently tracked.", inline=False)

    await ctx.channel.send(embed=embed, delete_after=120)


@bot.command(name = "log_discipline_completion", help= "Log a completed discipline item for data collection")
async def log_discipline_completion(ctx, task_name, completed_date=None):
    ensure_discipline_dataframe_exists()
    ensure_discipline_completion_log_exists()

    discipline_df = pd.read_pickle(path_for_discipline_list)
    task_match = discipline_df[discipline_df["TASK"].astype(str).str.lower() == str(task_name).strip().lower()]

    if task_match.empty:
        await ctx.send(f"Task not found in discipline tracker. Use {command_prefix}discipline_list to view tracked items.", delete_after=60)
        return

    task_row = task_match.iloc[0]
    catagory = str(task_row["CATAGORY"])

    if completed_date in (None, ""):
        completed_date = datetime.datetime.now().date()

    completion_row = build_discipline_completion_row(task_name=task_row["TASK"], catagory=catagory, completed_date=completed_date)

    try:
        completion_df = pd.read_pickle(path_for_discipline_completion_log)
    except FileNotFoundError:
        completion_df = completion_row.iloc[0:0]

    updated_completion_df = pd.concat([completion_df, completion_row], ignore_index=True)
    updated_completion_df.to_pickle(path_for_discipline_completion_log)

    logged_date = pd.to_datetime(completion_row["COMPLETED_DATE"].iloc[0]).strftime("%m/%d/%Y")
    await ctx.send(f"Logged completion for '{task_row['TASK']}' on {logged_date}.", delete_after=60)


@bot.command(name = "today_completions", help= "View discipline items you've logged as completed today")
async def today_completions(ctx, date=None):
    ensure_discipline_completion_log_exists()

    if date in (None, ""):
        target_date = pd.to_datetime(datetime.datetime.now().date()).normalize()
        display_date = datetime.datetime.now().strftime("%m/%d/%Y")
    else:
        try:
            target_date = pd.to_datetime(date).normalize()
            display_date = target_date.strftime("%m/%d/%Y")
        except Exception as e:
            await ctx.send(f"Invalid date format. Use YYYYMMDD (e.g., 20260511).", delete_after=60)
            return

    completion_df = pd.read_pickle(path_for_discipline_completion_log)
    today_logged = completion_df[completion_df["COMPLETED_DATE"] == target_date].copy()

    embed = discord.Embed(
        title=f"Discipline Completions - {display_date}",
        description="Items logged as completed on this date.",
        color=0x3498DB,
    )

    if today_logged.empty:
        embed.add_field(name="No Completions Logged", value="No items logged for this date.", inline=False)
        await ctx.send(embed=embed, delete_after=120)
        return

    count = 0
    grouped_by_task = today_logged.groupby("TASK").agg({
        "CATAGORY": "first",
        "LOGGED_AT": "min",
    }).reset_index()

    for _, row in grouped_by_task.iterrows():
        if count >= 20:
            break
        task_name = str(row["TASK"])
        catagory = str(row["CATAGORY"])
        logged_at = pd.to_datetime(row["LOGGED_AT"]).strftime("%I:%M %p")
        value = f"Category: {catagory}\nLogged at: {logged_at}"
        embed.add_field(name=f"{count + 1}. {task_name}", value=value, inline=False)
        count += 1

    if len(grouped_by_task) > 20:
        embed.set_footer(text=f"Showing top 20 of {len(grouped_by_task)} completions")
    else:
        embed.set_footer(text=f"Total logged: {len(grouped_by_task)}")

    await ctx.send(embed=embed, delete_after=120)


@bot.command(name = "weekly_discipline_summary", help= "Weekly discipline progress vs frequency targets")
async def weekly_discipline_summary(ctx, week_start=None):
    ensure_discipline_dataframe_exists()
    ensure_discipline_completion_log_exists()

    discipline_df = pd.read_pickle(path_for_discipline_list)
    if discipline_df.empty:
        await ctx.send("No discipline tasks are currently tracked.", delete_after=60)
        return

    today = pd.to_datetime(datetime.datetime.now().date()).normalize()
    if week_start in (None, ""):
        start_date = today - pd.Timedelta(days=int(today.weekday()))
    else:
        try:
            parsed_start = pd.to_datetime(week_start).normalize()
            start_date = parsed_start - pd.Timedelta(days=int(parsed_start.weekday()))
        except Exception:
            await ctx.send("Invalid week_start format. Use YYYYMMDD (e.g., 20260511).", delete_after=60)
            return

    end_date = start_date + pd.Timedelta(days=6)

    completion_df = pd.read_pickle(path_for_discipline_completion_log)
    if completion_df.empty:
        weekly_df = completion_df
    else:
        completion_df = completion_df.copy()
        completion_df["COMPLETED_DATE"] = pd.to_datetime(completion_df["COMPLETED_DATE"]).dt.normalize()
        weekly_df = completion_df[
            (completion_df["COMPLETED_DATE"] >= start_date)
            & (completion_df["COMPLETED_DATE"] <= end_date)
        ]

    # Count unique completion days per task so duplicate logs on one day do not inflate progress.
    weekly_counts = {}
    if not weekly_df.empty:
        weekly_counts = weekly_df.groupby("TASK")["COMPLETED_DATE"].nunique().to_dict()

    report_df = discipline_df.copy()
    report_df["TASK"] = report_df["TASK"].astype(str)
    report_df["FREQUENCY_PER_WEEK"] = pd.to_numeric(report_df["FREQUENCY_PER_WEEK"], errors="coerce").fillna(1).astype(int)
    report_df["FREQUENCY_PER_WEEK"] = report_df["FREQUENCY_PER_WEEK"].clip(lower=1, upper=7)
    report_df["COMPLETIONS_THIS_WEEK"] = report_df["TASK"].map(weekly_counts).fillna(0).astype(int)

    total_target = int(report_df["FREQUENCY_PER_WEEK"].sum())
    total_actual = int(report_df["COMPLETIONS_THIS_WEEK"].sum())
    overall_percent = (min(total_actual / total_target, 1) * 100) if total_target > 0 else 0

    embed = discord.Embed(
        title=f"Weekly Discipline Report ({start_date.strftime('%m/%d')} - {end_date.strftime('%m/%d')})",
        description="Progress against each task's weekly target frequency.",
        color=0xF1C40F,
    )

    sorted_report = report_df.sort_values(by=["FREQUENCY_PER_WEEK", "TASK"], ascending=[False, True])
    count = 0
    for _, row in sorted_report.iterrows():
        if count >= 20:
            break
        task_name = str(row["TASK"])
        catagory = str(row["CATAGORY"])
        target = int(row["FREQUENCY_PER_WEEK"])
        actual = int(row["COMPLETIONS_THIS_WEEK"])
        percent = round(min(actual / target, 1) * 100, 1) if target > 0 else 0
        extra = f" (+{actual - target})" if actual > target else ""
        value = (
            f"Category: {catagory}\n"
            f"This Week: {actual}/{target}{extra}\n"
            f"Progress: {percent}%"
        )
        embed.add_field(name=f"{count + 1}. {task_name}", value=value, inline=False)
        count += 1

    embed.set_footer(
        text=f"Overall: {total_actual}/{total_target} ({round(overall_percent, 1)}%) | Use {command_prefix}weekly_discipline_summary YYYYMMDD"
    )
    await ctx.send(embed=embed, delete_after=180)


@bot.command(name="daily_discipline_visual", aliases=["discipline_daily_visual"], help="Post today's discipline goal-status visual to the discipline channel")
async def daily_discipline_visual(ctx):
    ensure_discipline_dataframe_exists()
    ensure_discipline_completion_log_exists()

    try:
        await ctx.message.delete()
    except Exception:
        pass

    discipline_channel = get_discipline_channel()
    if not discipline_channel:
        await ctx.send("Discipline channel not found. Please verify Channel_ID_discipline in config.", delete_after=60)
        return

    discipline_df = pd.read_pickle(path_for_discipline_list)
    if discipline_df.empty:
        await ctx.send("No discipline tasks are currently tracked.", delete_after=60)
        return

    today = pd.to_datetime(datetime.datetime.now().date()).normalize()
    week_start = today - pd.Timedelta(days=int(today.weekday()))
    week_end = week_start + pd.Timedelta(days=6)

    completion_df = pd.read_pickle(path_for_discipline_completion_log)
    report_df = build_discipline_weekly_counts(discipline_df, completion_df, week_start, week_end)

    # Build state flags to match the daily visual intent.
    report_df["COMPLETED_TODAY"] = report_df["TASK"].apply(
        lambda task: get_task_completed_today(task, normalize_discipline_completion_df(completion_df), today)
    )

    status_codes = []
    goal_met_flags = []
    reached_today_count = 0
    goal_already_met_count = 0
    done_today_not_met_count = 0
    needs_completion_count = 0

    for _, row in report_df.iterrows():
        target = int(row["FREQUENCY_PER_WEEK"])
        actual_now = int(row["COMPLETIONS_THIS_WEEK"])
        actual_before_today = int(row["COMPLETIONS_BEFORE_END_DATE"])
        completed_today = bool(row["COMPLETED_TODAY"])

        if actual_now >= target:
            goal_met_flags.append(1)
            if completed_today and actual_before_today < target:
                status_codes.append("met_today")
                reached_today_count += 1
            else:
                status_codes.append("met_before_today")
                goal_already_met_count += 1
        else:
            goal_met_flags.append(0)
            if completed_today:
                status_codes.append("done_today_not_met")
                done_today_not_met_count += 1
            else:
                status_codes.append("needs_completion")
                needs_completion_count += 1

    report_df["STATUS_CODE"] = status_codes
    report_df["GOAL_MET_BINARY"] = goal_met_flags

    subtitle = (
        f"Met Today: {reached_today_count} | Already Met: {goal_already_met_count} | "
        f"Done Today: {done_today_not_met_count} | Need: {needs_completion_count}"
    )
    chart = render_discipline_daily_goal_status_chart(
        status_df=report_df,
        chart_title=f"Discipline Daily Goal Status ({today.strftime('%m/%d/%Y')})",
        subtitle=subtitle,
    )

    await discipline_channel.send(f"<@{user_id}>, On-demand discipline daily visual:", delete_after=300)
    await discipline_channel.send(file=discord.File(fp=chart, filename="discipline_daily_goal_status.png"), delete_after=300)

    if ctx.channel.id != discipline_channel.id:
        await ctx.send("Posted the discipline daily visual in the discipline channel.", delete_after=300)


@bot.command(name="weekly_discipline_visual", aliases=["discipline_weekly_visual", "weekly_discipline_report"], help="Post weekly discipline progress visual to the discipline channel")
async def weekly_discipline_visual(ctx, week_start=None):
    ensure_discipline_dataframe_exists()
    ensure_discipline_completion_log_exists()

    try:
        await ctx.message.delete()
    except Exception:
        pass

    discipline_channel = get_discipline_channel()
    if not discipline_channel:
        await ctx.send("Discipline channel not found. Please verify Channel_ID_discipline in config.", delete_after=60)
        return

    discipline_df = pd.read_pickle(path_for_discipline_list)
    if discipline_df.empty:
        await ctx.send("No discipline tasks are currently tracked.", delete_after=60)
        return

    today = pd.to_datetime(datetime.datetime.now().date()).normalize()
    if week_start in (None, ""):
        start_date = today - pd.Timedelta(days=int(today.weekday()))
    else:
        try:
            parsed_start = pd.to_datetime(week_start).normalize()
            start_date = parsed_start - pd.Timedelta(days=int(parsed_start.weekday()))
        except Exception:
            await ctx.send("Invalid week_start format. Use YYYYMMDD (e.g., 20260511).", delete_after=60)
            return

    end_date = start_date + pd.Timedelta(days=6)
    completion_df = pd.read_pickle(path_for_discipline_completion_log)
    report_df = build_discipline_weekly_counts(discipline_df, completion_df, start_date, end_date)

    total_target = int(report_df["FREQUENCY_PER_WEEK"].sum())
    total_actual = int(report_df["COMPLETIONS_THIS_WEEK"].sum())
    completion_rate = round((min(total_actual / total_target, 1) * 100) if total_target > 0 else 0, 1)

    subtitle = f"Week {start_date.strftime('%m/%d')} - {end_date.strftime('%m/%d')} | Total: {total_actual}/{total_target} | Goal Hit: {completion_rate}%"
    chart = render_discipline_weekly_progress_chart(
        report_df=report_df,
        chart_title="Discipline Weekly Progress (Actual vs Target)",
        subtitle=subtitle,
    )

    await discipline_channel.send(f"<@{user_id}>, On-demand discipline weekly visual:", delete_after=300)
    await discipline_channel.send(file=discord.File(fp=chart, filename="discipline_weekly_progress.png"), delete_after=300)

    if ctx.channel.id != discipline_channel.id:
        await ctx.send("Posted the discipline weekly visual in the discipline channel.", delete_after=300)


#%%
# This command updates the status of a task

    

#%%
# RUN THE BOT
bot.run(config['TOKEN'])


#%%
