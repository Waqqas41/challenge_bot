from typing import Final
import os
from dotenv import load_dotenv
from discord import Intents, Message
from discord.ui import Button, View
import discord
from discord.ext import commands
from discord.ext import tasks
from datetime import datetime
import aiohttp
from collections import defaultdict
from operator import itemgetter
from discord.utils import get
from data import load_user_stats, save_user_stats  # Importing from data.py


# STEP 0: Load token
load_dotenv()
TOKEN: Final[str] = os.getenv("DISCORD_TOKEN")

# STEP 1: BOT SETUP
intents: Intents = Intents.default()
intents.message_content = True
intents.guilds = True
intents.members = True
client = commands.Bot(command_prefix="!", intents=intents)

# Configuration variables
CHANNEL_ID = 1333839623037915166 
REQUIRED_ROLE_NAME = "job challenge"
TIME_LIMIT = 40  # seconds to post image before warning/removal
last_image_times = {}  # Track when users post images

# Add this after the client initialization
# BUTTON_MESSAGE_ID = 1333848152696029204
BUTTON_CHANNEL_ID = 1333848120211017840

# Add after other configuration variables
user_stats = load_user_stats()  # Load user stats from the database

# Add these global variables
global_vars = {
    'bot_enabled': True  # Store bot state in a dictionary to avoid global scope issues
}

# Add a new dictionary to track the time of the last warning sent
last_warning_times = defaultdict(lambda: None)

# STEP 2: Message functionality
async def send_message(message: Message, user_message: str) -> None:
    if not user_message:
        print("(Message was empty because intents were not enabled)")
        return

    if is_private := user_message[0] == "?":
        user_message = user_message[1:]

    try:
        response: str = get_response(user_message)
        await message.author.send(response) if is_private else await message.channel.send(response)
    except Exception as e:
        print(e)

