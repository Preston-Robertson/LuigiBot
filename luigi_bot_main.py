#%%
# IMPORTING LIBRARIES

# Discord
import discord
from discord.ext import commands

# General
import json
import os
import datetime
#import io

# For Slash Commands
from discord import app_commands
from discord import interactions

# For Data 
import pandas as pd





#%%
# CONFIG // INTIALIZING

# Loading BOT secrets
with open(f'Discord Bot\\LuigiBot\\config.json') as f:
    config = json.load(f)


# Set-up the TCGbothelper channel and command
bot = commands.Bot(command_prefix="!L ", intents=discord.Intents.all())

channel_id = config['Channel_ID']

path_for_to_do_list = "Discord Bot\\LuigiBot\\to_do_list\\to_do_list.pkl"



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

@bot.command()
async def hello(ctx):
    await ctx.send("Hello!")


#%%
# This Command Outputs the To-Do List

@bot.hybrid_command(name = "to_do_list", description= "The current list of non-completed to-do list action items")
#@app_commands.describe(to_do_list = "Please copy and paste the QR codes with no changes")
async def to_do_list(ctx):

    to_do_list_df = pd.read_pickle(path_for_to_do_list)

    filtered_df = to_do_list_df[to_do_list_df["STATUS"] != "Completed"]

    #embed = discord.Embed(title = "To Do List", description = "```\n" + to_do_list_df.loc[:, ["TASK", "PRIORITY", "STATUS", "DUE DATE", "RELEVANT LINK"]].to_markdown(index=False) + "\n```", color=0x00FF00)

    message = "```\n" + filtered_df.loc[:, ["TASK", "PRIORITY", "STATUS", "DUE DATE"]].astype(str).to_markdown(index=False, tablefmt="grid") + "\n```"

        

    #task = to_do_list_df['TASK'][0]

    await ctx.send(message)


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
        recurring_interval = "How often does this occur in hours, 1 week = 168 hours",
        due_date = "Is there a due date, format = 20130102",
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
    
    to_do_list_df = pd.read_pickle(path_for_to_do_list)

    combine = pd.concat([to_list_pd, to_do_list_df])

    try: 
        combine.to_pickle(path_for_to_do_list)
        await ctx.send("Added")
    except Exception as e:
        await ctx.send(f"Something went wrong: {e}")


#%%
# This command updates the status of a task


@bot.hybrid_command(name = "update_task", description = "This task to mark a task as completed or started")
@app_commands.describe(
    task_name = "The name of the task to start",
    status = "Change in Status, choose one: Starting, Pending, Blocked, Hiatus, Completed"
)
async def update_task(ctx, task_name, status = "Starting" ):

    to_do_list_df = pd.read_pickle(path_for_to_do_list)

    try:
        filtered_df = to_do_list_df[to_do_list_df["TASK"] == task_name]
    except Exception as e: 
        await ctx.send(f"Something went wrong: {e}")

    current_status = filtered_df["STATUS"][0]


    if current_status == "Not Started":
        if status == "Starting":
            to_do_list_df.loc[to_do_list_df["TASK"] == task_name, "START TIME"] = pd.to_datetime(datetime.datetime.now().isoformat(' ', 'seconds'))
            to_do_list_df.loc[to_do_list_df["TASK"] == task_name, "STATUS"] = "In Progress"
            to_do_list_df.to_pickle(path_for_to_do_list)
            await ctx.send(f"Updated '{task_name}' to 'Starting'")

        else:
            await ctx.send("Task must be started before changing status")

    else:
        if status == "Starting":
            await ctx.send(f"Task status was not set and {task_name} has already started")

        elif status == "Completed":
            to_do_list_df.loc[to_do_list_df["TASK"] == task_name, "COMPLTETED TIME"] = pd.to_datetime(datetime.datetime.now().isoformat(' ', 'seconds'))

            if pd.Timedelta(hours = filtered_df["LOGGED HOURS"][0]) != None:
                time_delta = filtered_df["COMPLETED TIME"] - filtered_df["START TIME"] + pd.Timedelta(hours = filtered_df["LOGGED HOURS"][0])
            else:
                time_delta = filtered_df["COMPLETED TIME"] - filtered_df["START TIME"]

            to_do_list_df.loc[to_do_list_df["TASK"] == task_name, "LOGGED HOURS"] = time_delta
            to_do_list_df.loc[to_do_list_df["TASK"] == task_name, "LOGGED HOURS"] = time_delta
            
            to_do_list_df.loc[to_do_list_df["TASK"] == task_name, "STATUS"] = "Completed"
            to_do_list_df.to_pickle(path_for_to_do_list)

            await ctx.send(f"Updated '{task_name}' to 'Completed'")
        
        elif status == "Pending" or "Blocked" or "Hiatus":
            to_do_list_df.loc[to_do_list_df["TASK"] == task_name, "STATUS"] = status
            to_do_list_df.to_pickle(path_for_to_do_list)
            await ctx.send(f"Updated '{task_name}' to '{status}'")



    

#%%
# RUN THE BOT


bot.run(config['TOKEN'])
# %%
