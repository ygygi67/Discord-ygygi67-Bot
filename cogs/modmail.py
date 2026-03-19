import discord
from discord.ext import commands
import logging
from datetime import datetime

logger = logging.getLogger('discord_bot')

class Modmail(commands.Cog):
    def __init__(self, bot):
        self.bot = bot
        self.category_id = 1478650262833987687
        # We find or use a specific server for these channels. 
        # Usually, the bot is in a main server. We'll use the first one it's in or a config ID.
        self.main_guild_id = 1171254331643789332 # The sync guild ID used in bot.py

    async def get_or_create_channel(self, guild, user):
        """Find existing member channel in category or create new one"""
        category = guild.get_channel(self.category_id)
        if not category or not isinstance(category, discord.CategoryChannel):
            logger.warning(f"Category {self.category_id} not found in guild {guild.name}")
            return None

        channel_name = f"💬︰{user.name}".lower().replace(" ", "-")
        # Seek by topic or name
        for channel in category.text_channels:
            if channel.topic == str(user.id):
                return channel
        
        # Create new channel
        overwrites = {
            guild.default_role: discord.PermissionOverwrite(view_channel=False),
            guild.me: discord.PermissionOverwrite(view_channel=True, send_messages=True)
        }
        
        try:
            new_channel = await category.create_text_channel(
                name=channel_name,
                topic=str(user.id),
                overwrites=overwrites,
                reason=f"Support channel for {user.name}"
            )
            return new_channel
        except Exception as e:
            logger.error(f"Failed to create support channel: {e}")
            return None

    @commands.Cog.listener()
    async def on_message(self, message):
        if message.author.bot:
            return

        # Case 1: Message is a Direct Message to the bot (User -> Bot/Staff)
        if isinstance(message.channel, discord.DMChannel):
            guild = self.bot.get_guild(self.main_guild_id)
            if not guild:
                return

            channel = await self.get_or_create_channel(guild, message.author)
            if not channel:
                return

            embed = discord.Embed(
                title="📥 ข้อความใหม่จากผู้ใช้",
                description=f"**ผู้ส่ง:** {message.author.mention} ({message.author.name})\n\n**เนื้อหา:**\n{message.content or '*[ไม่มีข้อความ]*'}",
                color=discord.Color.blue(),
                timestamp=datetime.now()
            )
            embed.set_author(name=f"คุยกับ: {message.author.name}", icon_url=message.author.display_avatar.url)
            embed.set_footer(text=f"User ID: {message.author.id}")
            
            # Forward attachments
            if message.attachments:
                embed.set_image(url=message.attachments[0].url)
            
            await channel.send(embed=embed)
            # Add reaction to user's DM to confirm receipt

        # Case 2: Message is in a Modmail channel (Staff -> User)
        elif message.guild and message.guild.id == self.main_guild_id:
            if message.channel.category_id == self.category_id:
                # The topic stores the User ID
                try:
                    user_id_str = message.channel.topic
                    if not user_id_str or not user_id_str.isdigit():
                        return
                        
                    user_id = int(user_id_str)
                    user = await self.bot.fetch_user(user_id)
                    if not user:
                        return
                    
                    # Create relay embed for the USER
                    embed = discord.Embed(
                        title="💬 การตอบกลับจากแอดมิน",
                        description=f"**แอดมิน {message.author.name} ส่งถึงคุณ:**\n\n{message.content or '*[ไม่มีข้อความ]*'}",
                        color=discord.Color.green(),
                        timestamp=datetime.now()
                    )
                    embed.set_author(name=f"Admin: {message.author.name}", icon_url=message.author.display_avatar.url)
                    embed.set_footer(text=f"ตอบจากเซิร์ฟเวอร์ {message.guild.name}")
                    
                    if message.attachments:
                        embed.set_image(url=message.attachments[0].url)
                    
                    await user.send(embed=embed)

                except Exception as e:
                    logger.warning(f"Modmail relay error: {e}")

async def setup(bot):
    await bot.add_cog(Modmail(bot))
    logger.info("Modmail cog loaded: DM Relay System active")
