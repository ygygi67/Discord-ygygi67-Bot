import discord
from discord import app_commands
from discord.ext import commands, tasks
import logging
from core.storage import storage
from core.command_logger import command_logger
from datetime import datetime


logger = logging.getLogger('discord_bot')

class Roles(commands.Cog):
    def __init__(self, bot):
        self.bot = bot
        self.role_messages = {}
        logger.info("Roles cog initialized")
        self.auto_remove_old_role.start()

    @app_commands.command(name="สร้างป้ายยศ", description="สร้างป้ายสำหรับเลือกยศด้วยอีโมจิ")
    @app_commands.default_permissions(administrator=True)
    async def create_role_panel(self, interaction: discord.Interaction, title: str, description: str):
        """สร้างป้ายสำหรับเลือกยศด้วยอีโมจิ"""
        await interaction.response.defer(ephemeral=True)
        try:
            embed = discord.Embed(
                title=title,
                description=description,
                color=discord.Color.blue()
            )
            embed.set_footer(text="กดที่อีโมจิด้านล่างเพื่อรับยศ")
            
            message = await interaction.channel.send(embed=embed)
            self.role_messages[message.id] = {
                "guild_id": interaction.guild.id,
                "roles": {}
            }
            
            # Save role panel to storage
            storage.save_data(interaction.guild.id, "role_panels", {
                str(message.id): {
                    "title": title,
                    "description": description,
                    "roles": {}
                }
            })
            
            await interaction.followup.send("✅ สร้างป้ายยศเรียบร้อยแล้ว", ephemeral=True)
            
        except Exception as e:
            logger.error(f"Error creating role panel: {e}")
            await interaction.followup.send(f"❌ เกิดข้อผิดพลาด: {str(e)}", ephemeral=True)

    @app_commands.command(name="เพิ่มยศ", description="เพิ่มยศลงในป้ายยศ")
    @app_commands.default_permissions(administrator=True)
    async def add_role(self, interaction: discord.Interaction, message_id: str, role: discord.Role, emoji: str):
        """เพิ่มยศลงในป้ายยศ"""
        await interaction.response.defer(ephemeral=True)
        try:
            message_id = int(message_id)
            message = await interaction.channel.fetch_message(message_id)
            
            if message.id not in self.role_messages:
                role_panels = storage.load_data(interaction.guild.id, "role_panels") or {}
                panel = role_panels.get(str(message.id))
                if not panel:
                    await interaction.followup.send("❌ ไม่พบป้ายยศนี้", ephemeral=True)
                    return
                self.role_messages[message.id] = {
                    "guild_id": interaction.guild.id,
                    "roles": panel.get("roles", {})
                }
                
            # Add reaction to message
            await message.add_reaction(emoji)
            
            # Update role panel data
            self.role_messages[message.id]["roles"][emoji] = role.id
            
            # Save to storage
            role_panels = storage.load_data(interaction.guild.id, "role_panels") or {}
            if str(message.id) in role_panels:
                role_panels[str(message.id)]["roles"][emoji] = role.id
                storage.save_data(interaction.guild.id, "role_panels", role_panels)
            
            await interaction.followup.send(f"✅ เพิ่มยศ {role.name} เรียบร้อยแล้ว", ephemeral=True)
            
        except Exception as e:
            logger.error(f"Error adding role: {e}")
            await interaction.followup.send(f"❌ เกิดข้อผิดพลาด: {str(e)}", ephemeral=True)

    @tasks.loop(minutes=1)
    async def auto_remove_old_role(self):
        """Automatically remove old_role from members who have both old_role and condition_role."""
        # You must set these role IDs below!
        OLD_ROLE_ID = 1323809549786026094  # <-- Set your old role ID here
        CONDITION_ROLE_ID = 1352915130593316895  # <-- Set your condition role ID here

        if OLD_ROLE_ID is None or CONDITION_ROLE_ID is None:
            logger.warning("OLD_ROLE_ID or CONDITION_ROLE_ID not set for auto_remove_old_role task.")
            return

        for guild in self.bot.guilds:
            old_role = guild.get_role(OLD_ROLE_ID)
            condition_role = guild.get_role(CONDITION_ROLE_ID)
            if not old_role or not condition_role:
                continue
            removed_count = 0
            for member in guild.members:
                if old_role in member.roles and condition_role in member.roles:
                    try:
                        await member.remove_roles(old_role, reason="Auto remove old role by bot")
                        removed_count += 1
                    except Exception as e:
                        logger.error(f"Error auto-removing role: {e}")
            if removed_count > 0:
                logger.info(f"Auto-removed role {old_role.name} from {removed_count} members in guild {guild.name}")

    @auto_remove_old_role.before_loop
    async def before_auto_remove_old_role(self):
        await self.bot.wait_until_ready()

    @commands.Cog.listener()
    async def on_raw_reaction_add(self, payload):
        """Handle role assignment when reaction is added"""
        if payload.message_id not in self.role_messages:
            return
            
        guild = self.bot.get_guild(payload.guild_id)
        if not guild:
            return
            
        member = guild.get_member(payload.user_id)
        if member.bot:
            return
            
        role_data = self.role_messages[payload.message_id]
        if str(payload.emoji) in role_data["roles"]:
            role = guild.get_role(role_data["roles"][str(payload.emoji)])
            if role:
                try:
                    # Check if bot has permission to manage roles
                    if not guild.me.guild_permissions.manage_roles:
                        logger.warning(f"Bot doesn't have permission to manage roles in guild {guild.id}")
                        return
                        
                    # Check if role is manageable
                    if role >= guild.me.top_role:
                        logger.warning(f"Role {role.name} is higher than bot's highest role in guild {guild.id}")
                        return
                        
                    await member.add_roles(role)
                    logger.info(f"Added role {role.name} to {member.name}")
                except discord.Forbidden:
                    logger.error(f"Bot doesn't have permission to add role {role.name} to {member.name}")
                except Exception as e:
                    logger.error(f"Error adding role: {e}")

    @commands.Cog.listener()
    async def on_raw_reaction_remove(self, payload):
        """Handle role removal when reaction is removed"""
        if payload.message_id not in self.role_messages:
            return
            
        guild = self.bot.get_guild(payload.guild_id)
        if not guild:
            return
            
        member = guild.get_member(payload.user_id)
        if member.bot:
            return
            
        role_data = self.role_messages[payload.message_id]
        if str(payload.emoji) in role_data["roles"]:
            role = guild.get_role(role_data["roles"][str(payload.emoji)])
            if role:
                try:
                    # Check if bot has permission to manage roles
                    if not guild.me.guild_permissions.manage_roles:
                        logger.warning(f"Bot doesn't have permission to manage roles in guild {guild.id}")
                        return
                        
                    # Check if role is manageable
                    if role >= guild.me.top_role:
                        logger.warning(f"Role {role.name} is higher than bot's highest role in guild {guild.id}")
                        return
                        
                    await member.remove_roles(role)
                    logger.info(f"Removed role {role.name} from {member.name}")
                except discord.Forbidden:
                    logger.error(f"Bot doesn't have permission to remove role {role.name} from {member.name}")
                except Exception as e:
                    logger.error(f"Error removing role: {e}")

async def setup(bot):
    await bot.add_cog(Roles(bot))

