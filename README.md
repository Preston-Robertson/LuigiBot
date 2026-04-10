# LuigiBot 🤖

A personal Discord bot for managing your to-do list directly from a Discord channel. Create tasks, track their progress, log hours, and get a daily morning summary — all without leaving Discord.

---

## Features

- **Create tasks** with rich metadata: category, group, subgroup, priority, due date, estimated time, and relevant links
- **View your to-do list** as a formatted embed, sorted by priority and due date
- **Interact with tasks via emoji reactions** — start, pause, or complete tasks with a single click
- **Automatic time tracking** — logs hours when you start (▶️) and pause (⏸️) a task
- **Recurring tasks** — define tasks that re-appear automatically after a set number of days
- **Daily morning summary** — posts your active to-do list to a designated channel every day at 8:00 AM EST

---

## Project Structure

```
LuigiBot/
├── luigi_bot_main.py      # Main bot logic: commands, events, scheduled tasks
├── required_functions.py  # Helper functions (e.g. task name extraction)
├── requirements.txt       # Python dependencies
├── config.json            # Bot configuration (not committed — see setup)
└── to_do_list/
    ├── to_do_list.pkl     # Persistent task storage
    └── recurring_tasks.pkl
```

---

## Prerequisites

- Python 3.9+
- A Discord bot token ([Discord Developer Portal](https://discord.com/developers/applications))
- The bot must have the following permissions in your server:
  - Send Messages
  - Read Message History
  - Add Reactions
  - Manage Messages (to delete processed messages)
  - Embed Links

---

## Setup

**1. Clone the repository**

```bash
git clone https://github.com/Leogi-ex/LuigiBot.git
cd LuigiBot
```

**2. Install dependencies**

```bash
pip install -r requirements.txt
```

**3. Create `config.json`**

Create a `config.json` file in the root directory with the following structure:

```json
{
  "TOKEN": "your-discord-bot-token",
  "Channel_ID": 123456789012345678,
  "Channel_ID_to_do": 123456789012345678,
  "User_ID": 123456789012345678
}
```

| Key | Description |
|-----|-------------|
| `TOKEN` | Your Discord bot token |
| `Channel_ID` | The default channel the bot posts to |
| `Channel_ID_to_do` | The channel used for to-do list messages |
| `User_ID` | Your Discord user ID (for daily summary mentions) |

**4. Initialize the data directory**

Create the task storage directory before running:

```bash
mkdir to_do_list
```

**5. Run the bot**

```bash
python luigi_bot_main.py
```

---

## Commands

### `/hello`
A simple test command. The bot greets you by mention.

---

### `/to_do_list` (or `!L to_do_list`)
Displays your current (non-completed) tasks as a numbered embed, sorted by priority then due date. React with a number emoji (1️⃣–9️⃣) to expand details on that task.

---

### `/create_task` (or `!L create_task`)
Creates a new task and adds it to your to-do list.

| Parameter | Required | Description |
|-----------|----------|-------------|
| `task_name` | ✅ | Name of the task |
| `catagory` | ✅ | Category (e.g. "Work", "Personal") |
| `group` | ➖ | High-level objective the task belongs to |
| `subgroup` | ➖ | Sub-group within the group |
| `relevant_link` | ➖ | A URL related to the task |
| `recurring` | ➖ | `True` if this task repeats (default: `False`) |
| `recurring_interval` | ➖ | How many days between recurrences (required if `recurring=True`) |
| `due_date` | ➖ | Due date — accepts `YYYYMMDD`, `today`/`td`, `tomorrow`/`tmw`, or `week`/`wk` |
| `priority` | ➖ | Priority 1–10 (10 = urgent, default: 1) |
| `estimated_time` | ➖ | Estimated hours of active work |

---

## Emoji Reactions

When a task embed is displayed, you can react to control it:

| Emoji | Action |
|-------|--------|
| Number (1️⃣–9️⃣) | Expand full details for that task |
| ▶️ | Mark task as **In Progress** and start the timer |
| ⏸️ | Pause the task (**Hiatus**) and log elapsed hours |
| ✅ | Mark task as **Completed** and finalize logged hours |

---

## Daily Summary

Every day at **8:00 AM EST**, LuigiBot automatically posts a summary of all active tasks to the configured to-do channel and pings you. At **7:45 AM EST**, it checks whether any recurring tasks are due to be re-added to the list.

---

## Task Statuses

Tasks move through the following states:

`Not Started` → `In Progress` → `Hiatus` → `Completed`

Other possible statuses: `Pending`, `Blocked`

---

## Dependencies

See `requirements.txt`. Key libraries:

- [`discord.py`](https://discordpy.readthedocs.io/) — Discord bot framework
- `pandas` — Task data storage and manipulation
- `pytz` — Timezone handling for scheduled messages

---

## License

This project does not currently specify a license. All rights reserved by the author.