# STEP 3: Role removal task
@tasks.loop(seconds=TIME_LIMIT)
async def check_roles():
    if not global_vars['bot_enabled']:
        return
        
    channel = client.get_channel(CHANNEL_ID)
    if not channel:
        print(f"[DEBUG] Could not find channel with ID {CHANNEL_ID}")
        return

    current_time = datetime.now()
    print(f"\n[DEBUG] ========== CHECKING ROLES AT {current_time} ==========")
    
    role = discord.utils.get(channel.guild.roles, name=REQUIRED_ROLE_NAME)
    if not role:
        print(f"[DEBUG] Could not find role {REQUIRED_ROLE_NAME}")
        return
        
    members_with_role = [member for member in channel.guild.members if role in member.roles]
    member_count = len(members_with_role)
    print(f"[DEBUG] Found {member_count} members with the {REQUIRED_ROLE_NAME} role")
    
    for member in members_with_role:
        if member.bot:
            continue
            
        last_image_time = last_image_times.get(member.id)  # This can be None if not set
        current_warnings = user_stats['warnings'][member.id]
        last_warning_time = last_warning_times[member.id]

        # If last_image_time is None or not set, treat it as if the user has not posted an image
        if last_image_time is None:
            print(f"[DEBUG] {member.name} has no recorded last image time.")
            time_since_last_image = float('inf')  # Treat as if a long time has passed
        else:
            time_since_last_image = (current_time - last_image_time).total_seconds()
            print(f"[DEBUG] Time since last image for {member.name}: {time_since_last_image} seconds")
        
        if time_since_last_image <= TIME_LIMIT:  # Keep role if image posted within time limit
            print(f"[DEBUG] {member.name} keeps role (posted image recently)")
            # Reset warnings if they post in time
            user_stats['warnings'][member.id] = 0  # Reset warnings
            continue

        # Handle warnings and role removal
        if current_warnings == 0:
            # First warning
            user_stats['warnings'][member.id] += 1  # Increment warnings
            print(f"[DEBUG] First warning for {member.name}")
            timestamp = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
            last_warning_times[member.id] = current_time  # Track when the warning was sent
            try:
                await member.send(f"You need to post an image every day to stay in the Job Challenge! If you miss two days in a row, you're out! This is your first warning. (Timestamp: {timestamp})")
                print(f"[DEBUG] Sent warning DM to {member.name}")
            except Exception as e:
                print(f"[DEBUG] Could not send warning DM to {member.name}: {e}")
        elif current_warnings == 1:
            # Check if enough time has passed since the last warning before removing the role
            if last_warning_time and (current_time - last_warning_time).total_seconds() > TIME_LIMIT:
                # Second strike - remove role
                print(f"\n[DEBUG] ATTEMPTING TO REMOVE ROLE FROM {member.name} (Second strike)")
                try:
                    await member.remove_roles(role, reason=f"No image posted within {TIME_LIMIT} seconds - second strike")
                    print(f"[DEBUG] SUCCESS: Removed role from {member.name}")
                    
                    # Clear last image time when the role is removed
                    if member.id in last_image_times:
                        del last_image_times[member.id]  # Remove the last image time entry
                    
                    # Remove the user's reaction
                    channel = client.get_channel(BUTTON_CHANNEL_ID)
                    if channel:
                        async for message in channel.history(limit=50):
                            if message.author == client.user and "React with ✅ to get the job challenge role!" in message.content:
                                await message.remove_reaction("✅", member)
                                break
                    
                    # Do not reset warnings after role removal
                    # user_stats['warnings'][member.id] = 0  # Remove this line
                    
                    # Update elimination stats
                    user_stats['streaks'][member.id] = 0
                    user_stats['eliminations'].add(member.id)
                    
                    timestamp = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
                    try:
                        await member.send(f"Your '{REQUIRED_ROLE_NAME}' role has been removed after two warnings. Better luck next time, you can still continue on your own! (Timestamp: {timestamp})")
                        print(f"[DEBUG] SUCCESS: Sent removal DM to {member.name}")
                    except Exception as e:
                        print(f"[DEBUG] ERROR: Could not send DM to {member.name}: {e}")
                except discord.Forbidden as e:
                    print(f"[DEBUG] ERROR: No permission to remove role from {member.name}: {e}")
                except discord.HTTPException as e:
                    print(f"[DEBUG] ERROR: HTTP error when removing role from {member.name}: {e}")
                except Exception as e:
                    print(f"[DEBUG] ERROR: Unknown error when removing role from {member.name}: {e}")

# STEP 4: Bot events
@client.event
async def on_ready() -> None:
    print(f"{client.user} is now running")
    
    # Set up the reaction message in the specific channel
    channel = client.get_channel(BUTTON_CHANNEL_ID)
    if channel:
        print(f"[DEBUG] Found channel: {channel.name}")
        try:
            # Check for existing role message from the bot
            async for message in channel.history(limit=50):
                if message.author == client.user and "React with ✅ to get the job challenge role!" in message.content:
                    print("[DEBUG] Found existing role message, skipping creation")
                    check_roles.start()
                    return

            # If no existing message found, create a new one
            role_message = await channel.send("React with ✅ to get the job challenge role!")
            await role_message.add_reaction("✅")
            print("[DEBUG] Created new role message with reaction")
        except Exception as e:
            print(f"[DEBUG] Error setting up role message: {e}")
    else:
        print(f"[DEBUG] Could not find channel with ID {BUTTON_CHANNEL_ID}")

    # Initialize user states
    for guild in client.guilds:
        for member in guild.members:
            if role in member.roles:  # Check if the member has the required role
                # Initialize user stats if not already present
                if member.id not in user_stats['warnings']:
                    user_stats['warnings'][member.id] = 0
                    user_stats['streaks'][member.id] = 0
                    user_stats['total_images'][member.id] = 0
                    user_stats['eliminations'].discard(member.id)  # Remove from eliminations if they are back

    check_roles.start()

