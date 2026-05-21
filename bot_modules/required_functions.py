import pandas as pd
import re
import discord

def extract_task_name(message):
        # try embed title first
        if message.embeds:
            embed = message.embeds[0]
            if embed.title and embed.title not in ("To Do List", "Task"):
                return embed.title
            if embed.fields:
                # field name can be "1. Task name" or just the task name
                name = embed.fields[0].name
                # strip leading numbering (e.g. "1. ")
                return re.sub(r'^\s*\d+\.\s*', '', name)
        # fallback to message content (short)
        if message.content:
            return message.content.splitlines()[0][:200]
        return None