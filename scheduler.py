import discord
from discord.ext import commands, tasks
from discord import app_commands
from datetime import datetime, time, timedelta
import json
import pytz
import configparser
import argparse

#Argument parser
parser= argparse.ArgumentParser("Scheduler.py")
parser.add_argument("conf_file", help="Configuration file path to be used to customize execution.")
args = parser.parse_args()

#config parser, read in configuration argument named conf_file (first argument)
config=configparser.ConfigParser()
config.read(args.conf_file)

# Bot configuration
TOKEN = config['private']['token']  # Replace with your bot token
TIMEZONE = 'US/Pacific'  # Change this to your timezone

# Define intents
intents = discord.Intents.default()  # Enable default intents
intents.message_content = True  # Enable message content intent

class SchedulerBot(commands.Bot):
    def __init__(self):
        # Pass the intents to the bot
        super().__init__(command_prefix='!', intents=intents)
        self.scheduled_messages = {}
        
    async def setup_hook(self):
        try:
            with open('scheduled_messages.json', 'r') as f:
                self.scheduled_messages = json.load(f)
        except FileNotFoundError:
            self.scheduled_messages = {}
        
        # Start the background task
        self.check_scheduled_messages.start()
        
    def save_scheduled_messages(self):
        with open('scheduled_messages.json', 'w') as f:
            json.dump(self.scheduled_messages, f)

    @tasks.loop(minutes=1)
    async def check_scheduled_messages(self):
        current_time = datetime.now(pytz.timezone(TIMEZONE))
        current_time_str = current_time.strftime("%H:%M")
        current_day = current_time.strftime("%A").lower()  # Get current day (e.g., "monday")
        
        # Create a list of keys to delete after iteration
        keys_to_delete = []
        
        for schedule_id, schedule in list(self.scheduled_messages.items()):  # Iterate over a copy
            # Skip if the schedule is missing the 'day' field
            if 'day' not in schedule:
                print(f"Warning: Schedule {schedule_id} is missing the 'day' field. Skipping.")
                continue
            
            if schedule['day'].lower() == current_day and schedule['time'] == current_time_str:
                # Check if message was already sent today
                if schedule['last_run'] != current_time.date().isoformat():
                    channel = self.get_channel(schedule['channel_id'])
                    if channel:
                        await channel.send(schedule['message'])
                        
                        if schedule['repeat']:
                            # Update last run time
                            schedule['last_run'] = current_time.date().isoformat()
                        else:
                            # Mark non-repeating schedule for deletion
                            keys_to_delete.append(schedule_id)
                    
        # Delete non-repeating schedules after iteration
        for schedule_id in keys_to_delete:
            del self.scheduled_messages[schedule_id]
        
        # Save changes to the file
        if keys_to_delete:
            self.save_scheduled_messages()

# Create the bot instance with the defined intents
bot = SchedulerBot()

