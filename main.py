#%%
# IMPORTING LIBRARIES

import datetime

import discord
from discord.ext import commands, tasks
from discord import app_commands
import pytz
import pandas as pd
import warnings
warnings.simplefilter(action='ignore', category=FutureWarning)

# --- Project Modules ---
from bot_modules.bot_config import (
    config,
    command_prefix,
    channel_id,
    user_id,
    discipline_delete_after_seconds,
    discipline_daily_hour,
    discipline_daily_minute,
    discipline_at_risk_weekday,
    discipline_at_risk_hour,
    discipline_at_risk_minute,
)
from bot_modules import db
from bot_modules.task_helpers import (
    build_tracker_row,
    normalize_due_date,
    build_completed_task_series,
    get_open_task_mask,
    load_latest_task_row,
    pause_task_tracking,
    build_task_detail_embed,
    resolve_task_index_from_position,
    parse_field_value_pairs,
    apply_task_field_updates,
    EDITABLE_TASK_FIELDS,
    parse_task_filter_tokens,
    filter_tasks,
    FILTERABLE_TASK_FIELDS,
)
from bot_modules.discipline_helpers import (
    build_discipline_row,
    ensure_discipline_dataframe_exists,
    ensure_discipline_history_exists,
    normalize_discipline_completion_df,
    build_discipline_weekly_counts,
    get_active_discipline_df,
    get_task_completed_today,
    calculate_streak,
    build_discipline_insight_df,
    build_discipline_alert_summary,
    build_discipline_daily_embed,
    build_discipline_progress_embed,
    build_discipline_category_rollup_df,
    build_discipline_at_risk_embed,
    read_discipline_history,
    set_discipline_cell,
    is_task_completed_on,
    load_discipline_completion_df,
)
from bot_modules.chart_rendering import (
    render_completed_task_bar_chart,
    render_discipline_daily_goal_status_chart,
    render_discipline_weekly_progress_chart,
    render_discipline_category_rollup_chart,
    render_discipline_heatmap_chart,
)
from bot_modules.follow_up_helpers import (
    load_follow_ups,
    add_follow_up as add_follow_up_mapping,
    delete_follow_up as delete_follow_up_mapping,
)
from bot_modules.ui_components import TaskSelectView, DisciplineTaskView


#%%
# BOT INITIALIZATION

bot = commands.Bot(command_prefix=command_prefix, intents=discord.Intents.all())

