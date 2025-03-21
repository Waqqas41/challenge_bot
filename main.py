from dotenv import load_dotenv # type: ignore
import os 
from discord.ext import commands
import discord
from typing import Final
from discord import Intents
from discord.ext import tasks
import datetime
import json

# Load token
load_dotenv()
TOKEN: Final[str] = os.getenv("DISCORD_TOKEN")

# Bot setup
intents = discord.Intents.all()
intents.guilds = True
intents.message_content = True
intents.members = True
client = commands.Bot(command_prefix=";", intents=intents)

@client.event
async def on_ready() -> None:
    print(f"{client.user} is now running")
    check_verification_channels.start()
    check_inactive_verification_tickets.start()

# Load shahada data
try:
    with open('shahada_counts.json', 'r') as f:
        data = json.load(f)
        shahada_count = data.get('total', 0)
        shahada_members = data.get('members', [])  # List of member IDs who took shahada
except FileNotFoundError:
    shahada_count = 0
    shahada_members = []

def save_shahada_data():
    """Helper function to save shahada data to JSON file"""
    with open('shahada_counts.json', 'w') as f:
        json.dump({
            'total': shahada_count,
            'members': shahada_members
        }, f)

@client.command(name='shahadacounter')
@commands.has_any_role('Mod', 'Mini Mod')
async def shahada_counter(ctx, *, args=None):
    global shahada_count, shahada_members
    
    if args is None:
        await ctx.send("Please provide either a member or a number to set the counter.")
        return
    
    # Check if args is just a number
    try:
        start_number = int(args)
        shahada_count = start_number
        shahada_members = []  # Reset the members list since we're starting fresh
        save_shahada_data()
        await ctx.send(f"Shahada counter has been set to {start_number}")
        return
    except ValueError:
        # Not a number, try to get a member
        try:
            # Try to convert mention to member
            member = await commands.MemberConverter().convert(ctx, args)
            
            # Regular shahada counting logic
            if str(member.id) in shahada_members:
                await ctx.send(f"{member.mention} has already taken their shahada!")
                return
            
            shahada_count += 1
            shahada_members.append(str(member.id))
            save_shahada_data()
            await ctx.send(f"{member.mention} has taken their shahada. Total count: {shahada_count}! Alhamdulillah!")
        except commands.MemberNotFound:
            await ctx.send("Please provide a valid member or number.")

@client.command(name='removeshahada')
@commands.has_any_role('Mod', 'Mini Mod')
async def remove_shahada(ctx, member: discord.Member):
    global shahada_count, shahada_members
    
    if str(member.id) not in shahada_members:
        await ctx.send(f"{member.mention} has not taken shahada yet.")
        return
        
    if shahada_count > 0:
        shahada_count -= 1
        shahada_members.remove(str(member.id))
        save_shahada_data()
        await ctx.send(f"Removed shahada count for {member.mention}. New total count: {shahada_count}")
    else:
        await ctx.send("There are no shahada counts to remove.")

@client.command(name='listshahadas')
@commands.has_any_role('Mod', 'Mini Mod')
async def list_shahadas(ctx):
    if not shahada_members:
        await ctx.send("No shahadas have been recorded yet.")
        return
        
    message = "Members who have taken shahada:\n"
    for member_id in shahada_members:
        member = ctx.guild.get_member(int(member_id))
        if member:
            message += f"• {member.mention}\n"
    
    message += f"\nTotal count: {shahada_count}"
    await ctx.send(message)

@shahada_counter.error
@remove_shahada.error
@list_shahadas.error
async def shahada_error(ctx, error):
    if isinstance(error, commands.MemberNotFound):
        await ctx.send("Please specify a valid member.")
    elif isinstance(error, commands.MissingRequiredArgument):
        await ctx.send("Please mention a member to track/remove their shahada.")
    elif isinstance(error, commands.MissingAnyRole):
        await ctx.send("You don't have permission to use this command.")