class ScheduleModal(discord.ui.Modal):
    def __init__(self, channel_name, server_name, server_id):
        super().__init__(title="Schedule Message")
        
        self.channel_name = channel_name
        self.server_name = server_name
        self.server_id = server_id
        
        self.message = discord.ui.TextInput(
            label="Message Content",
            style=discord.TextStyle.paragraph,
            placeholder="Enter your message here...",
            required=True,
            max_length=2000
        )
        
        self.day = discord.ui.TextInput(
            label="Day (e.g., Monday)",
            placeholder="Enter the day of the week (e.g., Monday)",
            required=True,
            max_length=10
        )
        
        self.time = discord.ui.TextInput(
            label="Time (HH:MM)",
            placeholder="Enter the time in 24-hour format (e.g., 14:30)",
            required=True,
            max_length=5
        )
        
        self.repeat = discord.ui.TextInput(
            label="Repeat Weekly? (yes/no)",
            placeholder="Type 'yes' or 'no'",
            required=True,
            max_length=3
        )
        
        self.add_item(self.message)
        self.add_item(self.day)
        self.add_item(self.time)
        self.add_item(self.repeat)

    async def on_submit(self, interaction: discord.Interaction):
        try:
            # Validate day
            day = self.day.value.lower()
            valid_days = ["monday", "tuesday", "wednesday", "thursday", "friday", "saturday", "sunday"]
            if day not in valid_days:
                await interaction.response.send_message(
                    "Invalid day! Please enter a valid day of the week (e.g., Monday).",
                    ephemeral=True
                )
                return
            
            # Validate time format
            try:
                hour, minute = map(int, self.time.value.split(':'))
                if not (0 <= hour <= 23 and 0 <= minute <= 59):
                    raise ValueError
            except ValueError:
                await interaction.response.send_message(
                    "Invalid time format! Please use HH:MM format (e.g., 14:30).",
                    ephemeral=True
                )
                return
            
            # Validate repeat option
            repeat = self.repeat.value.lower() == 'yes'
            
            # Create schedule entry
            schedule_id = str(len(bot.scheduled_messages) + 1)
            bot.scheduled_messages[schedule_id] = {
                'channel_id': interaction.channel_id,
                'channel_name': self.channel_name,
                'server_name': self.server_name,
                'server_id': self.server_id,
                'message': self.message.value,
                'day': day,
                'time': f"{hour:02d}:{minute:02d}",
                'repeat': repeat,
                'last_run': None
            }
            
            bot.save_scheduled_messages()
            
            await interaction.response.send_message(
                f"Message scheduled successfully!\n"
                f"ID: {schedule_id}\n"
                f"Channel: {self.channel_name}\n"
                f"Server: {self.server_name}\n"
                f"Day: {day.capitalize()}\n"
                f"Time: {hour:02d}:{minute:02d}\n"
                f"Repeat: {'Yes' if repeat else 'No'}"
            )
            
        except Exception as e:
            await interaction.response.send_message(
                f"An error occurred: {e}",
                ephemeral=True
            )

@bot.tree.command(name="schedule", description="Schedule a new message")
async def schedule(interaction: discord.Interaction):
    # Get channel and server details
    channel_name = interaction.channel.name
    server_name = interaction.guild.name
    server_id = interaction.guild.id
    
    # Pass details to the modal
    await interaction.response.send_modal(ScheduleModal(channel_name, server_name, server_id))

@bot.tree.command(name="list", description="List all scheduled messages")
async def list_schedules(interaction: discord.Interaction):
    if not bot.scheduled_messages:
        await interaction.response.send_message("No scheduled messages found.")
        return
        
    message = "Scheduled Messages:\n\n"
    for id, schedule in bot.scheduled_messages.items():
        message += f"ID: {id}\n"
        message += f"Channel: {schedule['channel_name']}\n"
        message += f"Server: {schedule['server_name']}\n"
        message += f"Message: {schedule['message']}\n"
        message += f"Day: {schedule['day'].capitalize()}\n"
        message += f"Time: {schedule['time']}\n"
        message += f"Repeat: {'Yes' if schedule['repeat'] else 'No'}\n\n"
        
    await interaction.response.send_message(message)

@bot.tree.command(name="delete", description="Delete a scheduled message")
async def delete_schedule(interaction: discord.Interaction, schedule_id: str):
    if schedule_id in bot.scheduled_messages:
        del bot.scheduled_messages[schedule_id]
        bot.save_scheduled_messages()
        await interaction.response.send_message(f"Schedule {schedule_id} deleted successfully!")
    else:
        await interaction.response.send_message("Schedule not found!", ephemeral=True)

@bot.event
async def on_ready():
    print(f'Bot is ready! Logged in as {bot.user.name}')
    try:
        synced = await bot.tree.sync()
        print(f"Synced {len(synced)} command(s)")
    except Exception as e:
        print(f"Failed to sync commands: {e}")

# Run the bot
bot.run(TOKEN)
