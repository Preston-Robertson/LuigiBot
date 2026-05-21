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
    path_for_to_do_list,
    path_for_recurring_tasks,
    path_for_discipline_list,
    path_for_discipline_completion_log,
    discipline_delete_after_seconds,
    discipline_daily_hour,
    discipline_daily_minute,
)
from bot_modules.task_helpers import (
    build_tracker_row,
    normalize_due_date,
    build_completed_task_series,
    get_open_task_mask,
    load_latest_task_row,
    pause_task_tracking,
    build_task_detail_embed,
)
from bot_modules.discipline_helpers import (
    build_discipline_row,
    build_discipline_completion_row,
    ensure_discipline_dataframe_exists,
    ensure_discipline_completion_log_exists,
    normalize_discipline_completion_df,
    build_discipline_weekly_counts,
    get_active_discipline_df,
    get_task_completed_today,
    calculate_streak,
    build_discipline_insight_df,
    build_discipline_alert_summary,
    build_discipline_daily_embed,
)
from bot_modules.chart_rendering import (
    render_completed_task_bar_chart,
    render_discipline_daily_goal_status_chart,
    render_discipline_weekly_progress_chart,
)
from bot_modules.ui_components import TaskSelectView, DisciplineTaskView


#%%
# BOT INITIALIZATION

bot = commands.Bot(command_prefix=command_prefix, intents=discord.Intents.all())

last_discipline_daily_date = None
last_discipline_visual_date = None
last_todo_visual_date = None
last_todo_weekly_visual_date = None


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
                f"`/create_discipline_task` or `{command_prefix}create_discipline_task` — Add a discipline item (task name, category, frequency/week 1-7)\n"
                f"`{command_prefix}discipline_list` — View all tracked discipline items\n"
                f"`{command_prefix}log_discipline_completion` — Log completion of a discipline task (for data collection)\n"
                f"`{command_prefix}today_completions` — View today's logged discipline completions (or any date)\n"
                f"`{command_prefix}weekly_discipline_summary` — Weekly progress report vs frequency targets\n"
                f"`{command_prefix}discipline_streaks` — Current streaks, best streaks, and 4-week consistency scores\n"
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
    global last_discipline_visual_date
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

        if last_discipline_visual_date != now.date():
            discipline_channel = get_discipline_channel()
            if discipline_channel:
                try:
                    ensure_discipline_dataframe_exists()
                    ensure_discipline_completion_log_exists()

                    discipline_df = pd.read_pickle(path_for_discipline_list)
                    completion_df = pd.read_pickle(path_for_discipline_completion_log)

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
    ensure_discipline_completion_log_exists()

    discipline_df = pd.read_pickle(path_for_discipline_list)
    task_match = discipline_df[discipline_df["TASK"].astype(str).str.lower() == str(task_name).strip().lower()]

    if task_match.empty:
        await ctx.send(f"Task not found in discipline tracker. Use {command_prefix}discipline_list to view tracked items.", delete_after=60)
        return

    task_row = task_match.iloc[0]
    catagory = str(task_row["CATAGORY"])

    if completed_date in (None, ""):
        target_completed_date = datetime.datetime.now().date()
    else:
        try:
            target_completed_date = pd.to_datetime(completed_date).date()
        except Exception:
            await ctx.send("Invalid date format. Use YYYYMMDD (e.g., 20260511).", delete_after=60)
            return

    target_completed_date_normalized = pd.to_datetime(target_completed_date).normalize()
    
    # Check for duplicate entry
    completion_df = pd.read_pickle(path_for_discipline_completion_log)
    duplicate_check = completion_df[
        (completion_df["TASK"].astype(str).str.lower() == str(task_name).strip().lower())
        & (completion_df["COMPLETED_DATE"] == target_completed_date_normalized)
    ]
    
    if not duplicate_check.empty:
        await ctx.send(f"'{task_row['TASK']}' has already been logged for {target_completed_date_normalized.strftime('%m/%d/%Y')}.", delete_after=60)
        return

    completion_row = build_discipline_completion_row(task_name=task_row["TASK"], catagory=catagory, completed_date=target_completed_date)

    try:
        completion_df = pd.read_pickle(path_for_discipline_completion_log)
    except FileNotFoundError:
        completion_df = completion_row.iloc[0:0]

    updated_completion_df = pd.concat([completion_df, completion_row], ignore_index=True)
    updated_completion_df.to_pickle(path_for_discipline_completion_log)
    
    # Update streak for this task
    new_streak = calculate_streak(task_row["TASK"], updated_completion_df, reference_date=target_completed_date)
    discipline_df.loc[task_match.index, "CURRENT_STREAK"] = new_streak
    discipline_df.to_pickle(path_for_discipline_list)

    logged_date = pd.to_datetime(completion_row["COMPLETED_DATE"].iloc[0]).strftime("%m/%d/%Y")
    streak_msg = f" (Streak: {new_streak} day(s))" if new_streak > 0 else ""
    await ctx.send(f"Logged completion for '{task_row['TASK']}' on {logged_date}.{streak_msg}", delete_after=60)


@bot.command(name = "deactivate_discipline_task", help= "Deactivate a discipline task (hide it from the list without deleting)")
async def deactivate_discipline_task(ctx, task_name):
    ensure_discipline_dataframe_exists()

    discipline_df = pd.read_pickle(path_for_discipline_list)
    task_match = discipline_df[discipline_df["TASK"].astype(str).str.lower() == str(task_name).strip().lower()]

    if task_match.empty:
        await ctx.send(f"Task not found in discipline tracker. Use {command_prefix}discipline_list to view tracked items.", delete_after=60)
        return

    discipline_df.loc[task_match.index, "ACTIVE"] = False
    discipline_df.to_pickle(path_for_discipline_list)
    
    await ctx.send(f"Deactivated '{task_match.iloc[0]['TASK']}'. It will no longer appear in the active tracker.", delete_after=60)


@bot.command(name = "update_discipline_frequency", help= "Update the weekly frequency target for a discipline task")
async def update_discipline_frequency(ctx, task_name, new_frequency):
    ensure_discipline_dataframe_exists()

    discipline_df = pd.read_pickle(path_for_discipline_list)
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
    discipline_df.to_pickle(path_for_discipline_list)
    
    await ctx.send(f"Updated '{task_match.iloc[0]['TASK']}' frequency from {old_frequency} to {new_frequency} times per week.", delete_after=60)


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
    ensure_discipline_completion_log_exists()

    discipline_df = pd.read_pickle(path_for_discipline_list)
    if discipline_df.empty:
        await ctx.send("No discipline tasks are currently tracked.", delete_after=60)
        return

    completion_df = pd.read_pickle(path_for_discipline_completion_log)
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
