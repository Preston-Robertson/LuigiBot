#%%
# IMPORTING LIBRARIES

# Discord
import discord
from discord.ext import commands, tasks

# General
import json
import os
import datetime
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

number_emojis = ["1️⃣","2️⃣","3️⃣","4️⃣","5️⃣","6️⃣","7️⃣","8️⃣","9️⃣"]



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



#%%
@bot.event
async def on_reaction_add(reaction, user):
    # Ignore reactions from the bot itself
    if user.bot:
        return
    
    luigi_channel = bot.get_channel(channel_id)
    #"{reaction.message.content}"

    try: 
        to_do_list_channel = bot.get_channel(config['Channel_ID_to_do'])
    except:
        to_do_list_channel = luigi_channel

    emoji = str(reaction.emoji)

    if str(reaction.emoji) in number_emojis:
        embed = discord.Embed(title="Task", color=0x00FF00)
        #await to_do_list_channel.send(f'{user.name} reacted with {reaction.emoji} to the To Do List.')
        # Test line above

        idx = number_emojis.index(emoji)
        to_do_list_df = pd.read_pickle(path_for_to_do_list)
        filtered_df = to_do_list_df[to_do_list_df["STATUS"] != "Completed"]
        task_df = filtered_df.sort_values(by=["PRIORITY", "DUE DATE"], ascending=[False, True]).iloc[[idx]]
        
        for _, row in task_df.astype(str).iterrows():
            task_name = row["TASK"]
            embed = discord.Embed(title=task_name, color=0x00FF00)
            priority = row["PRIORITY"]
            task_creation = row["TASK CREATION"]
            catagory = row["CATAGORY"]
            group = row["GROUP"]   
            subgroup = row["SUB-GROUP"]
            starttime = row["START TIME"]
            estimated_time = row["ESTIMATED TIME"]
            logged_hours = row["LOGGED HOURS"]
            status = row["STATUS"]
            if row["DUE DATE"] != "NaT":
                due = row["DUE DATE"]
            else:
                due = "No due date"
            link = row["RELEVANT LINK"]
            link_md = f"[LINK]({link})" if link and link not in ("None", "nan") else "No link"
            value = f"""Priority: {priority}\nDue: {due}\nSubgroup: {subgroup}\nStart Time: {starttime}\nEstimated Time: {estimated_time}\nLogged Hours: {logged_hours}\nTask Created: {task_creation}\n{link_md}\n"""
            embed.add_field(name=status,value=value, inline=False)
        
        
        msg = await to_do_list_channel.send(embed=embed)
        await msg.add_reaction("✅")
        await msg.add_reaction("▶️")
        await msg.add_reaction("⏸️")


    

    # Check the emoji name
    if emoji == "✅":

        # Saving Task as Completed in the DataFrame
        task_name = extract_task_name(reaction.message) 
        to_do_list_df = pd.read_pickle(path_for_to_do_list)
        try:
            filtered_df = to_do_list_df[to_do_list_df["TASK"] == task_name]
        except Exception as e: 
            await to_do_list_channel.send(f"Something went wrong: {e}")

        to_do_list_df.loc[to_do_list_df["TASK"] == task_name, "COMPLTETED TIME"] = pd.to_datetime(datetime.datetime.now().isoformat(' ', 'seconds'))
        if to_do_list_df.loc[to_do_list_df["TASK"] == task_name, "LOGGED HOURS"][0] != None:
            time_delta = to_do_list_df.loc[to_do_list_df["TASK"] == task_name,"COMPLETED TIME"] - to_do_list_df.loc[to_do_list_df["TASK"] == task_name,"START TIME"] + pd.Timedelta(hours = filtered_df["LOGGED HOURS"][0])
        else:
            time_delta = to_do_list_df.loc[to_do_list_df["TASK"] == task_name,"COMPLETED TIME"] - to_do_list_df.loc[to_do_list_df["TASK"] == task_name,"START TIME"]
            to_do_list_df.loc[to_do_list_df["TASK"] == task_name, "LOGGED HOURS"] = time_delta

        to_do_list_df.loc[to_do_list_df["TASK"] == task_name, "STATUS"] = "Completed"
        to_do_list_df.to_pickle(path_for_to_do_list)


        # Creating the Complete Message.
        # 
        try: 
            to_do_list_df = pd.read_pickle(path_for_to_do_list)
            try:
                filtered_df = to_do_list_df[to_do_list_df["TASK"] == task_name]
            except Exception as e: 
                await to_do_list_channel.send(f"Something went wrong: {e}")

            to_do_list_df = pd.read_pickle(path_for_to_do_list)
            task_df = to_do_list_df[to_do_list_df["TASK"] == task_name]

            for _, row in task_df.astype(str).iterrows():
                task_name = row["TASK"]
                embed = discord.Embed(title=task_name, color=0x00FF00)
                priority = row["PRIORITY"]
                task_creation = row["TASK CREATION"]
                catagory = row["CATAGORY"]
                group = row["GROUP"]   
                subgroup = row["SUB-GROUP"]
                starttime = row["START TIME"]
                estimated_time = row["ESTIMATED TIME"]
                logged_hours = row["LOGGED HOURS"]
                status = row["STATUS"]
                if row["DUE DATE"] != "NaT":
                    due = row["DUE DATE"]
                else:
                    due = "No due date"
                link = row["RELEVANT LINK"]
                link_md = f"[LINK]({link})" if link and link not in ("None", "nan") else "No link"
                value = f"""Priority: {priority}\nDue: {due}\nSubgroup: {subgroup}\nStart Time: {starttime}\nEstimated Time: {estimated_time}\nLogged Hours: {logged_hours}\nTask Created: {task_creation}\n{link_md}\n"""
                embed.add_field(name=status,value=value, inline=False)


            msg = await to_do_list_channel.send(embed=embed) 

        except Exception as e:
            await to_do_list_channel.send(f"Error sending completed task: '{task_name}': {e}")
            await to_do_list_channel.send(f"Updated '{task_name}' to 'Completed'")
            # No longer needed

        await reaction.message.delete()




    if emoji == "▶️":
        task_name = extract_task_name(reaction.message) 
        to_do_list_df = pd.read_pickle(path_for_to_do_list)
        #current_status = to_do_list_df.loc[to_do_list_df["TASK"] == task_name, "STATUS"].iloc[0]
        #if current_status == "Not Started":
        #Not needed
        to_do_list_df.loc[to_do_list_df["TASK"] == task_name, "START TIME"] = pd.to_datetime(datetime.datetime.now().isoformat(' ', 'seconds'))
        to_do_list_df.loc[to_do_list_df["TASK"] == task_name, "STATUS"] = "In Progress"
        to_do_list_df.to_pickle(path_for_to_do_list)
        await to_do_list_channel.send(f"Updated '{task_name}' to 'In Progress'")
        await reaction.message.delete()


    if emoji == "⏸️":
        task_name = extract_task_name(reaction.message) 
        to_do_list_df = pd.read_pickle(path_for_to_do_list)

        if to_do_list_df.loc[to_do_list_df["TASK" == task_name, "STATUS"]] == 'In Progress':
            # Then log hours
            now = datetime.datetime.now()
            start = to_do_list_df.loc[to_do_list_df["TASK"] == task_name, "START TIME"] 
            logged_hours = (now - start).total_seconds() / 3600
            to_do_list_df.loc[to_do_list_df["TASK" == task_name, "LOGGED HOURS"]] = to_do_list_df.loc[to_do_list_df["TASK" == task_name, "LOGGED HOURS"]] + logged_hours

        to_do_list_df.loc[to_do_list_df["TASK"] == task_name, "STATUS"] = "Hiatus"
        to_do_list_df.to_pickle(path_for_to_do_list)
        await to_do_list_channel.send(f"Updated '{task_name}' to 'Hiatus'")
        await reaction.message.delete()
        # You can add further actions here, like assigning a role or sending a message



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
    
    msg = await ctx.channel.send(embed=embed, delete_after=60)  # Delete after 1 minute

    for i in range(min(count, len(number_emojis))):
        try:
            await msg.add_reaction(number_emojis[i])
        except Exception:
            pass