# Daily task to check verification channels
@tasks.loop(time=datetime.time(hour=9, tzinfo=datetime.timezone(datetime.timedelta(hours=-5))))  # 9 AM EST
async def check_verification_channels():
    # Get the verification category
    for guild in client.guilds:
        verification_category = discord.utils.get(guild.categories, id=1349095399918407731)
        if verification_category:
            # Count channels in the category that contain "verification" in their name
            channel_count = len([
                channel for channel in verification_category.channels 
                if "verification" in channel.name.lower()
            ])
            
            # Subtract 1 from the count (for the permanent channel)
            open_tickets = channel_count
            
            # Only send a message if there are open tickets
            if open_tickets > 0:
                # Find the reminder channel (changed from mod_channel)
                reminder_channel = discord.utils.get(guild.channels, id=887834241881227354)
                if reminder_channel:
                    await reminder_channel.send(f"There are currently {open_tickets} open verification tickets that need your assistance!")

# New task to check for inactive verification tickets every 10 minutes
@tasks.loop(minutes=20)
async def check_inactive_verification_tickets():
    # Load previously reminded tickets
    try:
        with open('reminded_tickets.json', 'r') as f:
            reminded_tickets = json.load(f)
    except (FileNotFoundError, json.JSONDecodeError):
        reminded_tickets = {}
    
    current_time = datetime.datetime.now().timestamp()
    one_day_seconds = 86400  # 24 hours * 60 minutes * 60 seconds
    
    for guild in client.guilds:
        verification_category = discord.utils.get(guild.categories, id=1349095399918407731)
        if not verification_category:
            continue
            
        # Find the channel to send reminders to
        reminder_channel = discord.utils.get(guild.channels, id=887834241881227354)
        if not reminder_channel:
            continue
            
        inactive_tickets = []
        original_messages = {}  # Store original reminder messages
        
        # Check each verification channel in the category
        for channel in verification_category.channels:
            if "verification" in channel.name.lower():
                channel_id = str(channel.id)
                
                # Skip if we've reminded about this ticket in the last 24 hours
                if channel_id in reminded_tickets:
                    last_reminder = reminded_tickets[channel_id]
                    if current_time - last_reminder < one_day_seconds:
                        continue
                
                # Get the last 10 messages in the channel
                try:
                    messages = [msg async for msg in channel.history(limit=10)]
                    
                    # Check if only the bot has sent messages
                    has_non_bot_message = False
                    bot_message_count = 0
                    
                    for msg in messages:
                        if msg.author.id == 1346564959835787284:  # Bot ID
                            bot_message_count += 1
                        else:
                            has_non_bot_message = True
                            break
                    
                    # If there are messages but none from non-bot users and bot has 2 or fewer messages,
                    # consider it inactive
                    if messages and not has_non_bot_message and bot_message_count <= 2:
                        inactive_tickets.append(channel)
                        # Update the last reminder time
                        reminded_tickets[channel_id] = current_time
                except discord.Forbidden:
                    # Skip channels the bot can't read
                    continue
        
        # Send reminder with links if there are inactive tickets
        if inactive_tickets:
            reminder_msg = "The following verification tickets has not messaged or been messaged:\n"
            for ticket in inactive_tickets:
                reminder_msg += f"• <#{ticket.id}>\n"
            
            # Send the reminder message and store the message ID
            sent_message = await reminder_channel.send(reminder_msg)
            original_messages[sent_message.id] = inactive_tickets  # Store the message ID with the respective tickets

    # Save the updated reminded tickets
    with open('reminded_tickets.json', 'w') as f:
        json.dump(reminded_tickets, f)

# Listen for replies to the reminder message
@client.event
async def on_message(message):
    if message.channel.id == 887834241881227354 and message.reference:
        # Check if the message is a reply to a reminder message
        original_message = await message.channel.fetch_message(message.reference.message_id)
        
        # Check if the original message is a reminder message
        if original_message.content.startswith("The following verification tickets need attention"):
            # Extract the ticket ID from the reply
            ticket_id = message.content.split("<#")[1].split(">")[0]  # Get the channel ID from the reply
            
            # Update the original message with a checkmark
            updated_content = original_message.content.replace(f"• <#{ticket_id}>", f"• <#{ticket_id}> ✅")
            await original_message.edit(content=updated_content)

# Wait until the bot is ready before starting the tasks
@check_verification_channels.before_loop
async def before_check():
    await client.wait_until_ready()

