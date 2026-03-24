import discord
from discord.ext import commands
import logging
import os

logger = logging.getLogger('discord_bot')

class BaseCog(commands.Cog):
    def __init__(self, bot):
        self.bot = bot
        self.allowed_user_id = "1034845842709958786"
        self.admin_users = set()

    def is_admin(self, user_id):
        """Check if user is an admin"""
        return str(user_id) == self.allowed_user_id or str(user_id) in self.admin_users

async def setup(bot):
    await bot.add_cog(BaseCog(bot))
    logger.info("Base cog loaded")

async def setup_hook(self):
    # Clear any existing cogs first
    for cog in list(self.extensions):
        await self.unload_extension(cog)
        logger.info(f'Unloaded cog: {cog}')

    # Load cogs
    for filename in os.listdir('./cogs'):
        if filename.endswith('.py'):
            cog_name = f'cogs.{filename[:-3]}'
            if cog_name not in self.extensions:  # Check if already loaded
                try:
                    await self.load_extension(cog_name)
                    logger.info(f'Loaded cog: {filename}')
                except Exception as e:
                    logger.error(f'Failed to load cog {filename}: {e}')
            else:
                logger.warning(f'Cog {cog_name} is already loaded, skipping.')

    # Sync commands
    try:
        synced = await self.tree.sync()
        logger.info(f"Synced {len(synced)} command(s)")
    except Exception as e:
        logger.error(f"Failed to sync commands: {e}") 