#%% 

# This command outputs the To-Do List Summary at 9:00am daily (Local time)

# Define the specific time for the message (e.g., 9:45 AM UTC)
# Use UTC or manage timezones carefully
daily_message_time = datetime.time(hour=0, minute=45, second=0)
weekly_completion_message_time = datetime.time(hour=1, minute=0, second=0)


@tasks.loop(time = daily_message_time)
async def send_daily_message():
    # Set your desired time (24-hour format)
    to_do_list_channel = bot.get_channel(config['Channel_ID_to_do'])
    #target_time = datetime.time(hour=9, minute=0)  # 9:00 AM
    
    now = datetime.datetime.now().time()
    then = now.datetime.timedelta(days=1)
    then.replace(hour=0, minute= 45)
    wait_time = (then-now).total_seconds

    await asyncio.sleep(wait_time)

    
    
    # Check if current time matches target time (within the minute)
    if to_do_list_channel:

        to_do_list_df = pd.read_pickle(path_for_to_do_list)

        filtered_df = to_do_list_df[to_do_list_df["STATUS"] != "Completed"]

        # Build a single embed, each task as a field (renders well on mobile & desktop)
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

    await to_do_list_channel.send(f"<@{user_id}>, Daily To-Do List Summary:")    
    await to_do_list_channel.send(embed=embed)



#%% 


weekly_completion_message_time = datetime.time(hour=1, minute=0, second=0)

@tasks.loop(time = weekly_completion_message_time)
async def send_weekly_completion_message():
    # Not sure if needed

    to_do_list_channel = bot.get_channel(config['Channel_ID_to_do'])
    
    now = datetime.datetime.now().time()
    then = now.datetime.timedelta(days=7)
    then.replace(hour=1)
    wait_time = (then-now).total_seconds

    asyncio.sleep(wait_time)





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
    
    to_do_list_df = pd.read_pickle(path_for_to_do_list)

    combine = pd.concat([to_list_pd, to_do_list_df])

    try: 
        combine.to_pickle(path_for_to_do_list)
        await ctx.send("Added", delete_after = '60') # Deleting Added message after 60s 
    except Exception as e:
        await ctx.send(f"Something went wrong: {e}")


#%%
# This command updates the status of a task

    

#%%
# RUN THE BOT
bot.run(config['TOKEN'])


#%%
