# LuigiBot

A personal Discord bot for managing a to-do list and a separate discipline tracker directly from Discord.

## Features

- Create and manage to-do tasks with metadata (category, group, due date, priority, links, recurring cadence)
- View active tasks in a numbered embed and use buttons to start, pause, complete, snooze for 1 hour, move to tomorrow, or push to the weekend
- Track logged time as tasks move through statuses
- Auto re-add recurring tasks each morning when due
- Send daily to-do summaries and completed-task recaps
- Maintain a separate discipline tracker dataframe and completion log
- Surface discipline streaks, best streaks, 4-week consistency scores, and missed-target alerts
- Send a nightly discipline check-in with numbered buttons for quick logging

## Project Structure

```text
LuigiBot/
|-- main.py                  # Bot instance, commands, scheduler, event handlers
|-- bot_config.py            # Shared config (paths, channel IDs, prefix)
|-- chart_rendering.py       # Visual theme + all chart rendering functions
|-- discipline_helpers.py    # Discipline data processing, streaks, embeds
|-- task_helpers.py          # To-do row builders, series builder, task embeds
|-- ui_components.py         # Discord Button/View classes
|-- required_functions.py    # Utility: extract_task_name
|-- requirements.txt
|-- config.json
`-- to_do_list/
    |-- to_do_list.pkl
    |-- recurring_tasks.pkl
    |-- discipline_list.pkl
    `-- discipline_completion_log.pkl
```

## Prerequisites

- Python 3.9+
- A Discord bot token from the Discord Developer Portal
- Bot permissions:
  - Send Messages
  - Read Message History
  - Embed Links
  - Use Application Commands

## Setup

1. Install dependencies.

```bash
pip install -r requirements.txt
```

2. Create `config.json` in the project root.

```json
{
  "APPLICATION_ID": 123456789012345678,
  "PUBLIC_KEY": "your-public-key",
  "TOKEN": "your-discord-bot-token",
  "Channel_ID": 123456789012345678,
  "Channel_ID_to_do": 123456789012345678,
  "Channel_ID_discipline": 123456789012345678,
  "Discipline_List_Path": "to_do_list\\discipline_list.pkl",
  "Discipline_Completion_Log_Path": "to_do_list\\discipline_completion_log.pkl",
  "Discipline_Delete_After_Seconds": 7200,
  "Discipline_Daily_Hour": 23,
  "Discipline_Daily_Minute": 15,
  "User_ID": 123456789012345678
}
```

3. Ensure the data folder exists.

```bash
mkdir to_do_list
```

4. Run the bot.

```bash
python main.py
```

## Command Activation

- Prefix commands use `!L `.
- To-do commands are hybrid and can be run as slash or prefix commands.
- Discipline commands are prefix-only to reduce slash command clutter.

## Commands

### To-Do Commands

- `/hello`
- `/to_do_list` or `!L to_do_list`
- `/create_task` or `!L create_task`

### Discipline Commands (Prefix Only)

- `!L create_discipline_task <task_name> <catagory> <frequency_per_week>`
- `!L discipline_list`
- `!L log_discipline_completion <task_name> [completed_date]`
- `!L today_completions [date]`
- `!L weekly_discipline_report [week_start]`
- `!L discipline_streaks`

`completed_date` / `date` / `week_start` format: `YYYYMMDD` (for example, `20260512`).

## Quick Start Examples

Use these as copy/paste examples once the bot is running.

```text
# To-do (hybrid commands)
/to_do_list
!L to_do_list

/create_task task_name:Gym catagory:Health priority:7 due_date:today
!L create_task Gym Health None None None False None today 7 1.5

# Discipline (prefix-only commands)
!L create_discipline_task "Deep Work" Focus 5
!L discipline_list
!L log_discipline_completion "Deep Work"
!L today_completions
!L today_completions 20260512
!L weekly_discipline_report
!L weekly_discipline_report 20260512
```

Tips:

- For prefix commands, wrap multi-word task names in double quotes.
- If you skip a date for `today_completions`, LuigiBot uses today.

## Task Interaction

When you run the to-do list command, LuigiBot shows numbered task buttons. Selecting a task opens action buttons:

- Complete
- Start
- Pause

## Scheduled Events (ET)

- 7:45 AM: Check and re-add due recurring to-do tasks
- 8:00 AM: Daily active to-do summary
- 11:00 PM: Tasks completed today summary + completed-task visual
- 11:15 PM: Discipline nightly reminder with numbered completion buttons
- 11:30 PM: 15-minute post check-in visuals (to-do completion snapshot + discipline goal-status snapshot)

## Discipline Data Model

Discipline active list (`discipline_list.pkl`):

- `TASK`
- `CATAGORY`
- `FREQUENCY_PER_WEEK`

Discipline completion log (`discipline_completion_log.pkl`):

- `TASK`
- `CATAGORY`
- `COMPLETED_DATE`
- `LOGGED_AT`

## Notes

- Nightly discipline reminders auto-delete after `Discipline_Delete_After_Seconds`.
- Startup message includes command activation details so usage is visible at boot.
