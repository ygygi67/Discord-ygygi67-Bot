import discord
from discord import app_commands
from discord.ext import commands
import logging
import io
import os
from datetime import datetime
from PIL import Image, ImageDraw, ImageFont

logger = logging.getLogger('discovery_cog')

class Discovery(commands.Cog, name="Discovery"):
    def __init__(self, bot):
        self.bot = bot
        self.bot_admin_id = 1034845842709958786 # Based on utility.py

    def _is_bot_admin(self, user_id: int) -> bool:
        """ตรวจสอบว่าเป็นแอดมินบอทหรือไม่"""
        admin_cog = self.bot.get_cog('Admin')
        if admin_cog and hasattr(admin_cog, 'is_admin'):
            return admin_cog.is_admin(user_id)
        return user_id == self.bot_admin_id

    @app_commands.command(name="ค้นหาเพื่อนร่วมกลุ่ม", description="ค้นหาเซิร์ฟเวอร์ที่คนสองคนอยู่ร่วมกัน")
    @app_commands.describe(คนแรก="สมาชิกคนแรก", คนที่สอง="สมาชิกคนที่สอง (ถ้าไม่ใส่จะเทียบกับตัวคุณเอง)")
    async def find_shared_guilds(self, interaction: discord.Interaction, คนแรก: discord.User, คนที่สอง: discord.User = None):
        user1 = คนแรก
        user2 = คนที่สอง or interaction.user
        
        is_admin = interaction.user.guild_permissions.administrator
        is_bot_admin = self._is_bot_admin(interaction.user.id)
        
        await interaction.response.defer()
        
        shared_guilds = []
        for guild in self.bot.guilds:
            member1 = guild.get_member(user1.id)
            member2 = guild.get_member(user2.id)
            
            if member1 and member2:
                shared_guilds.append({
                    'guild': guild,
                    'm1': member1,
                    'm2': member2
                })
        
        if not shared_guilds:
            return await interaction.followup.send(f"❌ ไม่พบเซิร์ฟเวอร์ที่ **{user1.display_name}** และ **{user2.display_name}** อยู่ร่วมกัน")

        embed = discord.Embed(
            title="🔍 ผลการค้นหาเซิร์ฟเวอร์ร่วม",
            description=f"พบทั้งหมด **{len(shared_guilds)}** เซิร์ฟเวอร์ที่อยู่ด้วยกัน",
            color=discord.Color.blue()
        )
        embed.set_author(name=f"{user1.name} & {user2.name}", icon_url=user1.display_avatar.url)

        for item in shared_guilds[:15]: # Limit to 15 to avoid embed overflow
            g = item['guild']
            m1 = item['m1']
            m2 = item['m2']
            
            if is_admin or is_bot_admin:
                # Detailed view for admins
                m1_roles = [r.name for r in m1.roles[1:]][-3:] # Last 3 roles
                m2_roles = [r.name for r in m2.roles[1:]][-3:]
                
                info = (f"🆔 ID: `{g.id}`\n"
                        f"👤 **{user1.name}**: {', '.join(m1_roles) or 'ไม่มีสี'}\n"
                        f"👥 **{user2.name}**: {', '.join(m2_roles) or 'ไม่มีสี'}")
                embed.add_field(name=f"🏰 {g.name}", value=info, inline=False)
            else:
                # Basic view for users
                embed.add_field(name=f"🏰 {g.name}", value=f"ยศสูงสุด: {m1.top_role.name} / {m2.top_role.name}", inline=True)

        if len(shared_guilds) > 15:
            embed.set_footer(text=f"และอีก {len(shared_guilds)-15} เซิร์ฟเวอร์...")

        # Relationship Map for Admins
        if is_admin or is_bot_admin:
            try:
                map_file = await self.create_relationship_map(user1, user2, shared_guilds)
                await interaction.followup.send(embed=embed, file=map_file)
            except Exception as e:
                logger.error(f"Error creating map: {e}")
                await interaction.followup.send(embed=embed)
        else:
            await interaction.followup.send(embed=embed)

    async def create_relationship_map(self, u1, u2, shared_items):
        # Create a simple graph image using PIL
        width, height = 800, 600
        img = Image.new('RGB', (width, height), color=(35, 39, 42)) # Discord dark gray
        draw = ImageDraw.Draw(img)
        
        # Positions
        u1_pos = (150, height // 2)
        u2_pos = (width - 150, height // 2)
        
        # Max 8 guilds in map
        map_items = shared_items[:8]
        
        # Draw connections
        for i, item in enumerate(map_items):
            # Guild pos
            g_x = width // 2
            g_y = 100 + (i * 60)
            
            # Draw lines
            draw.line([u1_pos, (g_x, g_y)], fill=(114, 137, 218), width=2) # Blurple
            draw.line([u2_pos, (g_x, g_y)], fill=(114, 137, 218), width=2)
            
            # Draw Guild box
            box_w, box_h = 160, 40
            draw.rectangle([g_x - box_w//2, g_y - box_h//2, g_x + box_w//2, g_y + box_h//2], 
                           fill=(44, 47, 51), outline=(255, 255, 255))
            
            # Guild Name (Simple text)
            g_name = item['guild'].name
            if len(g_name) > 15: g_name = g_name[:12] + "..."
            draw.text((g_x - 70, g_y - 10), g_name, fill=(255, 255, 255))

        # Draw Users
        for pos, user_name in [(u1_pos, u1.name), (u2_pos, u2.name)]:
            radius = 50
            draw.ellipse([pos[0]-radius, pos[1]-radius, pos[0]+radius, pos[1]+radius], 
                         fill=(114, 137, 218), outline=(255, 255, 255), width=3)
            
            # User Name
            name_disp = user_name[:10]
            draw.text((pos[0]-30, pos[1]-10), name_disp, fill=(255, 255, 255))

        # Save to buffer
        buf = io.BytesIO()
        img.save(buf, format='PNG')
        buf.seek(0)
        return discord.File(buf, filename="relationship_map.png")

async def setup(bot):
    await bot.add_cog(Discovery(bot))
