"""Discord UI components — Button views for task selection and discipline logging."""
import datetime

import discord
import pandas as pd

from .bot_config import command_prefix
from . import db
from .task_helpers import get_open_task_mask, pause_task_tracking, load_latest_task_row, build_task_detail_embed
from .follow_up_helpers import create_follow_up_tasks_for
from .discipline_helpers import (
    ensure_discipline_dataframe_exists,
    ensure_discipline_history_exists,
    read_discipline_history,
    set_discipline_cell,
    is_task_completed_on,
)


# --- To-Do List Views ---

class TaskSelectButton(discord.ui.Button):
    def __init__(self, index):
        super().__init__(label=str(index + 1), style=discord.ButtonStyle.secondary)
        self.index = index

    async def callback(self, interaction: discord.Interaction):
        to_do_list_df = db.load_tasks_df()
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
    """Buttons to Complete, Start, Pause, or defer a task."""
    def __init__(self, task_name):
        super().__init__(timeout=None)
        self.task_name = task_name

    async def _persist_and_ack(self, interaction, to_do_list_df, message):
        db.save_tasks_df(to_do_list_df)
        await interaction.response.edit_message(content=message, embed=None, view=None)
        msg = await interaction.original_response()
        await msg.delete(delay=30)

    async def _load_open_task_df(self, interaction):
        to_do_list_df = db.load_tasks_df()
        task_mask = get_open_task_mask(to_do_list_df, self.task_name)
        if task_mask.sum() == 0:
            await interaction.response.send_message("Task no longer exists or is already completed.", ephemeral=True)
            return None, None
        return to_do_list_df, task_mask

    async def _defer_task(self, interaction, due_date, label):
        to_do_list_df, task_mask = await self._load_open_task_df(interaction)
        if to_do_list_df is None:
            return

        now_timestamp = pd.to_datetime(datetime.datetime.now().isoformat(' ', 'seconds'))
        pause_task_tracking(to_do_list_df, task_mask, now_timestamp)
        to_do_list_df.loc[task_mask, "DUE DATE"] = pd.to_datetime(due_date)
        to_do_list_df.loc[task_mask, "STATUS"] = "Pending"
        await self._persist_and_ack(
            interaction,
            to_do_list_df,
            f"Deferred '{self.task_name}' to {label}.",
        )

    @discord.ui.button(label="Complete", style=discord.ButtonStyle.success, emoji="✅")
    async def complete_task(self, interaction: discord.Interaction, button: discord.ui.Button):
        to_do_list_df, task_mask = await self._load_open_task_df(interaction)
        if to_do_list_df is None:
            return

        completion_timestamp = pd.to_datetime(datetime.datetime.now().isoformat(' ', 'seconds'))
        pause_task_tracking(to_do_list_df, task_mask, completion_timestamp)
        to_do_list_df.loc[task_mask, "COMPLETED TIME"] = completion_timestamp
        to_do_list_df.loc[task_mask, "STATUS"] = "Completed"
        db.save_tasks_df(to_do_list_df)

        # Auto-create any follow-up tasks tied to this trigger (e.g. Do Dishes -> Put up Dishes).
        created_follow_ups = []
        try:
            completed_row = to_do_list_df.loc[task_mask].iloc[0]
            created_follow_ups = create_follow_up_tasks_for(self.task_name, source_row=completed_row)
        except Exception as e:
            print(f"Error creating follow-up tasks for '{self.task_name}': {e}")

        try:
            task_row = load_latest_task_row(self.task_name)
            if task_row is None:
                await interaction.response.send_message(f"Task '{self.task_name}' could not be reloaded after completion.", ephemeral=True)
                return

            embed = build_task_detail_embed(task_row)
            if created_follow_ups:
                embed.add_field(
                    name="🔁 Follow-ups Created",
                    value="\n".join(f"• {name}" for name in created_follow_ups),
                    inline=False,
                )

            await interaction.response.edit_message(embed=embed, view=None)
            msg = await interaction.original_response()
            await msg.delete(delay=60)

        except Exception as e:
            await interaction.response.send_message(f"Error completing task '{self.task_name}': {e}", ephemeral=True)

    @discord.ui.button(label="Start", style=discord.ButtonStyle.primary, emoji="▶️")
    async def start_task(self, interaction: discord.Interaction, button: discord.ui.Button):
        to_do_list_df, task_mask = await self._load_open_task_df(interaction)
        if to_do_list_df is None:
            return

        to_do_list_df.loc[task_mask, "START TIME"] = pd.to_datetime(datetime.datetime.now().isoformat(' ', 'seconds'))
        to_do_list_df.loc[task_mask, "STATUS"] = "In Progress"
        await self._persist_and_ack(interaction, to_do_list_df, f"Updated '{self.task_name}' to 'In Progress'")

    @discord.ui.button(label="Pause", style=discord.ButtonStyle.secondary, emoji="⏸️")
    async def pause_task(self, interaction: discord.Interaction, button: discord.ui.Button):
        to_do_list_df, task_mask = await self._load_open_task_df(interaction)
        if to_do_list_df is None:
            return

        now_timestamp = pd.to_datetime(datetime.datetime.now().isoformat(' ', 'seconds'))
        pause_task_tracking(to_do_list_df, task_mask, now_timestamp)
        to_do_list_df.loc[task_mask, "STATUS"] = "Hiatus"
        await self._persist_and_ack(interaction, to_do_list_df, f"Updated '{self.task_name}' to 'Hiatus'")

    @discord.ui.button(label="Weekend", style=discord.ButtonStyle.secondary, emoji="🗓️")
    async def move_to_weekend(self, interaction: discord.Interaction, button: discord.ui.Button):
        today = datetime.datetime.now().date()
        days_until_saturday = (5 - today.weekday()) % 7
        if days_until_saturday == 0:
            days_until_saturday = 7
        weekend_date = today + datetime.timedelta(days=days_until_saturday)
        await self._defer_task(interaction, weekend_date, f"the weekend ({weekend_date.strftime('%m/%d')})")


# --- Discipline Tracker Views ---

class DisciplineTaskButton(discord.ui.Button):
    def __init__(self, index, task_name):
        super().__init__(label=str(index + 1), style=discord.ButtonStyle.secondary)
        self.index = index
        self.task_name = task_name

    async def callback(self, interaction: discord.Interaction):
        ensure_discipline_dataframe_exists()
        ensure_discipline_history_exists()

        today = pd.to_datetime(datetime.datetime.now().date()).normalize()
        history_df = read_discipline_history()
        is_logged = is_task_completed_on(self.task_name, today, history_df)

        # Verify task still exists in the discipline list before creating a new column.
        discipline_df = db.load_discipline_df()
        task_match = discipline_df[discipline_df["TASK"].astype(str).str.lower() == str(self.task_name).strip().lower()]
        if task_match.empty and not is_logged:
            await interaction.response.send_message(
                f"❌ Task not found. Use {command_prefix}discipline_list to view tracked items.",
                ephemeral=True,
                delete_after=30,
            )
            return

        set_discipline_cell(self.task_name, today, not is_logged)

        if is_logged:
            await interaction.response.send_message(
                f"✅ Marked '{self.task_name}' as incomplete for today.",
                ephemeral=True,
                delete_after=30,
            )
        else:
            await interaction.response.send_message(
                f"✅ Logged '{self.task_name}' as completed for today.",
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