@client.event
async def on_raw_reaction_add(payload):
    # Check if bot is enabled first
    if not global_vars['bot_enabled']:
        try:
            channel = client.get_channel(payload.channel_id)
            if channel:
                message = await channel.fetch_message(payload.message_id)
                await message.remove_reaction(payload.emoji, payload.member)
                await payload.member.send("The challenge is closed now.")
        except:
            pass
        return

    # Rest of the existing reaction handling code
    if payload.member.bot:
        return

    channel = client.get_channel(payload.channel_id)
    if not channel:
        return

    try:
        message = await channel.fetch_message(payload.message_id)
    except:
        return

    if message.author == client.user and "React with ✅ to get the job challenge role!" in message.content:
        if str(payload.emoji) == "✅":
            role = get(payload.member.guild.roles, name=REQUIRED_ROLE_NAME)
            if role:
                try:
                    await payload.member.add_roles(role)
                    # Reset warnings when the role is assigned
                    user_stats['warnings'][payload.member.id] = 0  # Reset warnings
                    last_image_times[payload.member.id] = datetime.min  # Ensure this is a datetime object
                    timestamp = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
                    await payload.member.send(f"You have been given the {REQUIRED_ROLE_NAME} role! (Timestamp: {timestamp})")
                except Exception as e:
                    print(f"[DEBUG] Error giving role: {e}")
                    try:
                        await payload.member.send("There was an error giving you the role. Please contact an administrator.")
                    except:
                        pass

@client.event
async def on_raw_reaction_remove(payload):
    # We don't need to do anything when reactions are removed
    pass

@client.event
async def on_message(message):
    # Check if the message is from a user and not a bot
    if message.author.bot:
        return

    # Check if the message is in the correct channel and contains attachments
    if message.channel.id == CHANNEL_ID and message.attachments:
        # Check if the bot is mentioned in the message
        if client.user.id in [user.id for user in message.mentions]:  # Check if the bot is mentioned
            for attachment in message.attachments:
                if any(attachment.filename.lower().endswith(ext) for ext in ['.png', '.jpg', '.jpeg', '.gif']):
                    last_image_times[message.author.id] = datetime.now()
                    print(f"[DEBUG] Image posted by {message.author.name} at {last_image_times[message.author.id]}")
                    
                    # Update stats
                    user_stats['streaks'][message.author.id] += 1
                    user_stats['total_images'][message.author.id] += 1
                    print(f"[DEBUG] Updated stats for {message.author.name}")
                    
                    # Reset warnings when an image is accepted
                    user_stats['warnings'][message.author.id] = 0  # Reset warnings
                    print(f"[DEBUG] Warnings reset for {message.author.name}")

                    # Send acceptance message
                    await message.channel.send(f"✅ {message.author.mention}, your image submission has been accepted!")
                    break
        else:
            # Debug message for image posted without ping
            print(f"[DEBUG] Image posted by {message.author.name} without mentioning the bot.")
    
    await client.process_commands(message)  # This allows commands to still work

@client.command(name='forcereset')
@commands.has_role('admin')
async def force_reset(ctx):
    try:
        role = get(ctx.guild.roles, name=REQUIRED_ROLE_NAME)
        if not role:
            await ctx.send("Could not find job challenge role.")
            return
            
        members_with_role = [member for member in ctx.guild.members if role in member.roles]
        member_count = len(members_with_role)
        
        await ctx.send(f"Removing job challenge role from {member_count} members...")
        
        for member in members_with_role:
            if member.bot:
                continue
            try:
                await member.remove_roles(role, reason="Force reset by admin")
                print(f"[DEBUG] Removed role from {member.name}")
            except Exception as e:
                print(f"[DEBUG] Error removing role from {member.name}: {e}")
        
        # Find and clear reactions on the role message
        channel = client.get_channel(BUTTON_CHANNEL_ID)
        if channel:
            async for message in channel.history(limit=50):
                if message.author == client.user and "React with ✅ to get the job challenge role!" in message.content:
                    await message.clear_reactions()
                    await message.add_reaction("✅")
                    break
        
        await ctx.send(f"✅ Successfully removed job challenge role from {member_count} members and reset reactions.")
        
    except discord.Forbidden:
        await ctx.send("I don't have permission to manage roles.")
    except Exception as e:
        await ctx.send(f"An error occurred: {str(e)}")