@check_inactive_verification_tickets.before_loop
async def before_inactive_check():
    await client.wait_until_ready()

@client.command(name='jail')
@commands.has_any_role('Mod', 'Mini Mod')
async def jail(ctx, member: discord.Member, *, reason=None):
    # Get the jail role using the specific ID
    jail_role = ctx.guild.get_role(897591887140098139)
    
    # Check if the jail role exists
    if not jail_role:
        await ctx.send("Error: The jail role doesn't exist in this server.")
        return
    
    # Check if the bot has permission to manage roles
    if not ctx.guild.me.guild_permissions.manage_roles:
        await ctx.send("Error: I don't have permission to manage roles.")
        return
        
    # Check if the bot's highest role is higher than the member's highest role
    if ctx.guild.me.top_role <= member.top_role:
        await ctx.send("Error: I can't jail this member because their highest role is above or equal to my highest role.")
        return
    
    # Check if the command user has permission to jail this member
    if ctx.author.top_role <= member.top_role and ctx.author.id != ctx.guild.owner_id:
        await ctx.send("Error: You can't jail someone with a higher or equal role than yourself.")
        return
    
    # Store the member's current roles
    member_roles = [role.id for role in member.roles if role.name != '@everyone']
    
    try:
        # Remove all roles and add jail role
        await member.remove_roles(*[role for role in member.roles if role.name != '@everyone'])
        await member.add_roles(jail_role)
        
        # Store the jailed member's info
        try:
            with open('jailed_members.json', 'r') as f:
                jailed_members = json.load(f)
        except FileNotFoundError:
            jailed_members = {}
        
        jailed_members[str(member.id)] = member_roles
        
        with open('jailed_members.json', 'w') as f:
            json.dump(jailed_members, f)
        
        # Send confirmation message
        if reason:
            await ctx.send(f"{member.mention} has been jailed for: {reason}")
        else:
            await ctx.send(f"{member.mention} has been jailed.")
    except discord.Forbidden:
        await ctx.send("I don't have permission to modify this member's roles.")
    except Exception as e:
        await ctx.send(f"An error occurred while jailing the member: {str(e)}")

@client.command(name='unjail')
@commands.has_any_role('Mod', 'Mini Mod')
async def unjail(ctx, member: discord.Member):
    # Get the jail role
    jail_role = discord.utils.get(ctx.guild.roles, name='Jail')
    
    # Check if the jail role exists
    if not jail_role:
        await ctx.send("Error: The 'Jail' role doesn't exist in this server. Please create it first.")
        return
    
    # Check if member has jail role
    if jail_role not in member.roles:
        await ctx.send(f"{member.mention} is not currently jailed.")
        return
    
    # Remove jail role
    await member.remove_roles(jail_role)
    
    # Restore previous roles if available
    try:
        with open('jailed_members.json', 'r') as f:
            jailed_members = json.load(f)
            
        if str(member.id) in jailed_members:
            roles_to_add = []
            for role_id in jailed_members[str(member.id)]:
                role = ctx.guild.get_role(role_id)
                if role:  # Make sure the role still exists
                    roles_to_add.append(role)
            
            if roles_to_add:  # Only try to add roles if there are any
                await member.add_roles(*roles_to_add)
            
            # Remove member from jailed list
            del jailed_members[str(member.id)]
            
            with open('jailed_members.json', 'w') as f:
                json.dump(jailed_members, f)
    except (FileNotFoundError, json.JSONDecodeError):
        pass  # If file doesn't exist or is invalid, just continue
    
    await ctx.send(f"{member.mention} has been released from jail.")

@jail.error
@unjail.error
async def jail_error(ctx, error):
    if isinstance(error, commands.MemberNotFound):
        await ctx.send("Please specify a valid member.")
    elif isinstance(error, commands.MissingRequiredArgument):
        await ctx.send("Please mention a member to jail/unjail.")
    elif isinstance(error, commands.MissingAnyRole):
        await ctx.send("You don't have permission to use this command.")
    else:
        await ctx.send(f"An error occurred: {error}")

def main() -> None:
    client.run(token=TOKEN)

if __name__ == '__main__':
    main()