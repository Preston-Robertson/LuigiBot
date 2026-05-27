# LuigiBot

A personal Discord bot for managing a to-do list and a separate discipline tracker directly from Discord.

## Features

- Create and manage to-do tasks with metadata (category, group, due date, priority, links, recurring cadence)
- View active tasks in a numbered embed and use buttons to start, pause, complete, or push to the weekend
- Track logged time as tasks move through statuses
- Auto re-add recurring tasks each morning when due
- Send daily to-do summaries and completed-task recaps
- Maintain a separate discipline tracker dataframe and completion log
- Surface discipline streaks, best streaks, 4-week consistency scores, and missed-target alerts
- View weekly partial-credit progress bars (X-of-Y with bar + percent) for each discipline
- Generate a weekly category-level adherence chart (e.g. Focus 90%, Health 60%)
- Receive an automatic midweek nudge listing disciplines that won't hit their weekly target at current pace
- Visualize the last 90 days of discipline activity as a GitHub-style heatmap
- Send a nightly discipline check-in with numbered buttons for quick logging

## Project Structure

```text
LuigiBot/
|-- main.py                       # Bot instance, commands, scheduler, event handlers
|-- bot_modules/                  # Helper package
|   |-- __init__.py
|   |-- bot_config.py             # Shared config (paths, channel IDs, prefix)
|   |-- chart_rendering.py        # Visual theme + all chart rendering functions
|   |-- discipline_helpers.py     # Discipline data processing, streaks, embeds
|   |-- task_helpers.py           # To-do row builders, series builder, task embeds
|   |-- ui_components.py          # Discord Button/View classes
|   `-- required_functions.py     # Utility: extract_task_name
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
  "Discipline_At_Risk_Weekday": 3,
  "Discipline_At_Risk_Hour": 17,
  "Discipline_At_Risk_Minute": 0,
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
- `!L edit_task <id> field=value [field=value ...]`
- `!L delete_task <id>`
- `!L tasks [field:value ...]`

Editable fields for `edit_task`: `task_name`, `priority`, `due_date`, `category` (alias `catagory`), `group`, `subgroup`, `link`, `status`, `estimated_time`.

- `due_date` accepts `today` / `tmw` / `wk` / `YYYYMMDD`, or `none` to clear.
- `status` must be one of: `Not Started`, `In Progress`, `Pending`, `Blocked`, `Hiatus`, `Completed`.
- Wrap multi-word values in double quotes (e.g. `task_name="Refactor parser"`).
- `<id>` is the number shown next to a task by `!L to_do_list`.

Filter syntax for `tasks` — combine any of:

- `task:<substring>` / `category:<substring>` / `group:<substring>` / `subgroup:<substring>`
- `priority:>=7` (operators: `>=`, `<=`, `>`, `<`, `=`; bare number = equals)
- `status:<substring>` (e.g. `status:progress`)
- `due:today` / `due:tmw` / `due:week` / `due:overdue` / `due:none` / `due:any` / `due:YYYYMMDD` (also accepts `>= <= > <`)
- `link:any` / `link:none` / `link:<substring>`
- `include:completed` to also include completed rows (open-only by default)

### Discipline Commands (Prefix Only)

- `!L create_discipline_task <task_name> <catagory> <frequency_per_week>`
- `!L discipline_list`
- `!L log_discipline_completion <task_name> [completed_date]`
- `!L today_completions [date]`
- `!L weekly_discipline_report [week_start]`
- `!L discipline_streaks`
- `!L discipline_progress [reference_date]`
- `!L discipline_category_rollup [week_start]`
- `!L at_risk [reference_date]`
- `!L discipline_heatmap [days] [reference_date]`

`completed_date` / `date` / `week_start` format: `YYYYMMDD` (for example, `20260512`).

## Quick Start Examples

Use these as copy/paste examples once the bot is running.

```text
# To-do (hybrid commands)
/to_do_list
!L to_do_list

/create_task task_name:Gym catagory:Health priority:7 due_date:today
!L create_task Gym Health None None None False None today 7 1.5

# Edit / delete an existing open task (id from `!L to_do_list`)
!L edit_task 3 priority=9 due_date=tmw
!L edit_task 3 task_name="Deep Work Block" link=https://example.com
!L delete_task 3

# Search / filter open tasks
!L tasks category:Health
!L tasks priority:>=7 due:week
!L tasks group:"100 percent" status:progress
!L tasks due:overdue
!L tasks include:completed task:gym

# Discipline (prefix-only commands)
!L create_discipline_task "Deep Work" Focus 5
!L discipline_list
!L log_discipline_completion "Deep Work"
!L today_completions
!L today_completions 20260512
!L weekly_discipline_report
!L weekly_discipline_report 20260512
!L discipline_progress
!L discipline_progress 20260512
!L discipline_category_rollup
!L discipline_category_rollup 20260512
!L at_risk
!L discipline_heatmap
!L discipline_heatmap 60
```

Tips:

- For prefix commands, wrap multi-word task names in double quotes.
- If you skip a date for `today_completions`, LuigiBot uses today.

## Task Interaction

When you run the to-do list command, LuigiBot shows numbered task buttons. Selecting a task opens action buttons:

- Complete
- Start
- Pause
- Weekend (defer the task to the upcoming Saturday)

## Scheduled Events (ET)

- 7:45 AM: Check and re-add due recurring to-do tasks
- 8:00 AM: Daily active to-do summary
- 11:00 PM: Tasks completed today summary + completed-task visual
- 11:15 PM: Discipline nightly reminder with numbered completion buttons
- 11:30 PM: 15-minute post check-in discipline goal-status snapshot
- 5:00 PM Thursday: Midweek at-risk discipline nudge (configurable via `Discipline_At_Risk_*` keys)

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

## Potential Future Features

- **Per-day quantity logging**: change the discipline history matrix from `True/False/NA` to `int/NA` so a single day can record multiple units (e.g. 2 deep-work blocks counts as 2 toward a weekly target of 5). This is a larger change — it requires migrating existing data, updating the button UI to support `+1` / `-1`, and switching all weekly aggregations from `nunique` to `sum`.
- **Natural-language task input**: a `!L nl <text>` command that parses free-form input like `Gym tomorrow 7p #Health !8 ~30m` into the existing task fields (`TASK`, `DUE_DATE`, `PRIORITY`, `CATAGORY`, `ESTIMATED_DURATION`, `LINK`, `RECURRING_FREQUENCY`). Tier 1 would be a regex/keyword parser (`#cat`, `!priority`, `~duration`, date/time words, URLs) with a Confirm/Cancel preview embed; Tier 2 could add a date library like `dateparser`; Tier 3 could route to an LLM for fully free-form text. Deferred — the structured `add_task` flow is currently sufficient.