# Add these new commands for stats
@client.command(name='stats')
async def show_stats(ctx):
    user_id = ctx.author.id
    streak = user_stats['streaks'].get(user_id, 0)
    days_missed = user_stats['warnings'].get(user_id, 0)  # Use warnings as days missed
    
    embed = discord.Embed(title="Your Stats", color=discord.Color.blue())
    embed.add_field(name="Current Streak", value=f"{streak} days", inline=False)
    embed.add_field(name="Days Missed", value=str(days_missed), inline=False)
    
    await ctx.send(embed=embed)

@client.command(name='leaderboard', aliases=['lb'])
async def show_leaderboard(ctx):
    # Sort users by total images
    top_posters = sorted(
        user_stats['total_images'].items(),
        key=itemgetter(1),
        reverse=True
    )[:10]  # Top 10 only
    
    # Get unique eliminated users
    eliminated_users = set(user_stats['eliminations'])
    
    embed = discord.Embed(title="🏆 Job Challenge Leaderboard", color=discord.Color.gold())
    
    # Top image posters
    top_posters_text = ""
    for i, (user_id, count) in enumerate(top_posters, 1):
        user = ctx.guild.get_member(user_id)
        if user:  # Only show users still in the server
            name = user.name
            if i == 1:
                top_posters_text += f"👑 {i}. {name}: {count} images\n"
            else:
                top_posters_text += f"{i}. {name}: {count} images\n"
    embed.add_field(
        name="📸 Top 10 Image Posters", 
        value=top_posters_text or "No data yet", 
        inline=False
    )
    
    # Eliminated users list
    eliminated_text = ""
    eliminated_count = 0
    for user_id in eliminated_users:
        user = ctx.guild.get_member(user_id)
        if user:  # Only show users still in the server
            eliminated_count += 1
            eliminated_text += f"• {user.name}\n"
    
    if eliminated_text:
        embed.add_field(
            name=f"❌ Eliminated Users ({eliminated_count})", 
            value=eliminated_text, 
            inline=False
        )
    else:
        embed.add_field(
            name="❌ Eliminated Users", 
            value="No eliminations yet", 
            inline=False
        )
    
    # Add total participants
    total_participants = len(set(user_stats['total_images'].keys()))
    embed.set_footer(text=f"Total Participants: {total_participants}")
    
    await ctx.send(embed=embed)

@client.command(name='disable')
@commands.has_role('admin')
async def disable_bot(ctx):
    if not global_vars['bot_enabled']:
        await ctx.send("Bot is already disabled!")
        return
        
    global_vars['bot_enabled'] = False
    check_roles.stop()  # Stop the role checking task
    
    # Find and remove the reaction from the role message
    channel = client.get_channel(BUTTON_CHANNEL_ID)
    if channel:
        async for message in channel.history(limit=50):
            if message.author == client.user and "React with ✅ to get the job challenge role!" in message.content:
                await message.clear_reactions()
                await message.edit(content="🔴 Role assignment is currently disabled.")
                break
    
    embed = discord.Embed(
        title="Bot Disabled",
        description="Role checking and assignment have been disabled. Users will keep their current roles.",
        color=discord.Color.red()
    )
    await ctx.send(embed=embed)
    print("[DEBUG] Bot disabled by admin")