last_discipline_daily_date = None
last_discipline_visual_date = None
last_todo_weekly_visual_date = None
last_discipline_at_risk_date = None


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
    ensure_discipline_history_exists()
    send_daily_message.start()

    if luigi_channel:
        # Create a comprehensive command list embed
        embed = discord.Embed(
            title="🤖 LuigiBot Startup — Available Commands",
            description="All commands and their functions",
            color=0x1E90FF,
        )

        todo_lines = [
            "`/hello` — Greeting test command",
            f"`/to_do_list` or `{command_prefix}to_do_list` — View active to-do items (sorted by priority & due date)",
            f"`/create_task` or `{command_prefix}create_task` — Create a new to-do task with metadata (priority, due date, estimated time, etc.)",
            f"`{command_prefix}edit_task <id> field=value ...` — Edit fields on an open task (priority, due_date, task_name, category, group, subgroup, link, status, estimated_time)",
            f"`{command_prefix}delete_task <id>` — Delete an open task by id (history preserved)",
            f"`{command_prefix}tasks field:value ...` — Search/filter open tasks (e.g. `category:Health priority:>=7 due:week`)",
            f"`{command_prefix}to_do_completion_visual` — Post a 7-day completed-task bar chart to the to-do channel",
            f"`{command_prefix}to_do_weekly_visual [week_end]` — Post an end-of-week bar chart to the to-do channel (optional YYYYMMDD)",
            f"`/add_follow_up` or `{command_prefix}add_follow_up <trigger> <follow_up> [catagory] [priority] [due_offset_days] [estimated_time] [link]` — Auto-create a follow-up task when a trigger task is completed (e.g. Do Dishes → Put up Dishes)",
            f"`{command_prefix}follow_ups` — List configured trigger → follow-up mappings",
            f"`{command_prefix}delete_follow_up <id>` — Delete a follow-up mapping by id",
        ]

        discipline_lines = [
            f"`/create_discipline_task` or `{command_prefix}create_discipline_task` — Add a discipline item (task name, category, frequency/week 1-7)",
            f"`{command_prefix}discipline_list` — View all tracked discipline items",
            f"`{command_prefix}log_discipline_completion` — Log completion of a discipline task (for data collection)",
            f"`{command_prefix}today_completions` — View today's logged discipline completions (or any date)",
            f"`{command_prefix}weekly_discipline_summary` — Weekly progress report vs frequency targets",
            f"`{command_prefix}discipline_streaks` — Current streaks, best streaks, and 4-week consistency scores",
            f"`{command_prefix}discipline_progress [YYYYMMDD]` — Weekly partial-credit progress bars (X/Y) for each discipline",
            f"`{command_prefix}at_risk [YYYYMMDD]` — List disciplines that won't hit their weekly target at current pace (auto-pings midweek)",
            f"`{command_prefix}discipline_heatmap [days] [YYYYMMDD]` — Post a GitHub-style heatmap of daily discipline completions (default 90 days)",
            f"`{command_prefix}daily_discipline_visual` — Post today's discipline goal-status visual to the discipline channel",
            f"`{command_prefix}weekly_discipline_visual [week_start]` — Post weekly discipline progress visual to the discipline channel",
            f"`{command_prefix}discipline_category_rollup [week_start]` — Post weekly category-level adherence chart to the discipline channel",
        ]

        def _chunk_lines_for_embed(lines, limit=1024):
            chunks = []
            current = ""
            for line in lines:
                addition = (line if not current else "\n" + line)
                if len(current) + len(addition) > limit:
                    chunks.append(current)
                    current = line
                else:
                    current += addition
            if current:
                chunks.append(current)
            return chunks

        for idx, chunk in enumerate(_chunk_lines_for_embed(todo_lines)):
            name = "📋 To-Do List Commands" if idx == 0 else "📋 To-Do List Commands (cont.)"
            embed.add_field(name=name, value=chunk, inline=False)

        for idx, chunk in enumerate(_chunk_lines_for_embed(discipline_lines)):
            name = "🎯 Discipline Tracker Commands" if idx == 0 else "🎯 Discipline Tracker Commands (cont.)"
            embed.add_field(name=name, value=chunk, inline=False)

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

    to_do_list_df = db.load_tasks_df()

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
    global last_discipline_visual_date
    global last_todo_weekly_visual_date
    global last_discipline_at_risk_date

    est = pytz.timezone('US/Eastern')
    now = datetime.datetime.now(est)


    if now.hour == 7 and now.minute == 45:

        recurring_pd = db.load_recurring_df()
        to_do_list_df = db.load_tasks_df()
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
        db.save_tasks_df(to_do_list_df)


    if now.hour == 8 and now.minute == 0:
        
        try: 
            to_do_list_channel = bot.get_channel(config['Channel_ID_to_do'])
        except:
            to_do_list_channel = bot.get_channel(channel_id)

        if to_do_list_channel:
            to_do_list_df = db.load_tasks_df()

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
            to_do_list_df = db.load_tasks_df()

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

            try:
                completion_series = build_completed_task_series(to_do_list_df, end_date=now.date(), days=7)
                today_total = int(completion_series.iloc[-1]) if not completion_series.empty else 0
                week_total = int(completion_series.sum())
                avg_daily = round(float(completion_series.mean()), 1) if len(completion_series) > 0 else 0

                subtitle = f"Today: {today_total} | Last 7 days: {week_total} | Avg/day: {avg_daily}"
                chart = render_completed_task_bar_chart(
                    completion_series=completion_series,
                    chart_title="Tasks Completed Today (7-Day Context)",
                    subtitle=subtitle,
                    highlight_index=len(completion_series) - 1,
                )
                await to_do_list_channel.send(file=discord.File(fp=chart, filename="tasks_completed_today_visual.png"))
            except Exception as e:
                print(f"Error sending completed-task daily visual: {e}")

    if now.hour == discipline_daily_hour and now.minute == discipline_daily_minute:
        if last_discipline_daily_date != now.date():
            discipline_channel = get_discipline_channel()
            if discipline_channel:
                try:
                    discipline_list_df = db.load_discipline_df()
                    discipline_df = get_active_discipline_df(discipline_list_df)
                    completion_log_df = load_discipline_completion_df()
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
        if last_discipline_visual_date != now.date():
            discipline_channel = get_discipline_channel()
            if discipline_channel:
                try:
                    ensure_discipline_dataframe_exists()
                    ensure_discipline_history_exists()

                    discipline_df = db.load_discipline_df()
                    completion_df = load_discipline_completion_df()

                    if not discipline_df.empty:
                        today = pd.to_datetime(now.date()).normalize()
                        week_start = today - pd.Timedelta(days=int(today.weekday()))
                        week_end = week_start + pd.Timedelta(days=6)

                        normalized_completion_df = normalize_discipline_completion_df(completion_df)
                        report_df = build_discipline_weekly_counts(
                            discipline_df,
                            normalized_completion_df,
                            week_start,
                            week_end,
                        )
                        report_df["COMPLETED_TODAY"] = report_df["TASK"].apply(
                            lambda task: get_task_completed_today(task, normalized_completion_df, today)
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

                        await discipline_channel.send(f"<@{user_id}>, 15-minute post check-in discipline snapshot:")
                        await discipline_channel.send(
                            file=discord.File(fp=chart, filename="discipline_daily_goal_status_nightly.png")
                        )
                except Exception as e:
                    print(f"Error sending nightly discipline visual: {e}")

            last_discipline_visual_date = now.date()

        if now.weekday() == 6 and last_todo_weekly_visual_date != now.date():
            to_do_list_channel = get_todo_channel()
            if to_do_list_channel:
                try:
                    to_do_list_df = db.load_tasks_df()
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

    if (
        now.weekday() == discipline_at_risk_weekday
        and now.hour == discipline_at_risk_hour
        and now.minute == discipline_at_risk_minute
        and last_discipline_at_risk_date != now.date()
    ):
        discipline_channel = get_discipline_channel()
        if discipline_channel:
            try:
                ensure_discipline_dataframe_exists()
                ensure_discipline_history_exists()
                discipline_df = db.load_discipline_df()
                completion_df = load_discipline_completion_df()
                reference_day = pd.to_datetime(now.date()).normalize()
                embed = build_discipline_at_risk_embed(
                    discipline_df, completion_df, reference_date=reference_day
                )
                await discipline_channel.send(
                    f"<@{user_id}> Midweek discipline check ({now.strftime('%a %I:%M %p ET')}):",
                    delete_after=discipline_delete_after_seconds,
                )
                await discipline_channel.send(
                    embed=embed,
                    delete_after=discipline_delete_after_seconds,
                )
            except Exception as e:
                print(f"Error sending midweek at-risk nudge: {e}")
        last_discipline_at_risk_date = now.date()




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
            recurring_pd = db.load_recurring_df()
        except FileNotFoundError:
            recurring_pd = pd.DataFrame()
        combine_recurring = pd.concat([recurring_pd, to_list_pd])
        try: 
            db.save_recurring_df(combine_recurring)
            await ctx.send("Added to recurring tasks")
        except Exception as e:
            await ctx.send(f"Something went wrong: {e}")
    
    to_do_list_df = db.load_tasks_df()

    combine = pd.concat([to_list_pd, to_do_list_df])

    try: 
        db.save_tasks_df(combine)
        await ctx.send("Added", delete_after=60)
    except Exception as e:
        await ctx.send(f"Something went wrong: {e}")


@bot.command(
    name="edit_task",
    help='Edit fields on an open task. Usage: !L edit_task <id> field=value [field=value ...]'
)
async def edit_task(ctx, task_id, *, updates: str = ""):
    try:
        position = int(task_id)
    except ValueError:
        await ctx.send("Task id must be the number shown in `!L to_do_list`.", delete_after=60)
        return

    if not updates.strip():
        allowed = ", ".join(sorted(set(EDITABLE_TASK_FIELDS)))
        await ctx.send(
            f"Provide at least one `field=value` pair. Allowed fields: {allowed}",
            delete_after=90,
        )
        return

    try:
        to_do_list_df = db.load_tasks_df()
    except Exception as e:
        await ctx.send(f"Could not read to-do list: {e}", delete_after=60)
        return

    df_index, target_row = resolve_task_index_from_position(to_do_list_df, position)
    if df_index is None:
        await ctx.send(f"No open task at position {position}. Run `!L to_do_list` to see current ids.", delete_after=60)
        return

    try:
        pairs = parse_field_value_pairs(updates)
        applied = apply_task_field_updates(to_do_list_df, df_index, pairs)
    except ValueError as exc:
        await ctx.send(f"Edit failed: {exc}", delete_after=90)
        return

    try:
        db.save_tasks_df(to_do_list_df)
    except Exception as e:
        await ctx.send(f"Could not save updates: {e}", delete_after=60)
        return

    task_name = str(target_row["TASK"])
    summary_lines = [f"Updated '{task_name}' (id {position}):"]
    for column, value in applied:
        display_val = value
        if column == "DUE DATE" and not pd.isna(pd.to_datetime(value, errors="coerce")):
            display_val = pd.to_datetime(value).strftime("%m/%d/%Y")
        summary_lines.append(f"  - {column}: {display_val}")
    await ctx.send("\n".join(summary_lines), delete_after=90)


@bot.command(
    name="delete_task",
    help="Delete an open task by its id from !L to_do_list. Historical completed rows are not touched."
)
async def delete_task(ctx, task_id):
    try:
        position = int(task_id)
    except ValueError:
        await ctx.send("Task id must be the number shown in `!L to_do_list`.", delete_after=60)
        return

    try:
        to_do_list_df = db.load_tasks_df()
    except Exception as e:
        await ctx.send(f"Could not read to-do list: {e}", delete_after=60)
        return

    df_index, target_row = resolve_task_index_from_position(to_do_list_df, position)
    if df_index is None:
        await ctx.send(f"No open task at position {position}. Run `!L to_do_list` to see current ids.", delete_after=60)
        return

    task_name = str(target_row["TASK"])
    to_do_list_df = to_do_list_df.drop(index=df_index)

    try:
        db.save_tasks_df(to_do_list_df)
    except Exception as e:
        await ctx.send(f"Could not save after delete: {e}", delete_after=60)
        return

    await ctx.send(f"Deleted open task '{task_name}' (id {position}). Past completions of this task remain in history.", delete_after=60)


# %%
# FOLLOW-UP TASK COMMANDS
# When a trigger task is completed via the Complete button, every mapping with a matching
# TRIGGER_TASK auto-creates a new task in the to-do list (e.g. Do Dishes -> Put up Dishes).

@bot.hybrid_command(
    name="add_follow_up",
    description="Auto-create a follow-up task when a trigger task is completed (e.g. Do Dishes -> Put up Dishes)",
)
@app_commands.describe(
    trigger_task="The task name that, when completed, triggers the follow-up",
    follow_up_task="The follow-up task to auto-create",
    catagory="Category for the follow-up task (defaults to trigger task's category)",
    priority="Priority 1-10 for the follow-up (default 1)",
    due_offset_days="Days from completion to set as due date (optional)",
    estimated_time="Estimated hours for the follow-up (optional)",
    relevant_link="Link to attach to the follow-up (optional)",
)
async def add_follow_up(
    ctx,
    trigger_task,
    follow_up_task,
    catagory=None,
    priority=1,
    due_offset_days=None,
    estimated_time=None,
    relevant_link=None,
):
    try:
        new_row = add_follow_up_mapping(
            trigger_task=trigger_task,
            follow_up_task=follow_up_task,
            catagory=catagory,
            priority=priority,
            due_offset_days=due_offset_days,
            estimated_time=estimated_time,
            relevant_link=relevant_link,
        )
    except ValueError as exc:
        await ctx.send(f"Could not add follow-up: {exc}", delete_after=60)
        return
    except Exception as e:
        await ctx.send(f"Something went wrong: {e}", delete_after=60)
        return

    due_note = f" (due +{int(new_row['DUE_OFFSET_DAYS'])}d)" if pd.notna(new_row.get("DUE_OFFSET_DAYS")) else ""
    await ctx.send(
        f"Added follow-up: '{new_row['TRIGGER_TASK']}' → '{new_row['FOLLOW_UP_TASK']}'{due_note}",
        delete_after=60,
    )


@bot.command(name="follow_ups", help="List all configured trigger → follow-up task mappings")
async def follow_ups(ctx):
    try:
        df = load_follow_ups()
    except Exception as e:
        await ctx.send(f"Could not read follow-up mappings: {e}", delete_after=60)
        return

    embed = discord.Embed(title="Follow-Up Task Mappings", color=0xE67E22)
    if df.empty:
        embed.add_field(
            name="No mappings configured",
            value=f"Use `{command_prefix}add_follow_up <trigger> <follow_up>` to create one.",
            inline=False,
        )
        await ctx.send(embed=embed, delete_after=120)
        return

    for count, (_, row) in enumerate(df.iterrows()):
        if count >= 20:
            break
        catagory = row.get("CATAGORY")
        priority = row.get("PRIORITY")
        offset = row.get("DUE_OFFSET_DAYS")
        lines = [f"Trigger: {row['TRIGGER_TASK']}"]
        if catagory and not pd.isna(catagory):
            lines.append(f"Category: {catagory}")
        if priority is not None and not pd.isna(priority):
            lines.append(f"Priority: {int(priority)}")
        if offset is not None and not pd.isna(offset):
            lines.append(f"Due offset: +{int(offset)} day(s) from completion")
        embed.add_field(
            name=f"{count + 1}. → {row['FOLLOW_UP_TASK']}",
            value="\n".join(lines),
            inline=False,
        )

    if len(df) > 20:
        embed.set_footer(text=f"Showing first 20 of {len(df)} mappings.")
    else:
        embed.set_footer(text=f"Total mappings: {len(df)} | Delete with {command_prefix}delete_follow_up <id>")

    await ctx.send(embed=embed, delete_after=120)


@bot.command(name="delete_follow_up", help="Delete a follow-up mapping by id from !L follow_ups")
async def delete_follow_up(ctx, mapping_id):
    try:
        position = int(mapping_id)
    except ValueError:
        await ctx.send("Mapping id must be the number shown in `!L follow_ups`.", delete_after=60)
        return

    try:
        removed = delete_follow_up_mapping(position)
    except ValueError as exc:
        await ctx.send(str(exc), delete_after=60)
        return
    except Exception as e:
        await ctx.send(f"Could not delete mapping: {e}", delete_after=60)
        return

    await ctx.send(
        f"Deleted follow-up mapping: '{removed['TRIGGER_TASK']}' → '{removed['FOLLOW_UP_TASK']}'.",
        delete_after=60,
    )


@bot.command(
    name="tasks",
    help="Filter the to-do list. Usage: !L tasks field:value [field:value ...] (e.g. category:Health priority:>=7 due:week)"
)
async def tasks(ctx, *, filters: str = ""):
    try:
        to_do_list_df = db.load_tasks_df()
    except Exception as e:
        await ctx.send(f"Could not read to-do list: {e}", delete_after=60)
        return

    try:
        filter_tokens = parse_task_filter_tokens(filters)
        filtered_df = filter_tasks(to_do_list_df, filter_tokens)
    except ValueError as exc:
        allowed = ", ".join(sorted(set(FILTERABLE_TASK_FIELDS)))
        await ctx.send(f"Filter error: {exc}\nAllowed fields: {allowed}", delete_after=120)
        return

    filter_summary = " ".join(f"{k}:{v}" for k, v in filter_tokens) if filter_tokens else "(no filters)"
    total_matches = len(filtered_df)

    embed = discord.Embed(
        title=f"To-Do Search Results ({total_matches})",
        description=f"Filters: `{filter_summary}`",
        color=0x00FF00,
    )

    if total_matches == 0:
        embed.add_field(name="No matches", value="Try loosening your filters.", inline=False)
        await ctx.channel.send(embed=embed, delete_after=90)
        return

    display_df = filtered_df.head(20).loc[:, ["TASK", "PRIORITY", "STATUS", "DUE DATE", "RELEVANT LINK", "CATAGORY"]].astype(str)
    for count, (_, row) in enumerate(display_df.iterrows()):
        task_name = row["TASK"]
        due = row["DUE DATE"] if row["DUE DATE"] != "NaT" else "No due date"
        link = row["RELEVANT LINK"]
        link_md = f"[LINK]({link})" if link and link not in ("None", "nan") else "No link"
        value = (
            f"Priority: {row['PRIORITY']}\n"
            f"Status: {row['STATUS']}\n"
            f"Category: {row['CATAGORY']}\n"
            f"Due: {due}\n"
            f"{link_md}"
        )
        embed.add_field(name=f"{count + 1}. {task_name}", value=value, inline=False)

    if total_matches > 20:
        embed.set_footer(text=f"Showing first 20 of {total_matches} matches.")

    await ctx.channel.send(embed=embed, delete_after=120)


@bot.command(name="to_do_completion_visual", help="Post a 7-day to-do completion bar chart to the to-do channel")
async def to_do_completion_visual(ctx):
    to_do_list_channel = get_todo_channel()
    if not to_do_list_channel:
        await ctx.send("To-do channel not found. Please verify Channel_ID_to_do in config.", delete_after=60)
        return

    try:
        to_do_list_df = db.load_tasks_df()
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
        to_do_list_df = db.load_tasks_df()
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


@bot.hybrid_command(name="create_discipline_task", description="Add a task to the separate discipline tracker")
@app_commands.describe(
    task_name="Discipline task name",
    catagory="Task category",
    frequency_per_week="How many times per week (1-7)",
)
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
        discipline_df = db.load_discipline_df()
    except FileNotFoundError:
        discipline_df = discipline_row.iloc[0:0]

    updated_df = pd.concat([discipline_row, discipline_df], ignore_index=True)

    try:
        db.save_discipline_df(updated_df)
        await ctx.send("Added to separate discipline tracker.", delete_after=60)
    except Exception as e:
        await ctx.send(f"Something went wrong: {e}")


@bot.command(name = "discipline_list", help= "The separate discipline tracker list")
async def discipline_list(ctx):
    ensure_discipline_dataframe_exists()
    discipline_df = db.load_discipline_df()
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
        elif completion_date == current_date:
            streak += 1
            current_date = current_date - pd.Timedelta(days=1)
        else:
            break
    
    return streak


@bot.command(name = "log_discipline_completion", help= "Log a completed discipline item for data collection")
async def log_discipline_completion(ctx, task_name, completed_date=None):
    ensure_discipline_dataframe_exists()
    ensure_discipline_history_exists()

    discipline_df = db.load_discipline_df()
    task_match = discipline_df[discipline_df["TASK"].astype(str).str.lower() == str(task_name).strip().lower()]

    if task_match.empty:
        await ctx.send(f"Task not found in discipline tracker. Use {command_prefix}discipline_list to view tracked items.", delete_after=60)
        return

    task_row = task_match.iloc[0]
    canonical_task_name = str(task_row["TASK"])

    if completed_date in (None, ""):
        target_completed_date = datetime.datetime.now().date()
    else:
        try:
            target_completed_date = pd.to_datetime(completed_date).date()
        except Exception:
            await ctx.send("Invalid date format. Use YYYYMMDD (e.g., 20260511).", delete_after=60)
            return

    target_completed_date_normalized = pd.to_datetime(target_completed_date).normalize()

    if is_task_completed_on(canonical_task_name, target_completed_date_normalized):
        await ctx.send(
            f"'{canonical_task_name}' has already been logged for {target_completed_date_normalized.strftime('%m/%d/%Y')}.",
            delete_after=60,
        )
        return

    set_discipline_cell(canonical_task_name, target_completed_date_normalized, True)

    # Recompute and persist CURRENT_STREAK for convenience (display uses matrix-derived values).
    updated_completion_df = load_discipline_completion_df()
    new_streak = calculate_streak(canonical_task_name, updated_completion_df, reference_date=target_completed_date_normalized)
    discipline_df.loc[task_match.index, "CURRENT_STREAK"] = new_streak
    db.save_discipline_df(discipline_df)

    logged_date = target_completed_date_normalized.strftime("%m/%d/%Y")
    streak_msg = f" (Streak: {new_streak} day(s))" if new_streak > 0 else ""
    await ctx.send(f"Logged completion for '{canonical_task_name}' on {logged_date}.{streak_msg}", delete_after=60)


@bot.command(name = "deactivate_discipline_task", help= "Deactivate a discipline task (hide it from the list without deleting)")
async def deactivate_discipline_task(ctx, task_name):
    ensure_discipline_dataframe_exists()

    discipline_df = db.load_discipline_df()
    task_match = discipline_df[discipline_df["TASK"].astype(str).str.lower() == str(task_name).strip().lower()]

    if task_match.empty:
        await ctx.send(f"Task not found in discipline tracker. Use {command_prefix}discipline_list to view tracked items.", delete_after=60)
        return

    discipline_df.loc[task_match.index, "ACTIVE"] = False
    db.save_discipline_df(discipline_df)
    
    await ctx.send(f"Deactivated '{task_match.iloc[0]['TASK']}'. It will no longer appear in the active tracker.", delete_after=60)


@bot.command(name = "update_discipline_frequency", help= "Update the weekly frequency target for a discipline task")
async def update_discipline_frequency(ctx, task_name, new_frequency):
    ensure_discipline_dataframe_exists()

    discipline_df = db.load_discipline_df()
    task_match = discipline_df[discipline_df["TASK"].astype(str).str.lower() == str(task_name).strip().lower()]

    if task_match.empty:
        await ctx.send(f"Task not found in discipline tracker. Use {command_prefix}discipline_list to view tracked items.", delete_after=60)
        return

    try:
        new_frequency = int(new_frequency)
    except ValueError:
        await ctx.send("New frequency must be a number between 1 and 7.", delete_after=60)
        return

    if new_frequency < 1 or new_frequency > 7:
        await ctx.send("Frequency must be between 1 and 7.", delete_after=60)
        return

    old_frequency = int(task_match.iloc[0]["FREQUENCY_PER_WEEK"])
    discipline_df.loc[task_match.index, "FREQUENCY_PER_WEEK"] = new_frequency
    db.save_discipline_df(discipline_df)
    
    await ctx.send(f"Updated '{task_match.iloc[0]['TASK']}' frequency from {old_frequency} to {new_frequency} times per week.", delete_after=60)


@bot.command(name = "today_completions", help= "View discipline items you've logged as completed today")
async def today_completions(ctx, date=None):
    ensure_discipline_history_exists()

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

    history_df = read_discipline_history()
    embed = discord.Embed(
        title=f"Discipline Completions - {display_date}",
        description="Items logged as completed on this date.",
        color=0x3498DB,
    )

    if history_df.empty or target_date not in history_df.index:
        embed.add_field(name="No Completions Logged", value="No items logged for this date.", inline=False)
        await ctx.send(embed=embed, delete_after=120)
        return

    row = history_df.loc[target_date]
    completed_tasks = [task for task, val in row.items() if (not pd.isna(val)) and bool(val)]

    if not completed_tasks:
        embed.add_field(name="No Completions Logged", value="No items logged for this date.", inline=False)
        await ctx.send(embed=embed, delete_after=120)
        return

    # Pull category from discipline_list for nicer display
    try:
        discipline_df = db.load_discipline_df()
        cat_map = dict(
            zip(
                discipline_df["TASK"].astype(str).str.strip(),
                discipline_df["CATAGORY"].astype(str),
            )
        )
    except Exception:
        cat_map = {}

    for count, task_name in enumerate(completed_tasks[:20]):
        catagory = cat_map.get(str(task_name).strip(), "Discipline")
        embed.add_field(name=f"{count + 1}. {task_name}", value=f"Category: {catagory}", inline=False)

    if len(completed_tasks) > 20:
        embed.set_footer(text=f"Showing top 20 of {len(completed_tasks)} completions")
    else:
        embed.set_footer(text=f"Total logged: {len(completed_tasks)}")

    await ctx.send(embed=embed, delete_after=120)


@bot.command(name = "weekly_discipline_summary", help= "Weekly discipline progress vs frequency targets")
async def weekly_discipline_summary(ctx, week_start=None):
    ensure_discipline_dataframe_exists()
    ensure_discipline_history_exists()

    discipline_df = db.load_discipline_df()
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

    completion_df = load_discipline_completion_df()
    reference_day = min(today, end_date)
    report_df = build_discipline_insight_df(discipline_df, completion_df, start_date, end_date, reference_date=reference_day)

    total_target = int(report_df["FREQUENCY_PER_WEEK"].sum())
    total_actual = int(report_df["COMPLETIONS_THIS_WEEK"].sum())
    overall_percent = (min(total_actual / total_target, 1) * 100) if total_target > 0 else 0
    avg_consistency = round(float(report_df["CONSISTENCY_SCORE"].mean()), 1) if not report_df.empty else 0
    active_streaks = int((report_df["CURRENT_STREAK"] > 0).sum()) if not report_df.empty else 0

    embed = discord.Embed(
        title=f"Weekly Discipline Report ({start_date.strftime('%m/%d')} - {end_date.strftime('%m/%d')})",
        description="Progress against each task's weekly target frequency, with streak and consistency context.",
        color=0xF1C40F,
    )

    sorted_report = report_df.sort_values(by=["AT_RISK_THIS_WEEK", "FREQUENCY_PER_WEEK", "TASK"], ascending=[False, False, True])
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
        alert_line = "At risk this week" if bool(row["AT_RISK_THIS_WEEK"]) else "On pace"
        value = (
            f"Category: {catagory}\n"
            f"This Week: {actual}/{target}{extra}\n"
            f"Progress: {percent}%\n"
            f"Current Streak: {int(row['CURRENT_STREAK'])} | Best: {int(row['LONGEST_STREAK'])}\n"
            f"4-Week Consistency: {row['CONSISTENCY_SCORE']}%\n"
            f"Alert: {alert_line}"
        )
        embed.add_field(name=f"{count + 1}. {task_name}", value=value, inline=False)
        count += 1

    embed.add_field(name="Alerts", value=build_discipline_alert_summary(report_df, for_current_week=end_date >= today), inline=False)
    embed.set_footer(
        text=(
            f"Overall: {total_actual}/{total_target} ({round(overall_percent, 1)}%) | "
            f"Avg consistency: {avg_consistency}% | Active streaks: {active_streaks} | "
            f"Use {command_prefix}weekly_discipline_summary YYYYMMDD"
        )
    )
    await ctx.send(embed=embed, delete_after=180)


@bot.command(name="discipline_streaks", help="Current streaks, longest streaks, and recent discipline consistency")
async def discipline_streaks(ctx):
    ensure_discipline_dataframe_exists()
    ensure_discipline_history_exists()

    discipline_df = db.load_discipline_df()
    if discipline_df.empty:
        await ctx.send("No discipline tasks are currently tracked.", delete_after=60)
        return

    completion_df = load_discipline_completion_df()
    today = pd.to_datetime(datetime.datetime.now().date()).normalize()
    week_start = today - pd.Timedelta(days=int(today.weekday()))
    week_end = week_start + pd.Timedelta(days=6)
    report_df = build_discipline_insight_df(discipline_df, completion_df, week_start, week_end, reference_date=today)

    embed = discord.Embed(
        title="Discipline Streaks",
        description="Current streaks, best streaks, and 4-week consistency scores.",
        color=0x9B59B6,
    )

    sorted_report = report_df.sort_values(by=["CURRENT_STREAK", "CONSISTENCY_SCORE", "LONGEST_STREAK", "TASK"], ascending=[False, False, False, True])
    count = 0
    for _, row in sorted_report.iterrows():
        if count >= 20:
            break
        embed.add_field(
            name=f"{count + 1}. {row['TASK']}",
            value=(
                f"Category: {row['CATAGORY']}\n"
                f"Current Streak: {int(row['CURRENT_STREAK'])} day(s)\n"
                f"Longest Streak: {int(row['LONGEST_STREAK'])} day(s)\n"
                f"4-Week Consistency: {row['CONSISTENCY_SCORE']}%\n"
                f"This Week: {int(row['COMPLETIONS_THIS_WEEK'])}/{int(row['FREQUENCY_PER_WEEK'])}"
            ),
            inline=False,
        )
        count += 1

    embed.set_footer(text=build_discipline_alert_summary(report_df, for_current_week=True))
    await ctx.send(embed=embed, delete_after=180)


@bot.command(
    name="discipline_progress",
    aliases=["discipline_bar", "discipline_status"],
    help="Show weekly partial-credit progress bars for each discipline (X/Y with bar + percent).",
)
async def discipline_progress(ctx, reference_date=None):
    ensure_discipline_dataframe_exists()
    ensure_discipline_history_exists()

    if reference_date in (None, ""):
        reference_day = pd.to_datetime(datetime.datetime.now().date()).normalize()
    else:
        try:
            reference_day = pd.to_datetime(reference_date).normalize()
        except Exception:
            await ctx.send("Invalid date format. Use YYYYMMDD (e.g., 20260511).", delete_after=60)
            return

    discipline_df = db.load_discipline_df()
    completion_df = load_discipline_completion_df()
    embed = build_discipline_progress_embed(discipline_df, completion_df, reference_date=reference_day)

    await ctx.send(embed=embed, delete_after=180)


@bot.command(
    name="at_risk",
    aliases=["discipline_at_risk", "midweek_check"],
    help="List disciplines that won't hit their weekly target at current pace (plus a 'tight' tier).",
)
async def at_risk(ctx, reference_date=None):
    ensure_discipline_dataframe_exists()
    ensure_discipline_history_exists()

    if reference_date in (None, ""):
        reference_day = pd.to_datetime(datetime.datetime.now().date()).normalize()
    else:
        try:
            reference_day = pd.to_datetime(reference_date).normalize()
        except Exception:
            await ctx.send("Invalid date format. Use YYYYMMDD (e.g., 20260511).", delete_after=60)
            return

    discipline_df = db.load_discipline_df()
    completion_df = load_discipline_completion_df()
    embed = build_discipline_at_risk_embed(discipline_df, completion_df, reference_date=reference_day)

    await ctx.send(embed=embed, delete_after=180)


@bot.command(name="daily_discipline_visual", aliases=["discipline_daily_visual"], help="Post today's discipline goal-status visual to the discipline channel")
async def daily_discipline_visual(ctx):
    ensure_discipline_dataframe_exists()
    ensure_discipline_history_exists()

    try:
        await ctx.message.delete()
    except Exception:
        pass

    discipline_channel = get_discipline_channel()
    if not discipline_channel:
        await ctx.send("Discipline channel not found. Please verify Channel_ID_discipline in config.", delete_after=60)
        return

    discipline_df = db.load_discipline_df()
    if discipline_df.empty:
        await ctx.send("No discipline tasks are currently tracked.", delete_after=60)
        return

    today = pd.to_datetime(datetime.datetime.now().date()).normalize()
    week_start = today - pd.Timedelta(days=int(today.weekday()))
    week_end = week_start + pd.Timedelta(days=6)

    completion_df = load_discipline_completion_df()
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
    ensure_discipline_history_exists()

    try:
        await ctx.message.delete()
    except Exception:
        pass

    discipline_channel = get_discipline_channel()
    if not discipline_channel:
        await ctx.send("Discipline channel not found. Please verify Channel_ID_discipline in config.", delete_after=60)
        return

    discipline_df = db.load_discipline_df()
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
    completion_df = load_discipline_completion_df()
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


@bot.command(
    name="discipline_category_rollup",
    aliases=["category_rollup", "discipline_categories"],
    help="Post a weekly category-level adherence chart (e.g. Focus 90%, Health 60%) to the discipline channel.",
)
async def discipline_category_rollup(ctx, week_start=None):
    ensure_discipline_dataframe_exists()
    ensure_discipline_history_exists()

    try:
        await ctx.message.delete()
    except Exception:
        pass

    discipline_channel = get_discipline_channel()
    if not discipline_channel:
        await ctx.send("Discipline channel not found. Please verify Channel_ID_discipline in config.", delete_after=60)
        return

    discipline_df = db.load_discipline_df()
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

    completion_df = load_discipline_completion_df()
    rollup_df = build_discipline_category_rollup_df(discipline_df, completion_df, start_date, end_date)

    if rollup_df.empty:
        await ctx.send("No active discipline tasks to roll up.", delete_after=60)
        return

    total_target = int(rollup_df["TARGET_SUM"].sum())
    total_actual = int(rollup_df["ACTUAL_SUM"].sum())
    overall_pct = round(min(total_actual / total_target, 1) * 100, 1) if total_target > 0 else 0.0
    cat_count = len(rollup_df)
    strong = int((rollup_df["ADHERENCE_PERCENT"] >= 80).sum())
    slipping = int(((rollup_df["ADHERENCE_PERCENT"] >= 50) & (rollup_df["ADHERENCE_PERCENT"] < 80)).sum())
    off_track = int((rollup_df["ADHERENCE_PERCENT"] < 50).sum())

    subtitle = (
        f"Week {start_date.strftime('%m/%d')} - {end_date.strftime('%m/%d')} | "
        f"Categories: {cat_count} | Strong: {strong} | Slipping: {slipping} | Off: {off_track} | "
        f"Overall: {total_actual}/{total_target} ({overall_pct}%)"
    )
    chart = render_discipline_category_rollup_chart(
        rollup_df=rollup_df,
        chart_title="Discipline Category Adherence (Weekly)",
        subtitle=subtitle,
    )

    await discipline_channel.send(f"<@{user_id}>, Weekly discipline category rollup:", delete_after=300)
    await discipline_channel.send(
        file=discord.File(fp=chart, filename="discipline_category_rollup.png"),
        delete_after=300,
    )

    if ctx.channel.id != discipline_channel.id:
        await ctx.send("Posted the category rollup in the discipline channel.", delete_after=300)


@bot.command(
    name="discipline_heatmap",
    aliases=["heatmap", "discipline_activity"],
    help="Post a GitHub-style heatmap of daily discipline completions over the last N days (default 90).",
)
async def discipline_heatmap(ctx, days: int = 90, reference_date=None):
    ensure_discipline_dataframe_exists()
    ensure_discipline_history_exists()

    try:
        await ctx.message.delete()
    except Exception:
        pass

    discipline_channel = get_discipline_channel()
    if not discipline_channel:
        await ctx.send("Discipline channel not found. Please verify Channel_ID_discipline in config.", delete_after=60)
        return

    try:
        days = int(days)
    except Exception:
        await ctx.send("Invalid `days` value. Provide a positive integer (e.g., 90).", delete_after=60)
        return
    if days < 7:
        days = 7
    if days > 365:
        days = 365

    if reference_date in (None, ""):
        ref_day = pd.to_datetime(datetime.datetime.now().date()).normalize()
    else:
        try:
            ref_day = pd.to_datetime(reference_date).normalize()
        except Exception:
            await ctx.send("Invalid reference_date. Use YYYYMMDD (e.g., 20260511).", delete_after=60)
            return

    completion_df = load_discipline_completion_df()
    window_start = ref_day - pd.Timedelta(days=days - 1)

    if completion_df is None or completion_df.empty:
        active_days = 0
        total_completions = 0
        best_day_count = 0
    else:
        norm = completion_df.copy()
        norm["COMPLETED_DATE"] = pd.to_datetime(norm["COMPLETED_DATE"], errors="coerce").dt.normalize()
        norm = norm.dropna(subset=["COMPLETED_DATE"])
        in_range = norm[(norm["COMPLETED_DATE"] >= window_start) & (norm["COMPLETED_DATE"] <= ref_day)]
        if in_range.empty:
            active_days = 0
            total_completions = 0
            best_day_count = 0
        else:
            per_day = in_range.groupby("COMPLETED_DATE")["TASK"].nunique()
            active_days = int((per_day > 0).sum())
            total_completions = int(per_day.sum())
            best_day_count = int(per_day.max())

    active_pct = round((active_days / days) * 100, 1) if days > 0 else 0.0
    subtitle = (
        f"{window_start.strftime('%m/%d/%Y')} → {ref_day.strftime('%m/%d/%Y')} • "
        f"{days} days • Active days: {active_days} ({active_pct}%) • "
        f"Completions: {total_completions} • Best day: {best_day_count}"
    )

    chart = render_discipline_heatmap_chart(
        completion_df=completion_df,
        reference_date=ref_day,
        days=days,
        chart_title="Discipline Activity Heatmap",
        subtitle=subtitle,
    )

    await discipline_channel.send(
        f"<@{user_id}>, Discipline activity heatmap (last {days} days):",
        delete_after=300,
    )
    await discipline_channel.send(
        file=discord.File(fp=chart, filename="discipline_heatmap.png"),
        delete_after=300,
    )

    if ctx.channel.id != discipline_channel.id:
        await ctx.send("Posted the discipline heatmap in the discipline channel.", delete_after=300)


#%%
# This command updates the status of a task

    

#%%
# RUN THE BOT
bot.run(config['TOKEN'])


#%%
