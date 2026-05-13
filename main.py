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
#import io

# For Slash Commands
from discord import app_commands
from discord import interactions

# For Data 
from matplotlib import lines
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
bot = commands.Bot(command_prefix="!L ", intents=discord.Intents.all())

channel_id = config['Channel_ID']
user_id = config['User_ID']

path_for_to_do_list = "to_do_list\\to_do_list.pkl"
path_for_recurring_tasks = "to_do_list\\recurring_tasks.pkl"

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
    
    send_daily_message.start()

    if luigi_channel:
        await luigi_channel.send("I'm Ready")
    else:
        print("Channel not found.")
    # Once bot start-up is done, it will send "I'm Ready"


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
    

    
    if due_date == "Today" or due_date == "today" or due_date == "td" or due_date == "TD":
        due_date = datetime.datetime.now().date()

    elif due_date == "Tomorrow" or due_date == "tomorrow" or due_date == "tmw" or due_date == "TMw":
        due_date = datetime.datetime.now().date() + datetime.timedelta(days=1)

    elif due_date == "Week" or due_date == "week" or due_date == "WK" or due_date == "wk":
        due_date = datetime.datetime.now().date() + datetime.timedelta(weeks=1)

    to_list_pd = pd.DataFrame(
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
        "STATUS": pd.Categorical(["Not Started"], 
                                 categories = [
                                     "Not Started",
                                     "In Progress",
                                     "Pending",
                                     "Blocked",
                                     "Hiatus",
                                     "Completed"
                                               ], 
                                 ordered= True),
        "START TIME": None,
        "ESTIMATED TIME": estimated_time,
        "LOGGED HOURS": 0,
        "COMPLETED": False,
        "COMPLETED TIME": None})
    
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


#%%
# This command updates the status of a task

    

#%%
# RUN THE BOT
bot.run(config['TOKEN'])


#%%