@client.command(name='enable')
@commands.has_role('admin')
async def enable_bot(ctx):
    if global_vars['bot_enabled']:
        await ctx.send("Bot is already enabled!")
        return
        
    global_vars['bot_enabled'] = True
    check_roles.start()  # Restart the role checking task
    
    # Restore the reaction on the role message
    channel = client.get_channel(BUTTON_CHANNEL_ID)
    if channel:
        async for message in channel.history(limit=50):
            if message.author == client.user and "🔴 Role assignment is currently disabled." in message.content:
                await message.edit(content="React with ✅ to get the job challenge role!")
                await message.add_reaction("✅")
                break
    
    embed = discord.Embed(
        title="Bot Enabled",
        description="Role checking and assignment have been enabled. Users must now post images every " + 
                   f"{TIME_LIMIT} seconds to keep their roles.",
        color=discord.Color.green()
    )
    await ctx.send(embed=embed)
    print("[DEBUG] Bot enabled by admin")

@client.command(name='status')
@commands.has_role('admin')
async def check_status(ctx):
    status = "Enabled" if global_vars['bot_enabled'] else "Disabled"
    color = discord.Color.green() if global_vars['bot_enabled'] else discord.Color.red()
    
    embed = discord.Embed(
        title="Bot Status",
        description=f"Current Status: **{status}**\n" +
                   f"Time Limit: **{TIME_LIMIT}** seconds\n" +
                   f"Role Name: **{REQUIRED_ROLE_NAME}**",
        color=color
    )
    await ctx.send(embed=embed)

@client.command(name='guide')
async def show_guide(ctx):
    embed = discord.Embed(
        title="Bot Commands Guide",
        description="Here's a list of all available commands and their functions:",
        color=discord.Color.blue()
    )

    # User Commands
    embed.add_field(
        name="📊 User Commands",
        value=(
            "**!stats**\n"
            "• Shows your personal stats\n"
            "• Displays: Current Streak, Total Images, Times Eliminated, Days Missed\n\n"
            "**!leaderboard** (or **!lb**)\n"
            "• Shows the top 10 image posters\n"
            "• Shows list of eliminated users"
        ),
        inline=False
    )

    # Admin Commands
    embed.add_field(
        name="🛠️ Admin Commands",
        value=(
            "**!enable**\n"
            "• Enables the role system\n"
            "• Restores role assignment and checking\n"
            "• Adds back the reaction for getting roles\n\n"
            "**!disable**\n"
            "• Disables the role system\n"
            "• Stops role checking and assignment\n"
            "• Removes the reaction for getting roles\n\n"
            "**!forcereset**\n"
            "• Removes the job challenge role from all users\n"
            "• Resets the role reaction\n"
            "• Shows how many roles were removed\n\n"
            "**!status**\n"
            "• Shows if the bot is enabled or disabled\n"
            "• Displays current time limit and role name"
        ),
        inline=False
    )

    # How to Get/Keep Role
    embed.add_field(
        name="🎯 How to Do the Challenge",
        value=(
            "1. React with ✅ to get the role\n"
            f"2. Post an image every {TIME_LIMIT} seconds to keep it\n"
            "3. You'll get one warning if you miss the time limit\n"
            "4. Role is removed after second missed deadline"
        ),
        inline=False
    )

    # Footer
    embed.set_footer(text="Note: Admin commands require the 'admin' role to use.")

    await ctx.send(embed=embed)

@client.command(name='complete_module_9')
@commands.has_role('admin')
async def complete_module_9(ctx, member: discord.Member):
    user_stats['completed_modules'][member.id].add('Module 9')
    save_user_stats(member.id)  # Save stats after updating
    await ctx.send(f"✅ {member.mention} has been marked as completed for Module 9.")

@client.command(name='complete_module_10')
@commands.has_role('admin')
async def complete_module_10(ctx, member: discord.Member):
    # Check if the user is already marked as completed for the modules
    if 'completed_modules' not in user_stats:
        user_stats['completed_modules'] = defaultdict(set)  # Initialize if not present

    # Add Module 10 to the user's completed list
    user_stats['completed_modules'][member.id].add('Module 10')

    # Send confirmation message
    await ctx.send(f"✅ {member.mention} has been marked as completed for Module 10.")
    print(f"[DEBUG] {member.name} marked as completed for Module 10.")


# STEP 5: Main entry point
def main() -> None:
    client.run(token=TOKEN)

if __name__ == '__main__':
    main()
