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
MAX_SCHEDULES_PER_SERVER = 100  # Maximum number of scheduled messages per server

# Define intents
intents = discord.Intents.default()  # Enable default intents
intents.message_content = True  # Enable message content intent

class SchedulerBot(commands.Bot):
    def __init__(self):
        # Pass the intents to the bot
        super().__init__(command_prefix='!', intents=intents)
        self.scheduled_messages = {}  # Store schedules per server: {server_id: {schedule_id: schedule}}
        
    async def setup_hook(self):
        self.load_scheduled_messages()
        # Start the background task
        await self.start_synchronized_check()

    async def start_synchronized_check(self):
        # Calculate delay until the start of the next minute
        now = datetime.now(pytz.timezone(TIMEZONE))
        seconds_until_next_minute = 60 - now.second
        microseconds_remaining = 1000000 - now.microsecond
        
        # Convert to seconds (including microseconds part)
        total_delay = seconds_until_next_minute + (microseconds_remaining / 1000000)
        
        print(f"Synchronizing scheduler... Waiting {total_delay:.2f} seconds until next minute.")
        
        # Wait until the start of the next minute
        await asyncio.sleep(total_delay)
        
        # Start the task loop
        self.check_scheduled_messages.start()
        print(f"Scheduler synchronized and started at {datetime.now(pytz.timezone(TIMEZONE)).strftime('%H:%M:%S.%f')}")
        
    def load_scheduled_messages(self):
        try:
            with open('scheduled_messages.json', 'r') as f:
                self.scheduled_messages = json.load(f)
        except FileNotFoundError:
            self.scheduled_messages = {}
        
    def save_scheduled_messages(self):
        with open('scheduled_messages.json', 'w') as f:
            json.dump(self.scheduled_messages, f, indent=4)  # Use indent for readability

    @tasks.loop(minutes=1)
    async def check_scheduled_messages(self):
        current_time = datetime.now(pytz.timezone(TIMEZONE)).replace(second=0, microsecond=0)
        current_time_str = current_time.strftime("%H:%M")
        current_day = current_time.strftime("%A").lower()  # Get current day (e.g., "monday")
        keys_to_delete = []
        
        # Check for missed messages
        for server_id, schedules in list(self.scheduled_messages.items()):  # Iterate over servers
            for schedule_id, schedule in list(schedules.items()):  # Iterate over schedules for the server
                # Skip if the schedule is missing the 'day' field
                if 'day' not in schedule:
                    print(f"Warning: Schedule {schedule_id} is missing the 'day' field. Skipping.")
                    continue
                
                # Calculate the next run time
                if schedule.get('repeat_interval_hours'):  # Hourly repeat
                    last_run = schedule.get('last_run')
                    if last_run:
                        last_run_time = datetime.fromisoformat(last_run)
                        next_run_time = last_run_time + timedelta(hours=schedule['repeat_interval_hours'])
                    else:
                        # For first run or after restart, use the scheduled time as reference
                        scheduled_time = datetime.strptime(f"{schedule['time']}", "%H:%M").time()
                        next_run_time = current_time.replace(
                            hour=scheduled_time.hour,
                            minute=scheduled_time.minute,
                            second=0,
                            microsecond=0
                        )
                        # If the scheduled time has passed today, move to next interval
                        if next_run_time < current_time:
                            next_run_time += timedelta(hours=schedule['repeat_interval_hours'])
                    # Check if the next run time is in the past (missed message)
                    if next_run_time <= current_time:
                        # Send the missed message immediately
                        channel = self.get_channel(schedule['channel_id'])
                        if channel:
                            try:
                                print(f"Sending hourly scheduled message {schedule_id}")
                                await channel.send(schedule['message'])
                                # Update last run time
                                schedule['last_run'] = current_time.isoformat()
                            except discord.errors.Forbidden:
                                print(f"Missing permissions to send messages in channel {channel.id}. Skipping.")
                            except discord.errors.NotFound:
                                print(f"Channel {channel.id} not found. Skipping.")
                            except Exception as e:
                                print(f"An error occurred while sending the message: {e}")
                else:  # Weekly repeat
                    if schedule['day'].lower() == current_day and schedule['time'] == current_time_str:
                        # Check if message was already sent today
                        if schedule['last_run'] != current_time.date().isoformat():
                            # Send the message immediately
                            channel = self.get_channel(schedule['channel_id'])
                            if channel:
                                try:
                                    print(f"Sending weekly scheduled message {schedule_id}, repeat: {schedule['repeat']}")
                                    await channel.send(schedule['message'])
                                    if not schedule['repeat']:
                                        # Delete non repeating schedule after sending
                                        keys_to_delete.append(schedule_id)
                                    else:
                                        # Update last run time
                                        schedule['last_run'] = current_time.date().isoformat()
                                        self.save_scheduled_messages()
                                except discord.errors.Forbidden:
                                    print(f"Missing permissions to send messages in channel {channel.id}. Skipping.")
                                except discord.errors.NotFound:
                                    print(f"Channel {channel.id} not found. Deleting schedule {schedule_id}")
                                    keys_to_delete.append(schedule_id)
                                except Exception as e:
                                    print(f"An error occurred while sending the message: {e}")

            try: 
                for schedule_id in keys_to_delete:
                    del schedules[str(schedule_id)]
            except Exception as e:
                print("")
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
        
        self.repeat_interval = discord.ui.TextInput(
            label="Repeat Interval (hours, optional)",
            placeholder="Enter the repeat interval in hours (e.g., 2)",
            required=False,
            max_length=2
        )
        
        self.repeat = discord.ui.TextInput(
            label="Repeat? (yes/no)",
            placeholder="Type 'yes' or 'no'",
            required=True,
            max_length=3
        )
        
        self.add_item(self.message)
        self.add_item(self.day)
        self.add_item(self.time)
        self.add_item(self.repeat_interval)
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
            
            # Validate repeat interval (if provided)
            repeat_interval_hours = int(self.repeat_interval.value) if self.repeat_interval.value else None
            if repeat_interval_hours and repeat_interval_hours <= 0:
                await interaction.response.send_message(
                    "Invalid repeat interval! Please enter a positive number of hours.",
                    ephemeral=True
                )
                return
            
            # Validate repeat option
            repeat = self.repeat.value.lower() == 'yes'
            
            # If hourly interval is provided, repeat must be "yes"
            if repeat_interval_hours and not repeat:
                await interaction.response.send_message(
                    "If hourly interval is provided, repeat must be 'yes'.",
                    ephemeral=True
                )
                return
            
            server_id_str = str(self.server_id)
            
            # Initialize server schedules if it doesn't exist
            if server_id_str not in bot.scheduled_messages:
                bot.scheduled_messages[server_id_str] = {}
                
            server_schedules = bot.scheduled_messages[server_id_str]

            # Check if the server has reached the maximum number of scheduled messages
            if len(server_schedules) >= MAX_SCHEDULES_PER_SERVER:
                await interaction.response.send_message(
                    f"This server has reached the maximum limit of {MAX_SCHEDULES_PER_SERVER} scheduled messages.",
                    ephemeral=True
                )
                return
            
            # Find the next available schedule ID
            next_id = 1
            while str(next_id) in server_schedules:
                next_id += 1
            schedule_id = str(next_id)
            
            # Create schedule entry
            server_schedules[schedule_id] = {
                'channel_id': interaction.channel_id,
                'channel_name': self.channel_name,
                'server_name': self.server_name,
                'server_id': self.server_id,
                'message': self.message.value,
                'day': day,
                'time': f"{hour:02d}:{minute:02d}",
                'repeat': repeat,
                'repeat_interval_hours': repeat_interval_hours,
                'last_run': None
            }
            
            # Update the server's schedules
            bot.save_scheduled_messages()

            repeat_str = "N/A"
            if repeat_interval_hours:
                repeat_str = str(repeat_interval_hours)
                 
            
            await interaction.response.send_message(
                f"Message scheduled successfully!\n"
                f"ID: {schedule_id}\n"
                f"Channel: {self.channel_name}\n"
                f"Server: {self.server_name}\n"
                f"Message: {self.message.value.replace("@everyone", "@\u200beveryone").replace("@here", "@\u200bhere")}\n" 
                f"Day: {day.capitalize()}\n"
                f"Time: {hour:02d}:{minute:02d}\n"
                f"Repeat Interval: {repeat_str}\n"
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

@bot.tree.command(name="list", description="List all scheduled messages for this server")
async def list_schedules(interaction: discord.Interaction):
    # Reload the scheduled messages from the file to get the latest data
    bot.load_scheduled_messages()
    
    # Get the current server ID
    current_server_id = str(interaction.guild.id)
    
    # Filter scheduled messages for the current server
    server_schedules = bot.scheduled_messages.get(current_server_id, {})
    
    if not server_schedules:
        await interaction.response.send_message("No scheduled messages found for this server.")
        return
        
    message = "Scheduled Messages for this Server:\n\n"
    for id, schedule in server_schedules.items():
        # Remove @everyone and @here mentions to avoid notifications
        safe_message = schedule['message'].replace("@everyone", "@\u200beveryone").replace("@here", "@\u200bhere")
        message += f"ID: {id}\n"
        message += f"Channel: {schedule['channel_name']}\n"
        message += f"Message: {safe_message}\n"
        message += f"Day: {schedule['day'].capitalize()}\n"
        message += f"Time: {schedule['time']}\n"
        message += f"Repeat Interval: {schedule['repeat_interval_hours']} hours\n" if schedule.get('repeat_interval_hours') else f"Repeat: {'Yes' if schedule['repeat'] else 'No'}\n"
        message += "\n"
        
    await interaction.response.send_message(message)

@bot.tree.command(name="delete", description="Delete a scheduled message")
async def delete_schedule(interaction: discord.Interaction, schedule_id: str):
    # Get the current server ID
    current_server_id = str(interaction.guild.id)
    
    # Check if the schedule exists and belongs to the current server
    server_schedules = bot.scheduled_messages.get(current_server_id, {})
    if schedule_id in server_schedules:
        del server_schedules[schedule_id]
        bot.scheduled_messages[current_server_id] = server_schedules
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
