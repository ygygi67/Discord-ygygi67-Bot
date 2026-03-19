import discord
from discord.ext import commands
import logging
from datetime import datetime

logger = logging.getLogger('discord_bot')

class ServerLogger(commands.Cog):
    def __init__(self, bot):
        self.bot = bot
        self.log_channel_id = 1467898137459949742
        self.invites = {} # Guild ID -> {Invite Code -> Uses}
        logger.info(f"ServerLogger initialized with target channel: {self.log_channel_id}")

    @commands.Cog.listener()
    async def on_ready(self):
        """Pre-fetch invites for tracking"""
        for guild in self.bot.guilds:
            try:
                self.invites[guild.id] = {invite.code: invite.uses for invite in await guild.invites()}
            except:
                pass
        logger.info("Invite tracking initialized for all guilds.")

    @commands.Cog.listener()
    async def on_guild_join(self, guild):
        """Update invite tracking for new guilds"""
        try:
            self.invites[guild.id] = {invite.code: invite.uses for invite in await guild.invites()}
        except:
            pass

    async def send_log(self, embed, guild=None):
        """Helper to send logs to the designated channel"""
        # If guild is provided, identify which server
        if guild:
            embed.set_footer(text=f"Server: {guild.name} | ID: {guild.id}")
        elif not embed.footer:
            embed.set_footer(text="System Log")
            
        channel = self.bot.get_channel(self.log_channel_id)
        if channel:
            try:
                await channel.send(embed=embed)
            except Exception as e:
                logger.error(f"Failed to send log to channel: {e}")
        else:
            # Try to fetch if not in cache (could happen on first log after restart)
            try:
                channel = await self.bot.fetch_channel(self.log_channel_id)
                if channel:
                    await channel.send(embed=embed)
            except:
                pass

    @commands.Cog.listener()
    async def on_member_update(self, before, after):
        """Track nickname, roles, and server-specific profile changes"""
        embed = discord.Embed(color=discord.Color.blue(), timestamp=datetime.now())
        embed.set_author(name=f"{after.name}#{after.discriminator}", icon_url=after.display_avatar.url)
        embed.set_footer(text=f"User ID: {after.id}")
        
        changed = False

        # Nickname change
        if before.nick != after.nick:
            embed.title = "📝 เปลี่ยนชื่อเล่น"
            embed.add_field(name="คนเดิม", value=before.nick or "ไม่มี", inline=True)
            embed.add_field(name="ปัจจุบัน", value=after.nick or "ไม่มี", inline=True)
            changed = True
            
        # Avatar changes (Global and Server)
        avatar_changed = False
        if before.avatar != after.avatar or before.guild_avatar != after.guild_avatar:
            avatar_embed = discord.Embed(title="🖼️ เปลี่ยนรูปโปรไฟล์", color=discord.Color.blue(), timestamp=datetime.now())
            avatar_embed.set_author(name=after.name, icon_url=after.display_avatar.url)
            avatar_embed.description = f"{after.mention} ได้ทำการเปลี่ยนรูปโปรไฟล์"
            
            if before.display_avatar:
                avatar_embed.set_thumbnail(url=before.display_avatar.url)
                avatar_embed.add_field(name="รูปเดิม", value=f"[คลิกที่นี่]({before.display_avatar.url})")
            
            avatar_embed.set_image(url=after.display_avatar.url)
            avatar_embed.add_field(name="รูปใหม่", value=f"[คลิกที่นี่]({after.display_avatar.url})")
            avatar_embed.set_footer(text=f"User ID: {after.id}")
            await self.send_log(avatar_embed, after.guild)

        # Timeout check
        if before.timed_out_until != after.timed_out_until:
             if after.timed_out_until:
                 embed.title = "⏳ สมาชิกถูกจำกัดเวลา (Timeout)"
                 embed.description = f"{after.mention} ถูก Timeout จนถึง {discord.utils.format_dt(after.timed_out_until)}"
                 embed.color = discord.Color.dark_red()
             else:
                 embed.title = "🔓 ยกเลิกการจำกัดเวลา"
                 embed.description = f"{after.mention} พ้นช่วง Timeout แล้ว"
                 embed.color = discord.Color.green()
             changed = True

        if changed:
            await self.send_log(embed, after.guild)
            
        # Role update
        if before.roles != after.roles:
            role_embed = discord.Embed(title="🛡️ อัปเดตบทบาทสมาชิก", color=discord.Color.blue(), timestamp=datetime.now())
            role_embed.set_author(name=after.name, icon_url=after.display_avatar.url)
            
            added = [role.mention for role in after.roles if role not in before.roles]
            removed = [role.mention for role in before.roles if role not in after.roles]
            
            if added:
                role_embed.add_field(name="✅ เพิ่มบทบาท", value=", ".join(added))
            if removed:
                role_embed.add_field(name="❌ ลบบทบาท", value=", ".join(removed))
                
            # Try to find who did it
            async for entry in after.guild.audit_logs(limit=1, action=discord.AuditLogAction.member_role_update):
                if entry.target.id == after.id:
                    role_embed.add_field(name="โดย", value=entry.user.mention, inline=False)
                    break
            
            await self.send_log(role_embed)

        # Banner change (Server Specific)
        if hasattr(after, 'display_banner') and before.display_banner != after.display_banner:
            banner_embed = discord.Embed(title="🖼️ เปลี่ยนแบนเนอร์โปรไฟล์", color=discord.Color.blue(), timestamp=datetime.now())
            banner_embed.set_author(name=after.name, icon_url=after.display_avatar.url)
            banner_embed.description = "สมาชิกมีการเปลี่ยนแบนเนอร์โปรไฟล์"
            await self.send_log(banner_embed)

    @commands.Cog.listener()
    async def on_user_update(self, before, after):
        """Track global profile changes (Avatar, Username)"""
        embed = discord.Embed(color=discord.Color.blue(), timestamp=datetime.now())
        embed.set_author(name=f"{after.name}", icon_url=after.display_avatar.url)
        embed.set_footer(text=f"User ID: {after.id}")

        # Avatar change
        if before.avatar != after.avatar:
            embed.title = "🖼️ เปลี่ยนรูปโปรไฟล์หลัก"
            embed.description = "ผู้ใช้เปลี่ยนรูปโปรไฟล์หลักของบัญชี"
            if before.avatar:
                embed.set_thumbnail(url=before.avatar.url)
        # Name change
        if before.name != after.name:
            embed.title = "👤 เปลี่ยนชื่อผู้ใช้"
            embed.add_field(name="ชื่อเดิม", value=before.name, inline=True)
            embed.add_field(name="ชื่อใหม่", value=after.name, inline=True)
            await self.send_log(embed)

    @commands.Cog.listener()
    async def on_voice_state_update(self, member, before, after):
        """Track voice actions (Mute, Deaf, Join, Leave, Move) with Audit Log attribution"""
        embed = discord.Embed(color=discord.Color.orange(), timestamp=datetime.now())
        embed.set_author(name=member.name, icon_url=member.display_avatar.url)
        embed.set_footer(text=f"User ID: {member.id}")

        now = datetime.utcnow()

        # Channel Join/Leave/Move
        if before.channel != after.channel:
            if before.channel is None:
                embed.title = "🔊 เข้าช่องเสียง"
                embed.description = f"{member.mention} เข้าช่อง {after.channel.mention} (**{after.channel.name}**)"
                embed.color = discord.Color.green()
            elif after.channel is None:
                embed.title = "🔇 ออกจากช่องเสียง"
                embed.description = f"{member.mention} ออกจากช่อง {before.channel.mention} (**{before.channel.name}**)"
                embed.color = discord.Color.red()
                
                # Check for disconnect by admin
                try:
                    async for entry in member.guild.audit_logs(limit=5, action=discord.AuditLogAction.member_disconnect):
                        if entry.target.id == member.id and (now - entry.created_at).total_seconds() < 10:
                            embed.add_field(name="⚠️ ตัดการเชื่อมต่อโดย", value=f"{entry.user.mention} ({entry.user.name})", inline=False)
                            embed.title = "🚫 ถูกตัดการเชื่อมต่อจากช่องเสียง"
                            break
                except: pass
            else:
                embed.title = "🔄 ย้ายช่องเสียง"
                embed.description = f"{member.mention} ย้ายจาก {before.channel.mention} ไปยัง {after.channel.mention}"
                
                # Check for move by admin
                try:
                    async for entry in member.guild.audit_logs(limit=5, action=discord.AuditLogAction.member_move):
                        # member_move extra attribute contains the channel they were moved TO
                        if entry.target.id == member.id and (now - entry.created_at).total_seconds() < 10:
                            embed.add_field(name="👤 ดำเนินการโดย", value=f"{entry.user.mention} ({entry.user.name})", inline=False)
                            embed.description = f"{member.mention} ถูกย้ายจาก {before.channel.mention} ไปยัง {after.channel.mention}"
                            break
                except: pass
                
            await self.send_log(embed, member.guild)
            return

        # Mute/Deaf changes
        status_changes = []
        is_admin_action = False
        
        if before.self_mute != after.self_mute:
            status_changes.append("🔇 ปิดไมค์ (Self)" if after.self_mute else "🎙️ เปิดไมค์ (Self)")
        if before.self_deaf != after.self_deaf:
            status_changes.append("🎧 ปิดหู (Self)" if after.self_deaf else "🔊 เปิดหู (Self)")
        
        # Server mute/deaf (Admin actions usually)
        if before.mute != after.mute:
            status_changes.append("🚨 **ถูกปิดไมค์โดยแอดมิน**" if after.mute else "✅ **ถูกยกเลิกการปิดไมค์**")
            is_admin_action = True
        if before.deaf != after.deaf:
            status_changes.append("🚨 **ถูกปิดหูโดยแอดมิน**" if after.deaf else "✅ **ถูกยกเลิกการปิดหู**")
            is_admin_action = True

        if status_changes:
            embed.title = "🎙️ สถานะเสียงเปลี่ยนไป"
            embed.description = f"{member.mention} : " + ", ".join(status_changes)
            if after.channel:
                embed.description += f"\nในช่อง: {after.channel.mention}"
            
            if is_admin_action:
                try:
                    async for entry in member.guild.audit_logs(limit=5, action=discord.AuditLogAction.member_update):
                        if entry.target.id == member.id and (now - entry.created_at).total_seconds() < 10:
                            if hasattr(entry.after, 'mute') or hasattr(entry.after, 'deaf'):
                                embed.add_field(name="🛡️ ดำเนินการโดย", value=f"{entry.user.mention} ({entry.user.name})", inline=False)
                                break
                except: pass
                
            await self.send_log(embed, member.guild)

    @commands.Cog.listener()
    async def on_app_command_completion(self, interaction: discord.Interaction, command: discord.app_commands.Command):
        """Log command usage to the log channel (Console/Console simulation)"""
        embed = discord.Embed(title="⌨️ ใช้คำสั่ง", color=discord.Color.light_grey(), timestamp=datetime.now())
        embed.set_author(name=interaction.user.name, icon_url=interaction.user.display_avatar.url)
        embed.description = f"ใช้คำสั่ง `/{command.name}` ในช่อง {interaction.channel.mention if hasattr(interaction.channel, 'mention') else 'DM'}"
        
        # Add options if any
        if interaction.data.get('options'):
            options = []
            for opt in interaction.data['options']:
                options.append(f"**{opt['name']}:** `{opt['value']}`")
            embed.add_field(name="รายละเอียด", value="\n".join(options), inline=False)
            
        await self.send_log(embed, interaction.guild)

    @commands.Cog.listener()
    async def on_guild_update(self, before, after):
        """Track server level changes (Name, Description, Icon)"""
        embed = discord.Embed(title="⚙️ ข้อมูลเซิร์ฟเวอร์เปลี่ยนไป", color=discord.Color.purple(), timestamp=datetime.now())
        
        changed = False
        if before.name != after.name:
            embed.add_field(name="เปลี่ยนชื่อเซิร์ฟเวอร์", value=f"จาก `{before.name}` เป็น `{after.name}`", inline=False)
            changed = True
        
        if before.description != after.description:
            embed.add_field(name="เปลี่ยนคำอธิบายเซิร์ฟเวอร์", value=f"**เดิม:** {before.description or 'ไม่มี'}\n**ใหม่:** {after.description or 'ไม่มี'}", inline=False)
            changed = True

        if before.icon != after.icon:
            embed.add_field(name="เปลี่ยนรูปไอคอนเซิร์ฟเวอร์", value="มีการอัปเดตรูปไอคอนใหม่", inline=False)
            if after.icon:
                embed.set_thumbnail(url=after.icon.url)
            changed = True

        if changed:
            await self.send_log(embed, after)

    @commands.Cog.listener()
    async def on_message_delete(self, message):
        """Track deleted messages with specific image support"""
        if message.author.bot:
            return
            
        is_image = False
        if message.attachments:
             for a in message.attachments:
                 if a.content_type and 'image' in a.content_type:
                     is_image = True
                     break

        title = "🗑️ ลบข้อความ"
        if is_image:
            title = f"🖼️ Image sent by {message.author.name} Deleted"

        embed = discord.Embed(title=title, color=discord.Color.red(), timestamp=datetime.now())
        embed.set_author(name=message.author.name, icon_url=message.author.display_avatar.url)
        embed.description = f"**ถูกลบในช่อง:** {message.channel.mention}"
        
        content = message.content or "[ไม่มีเนื้อหาข้อความ]"
        if message.attachments:
             content += "\n\n**ไฟล์แนบ:**\n" + "\n".join([f"[{a.filename}]({a.url})" for a in message.attachments])
             # Set image if possible
             for a in message.attachments:
                 if a.content_type and 'image' in a.content_type:
                     embed.set_image(url=a.proxy_url)
                     break
        
        embed.add_field(name="เนื้อหา", value=content[:1024], inline=False)
        
        # Try to see who deleted it
        try:
            async for entry in message.guild.audit_logs(limit=1, action=discord.AuditLogAction.message_delete):
                if entry.target.id == message.author.id and (datetime.utcnow() - entry.created_at).total_seconds() < 5:
                    embed.add_field(name="ลบโดย", value=entry.user.mention, inline=False)
                    break
        except:
            pass
            
        embed.set_footer(text=f"Author: {message.author.id} | Message ID: {message.id}")
        await self.send_log(embed, message.guild)

    @commands.Cog.listener()
    async def on_bulk_message_delete(self, messages):
        """Track bulk deleted messages"""
        if not messages:
            return
            
        guild = messages[0].guild
        channel = messages[0].channel
        
        embed = discord.Embed(title="🧹 ลบข้อความจำนวนมาก (Bulk Delete)", color=discord.Color.red(), timestamp=datetime.now())
        embed.description = f"มีการลบข้อความออกจำนวน **{len(messages)}** ข้อความ ในช่อง {channel.mention}"
        embed.set_footer(text=f"Channel ID: {channel.id}")
        await self.send_log(embed, guild)

    @commands.Cog.listener()
    async def on_message_edit(self, before, after):
        """Track edited messages"""
        if before.author.bot or before.content == after.content:
            return
            
        embed = discord.Embed(title="✏️ แก้ไขข้อความ", color=discord.Color.yellow(), timestamp=datetime.now())
        embed.set_author(name=after.author.name, icon_url=after.display_avatar.url)
        embed.add_field(name="ช่อง", value=after.channel.mention, inline=True)
        embed.add_field(name="ก่อนแก้ไข", value=before.content or "[ไม่มีข้อความ]", inline=False)
        embed.add_field(name="หลังแก้ไข", value=after.content or "[ไม่มีข้อความ]", inline=False)
        
        if after.attachments:
            embed.add_field(name="ไฟล์แนบ", value="\n".join([f"[{a.filename}]({a.url})" for a in after.attachments]))

        embed.set_footer(text=f"Author ID: {after.author.id} | Message ID: {after.id}")
        await self.send_log(embed, after.guild)

    @commands.Cog.listener()
    async def on_message(self, message):
        """Log all messages (Be careful with spam, usually used for auditing)"""
        if message.author.bot or not message.guild:
            return
            
        # Optional: Only log if it has attachments or special content to save space
        if message.attachments:
            embed = discord.Embed(title="📎 ส่งไฟล์แนบ", color=discord.Color.light_grey(), timestamp=datetime.now())
            embed.set_author(name=message.author.name, icon_url=message.author.display_avatar.url)
            embed.description = f"ส่งไฟล์ในช่อง {message.channel.mention}"
            embed.add_field(name="ชื่อไฟล์", value="\n".join([a.filename for a in message.attachments]))
            embed.set_footer(text=f"User ID: {message.author.id}")
            await self.send_log(embed, message.guild)

    @commands.Cog.listener()
    async def on_guild_channel_update(self, before, after):
        embed = discord.Embed(title="⚙️ อัปเดตนิยามช่อง", color=discord.Color.blue(), timestamp=datetime.now())
        embed.description = f"ช่อง: {after.mention} ({after.name})"
        
        changed = False
        if before.name != after.name:
            embed.add_field(name="เปลี่ยนชื่อช่อง", value=f"จาก `{before.name}` เป็น `{after.name}`", inline=False)
            changed = True
        
        if before.category != after.category:
            embed.add_field(name="ย้ายหมวดหมู่", value=f"จาก `{before.category}` เป็น `{after.category}`", inline=False)
            changed = True

        if changed:
            async for entry in after.guild.audit_logs(limit=1, action=discord.AuditLogAction.channel_update):
                if entry.target.id == after.id:
                    embed.add_field(name="โดย", value=entry.user.mention, inline=False)
                    break
            await self.send_log(embed)

    @commands.Cog.listener()
    async def on_guild_role_update(self, before, after):
        embed = discord.Embed(title="🛡️ อัปเดตบทบาท", color=after.color if after.color else discord.Color.blue(), timestamp=datetime.now())
        embed.description = f"บทบาท: {after.mention}"
        
        changed = False
        if before.name != after.name:
            embed.add_field(name="เปลี่ยนชื่อบทบาท", value=f"จาก `{before.name}` เป็น `{after.name}`", inline=False)
            changed = True
        if before.color != after.color:
            embed.add_field(name="เปลี่ยนสี", value=f"จาก `{before.color}` เป็น `{after.color}`", inline=False)
            changed = True
        if before.permissions != after.permissions:
            embed.add_field(name="เปลี่ยนสิทธิ์ (Permissions)", value="มีการแก้ไขสิทธิ์ของบทบาท", inline=False)
            changed = True

        if changed:
            async for entry in after.guild.audit_logs(limit=1, action=discord.AuditLogAction.role_update):
                if entry.target.id == after.id:
                    embed.add_field(name="โดย", value=entry.user.mention, inline=False)
                    break
            await self.send_log(embed)

    @commands.Cog.listener()
    async def on_thread_create(self, thread):
        embed = discord.Embed(title="🧵 สร้างเธรดใหม่", color=discord.Color.green(), timestamp=datetime.now())
        embed.description = f"เธรด: **{thread.name}** ในช่อง {thread.parent.mention}"
        await self.send_log(embed)

    @commands.Cog.listener()
    async def on_thread_delete(self, thread):
        embed = discord.Embed(title="🗑️ ลบทราด", color=discord.Color.red(), timestamp=datetime.now())
        embed.description = f"เธรดที่ถูกลบ: **{thread.name}**"
        await self.send_log(embed)

    @commands.Cog.listener()
    async def on_guild_channel_create(self, channel):
        embed = discord.Embed(title="🆕 สร้างช่องใหม่", color=discord.Color.green(), timestamp=datetime.now())
        embed.description = f"ช่อง: **{channel.name}** ({channel.mention})\nประเภท: {channel.type}"
        
        # Try to find who created it
        async for entry in channel.guild.audit_logs(limit=1, action=discord.AuditLogAction.channel_create):
            embed.add_field(name="โดย", value=f"{entry.user.mention} ({entry.user.name})")
            break
            
        await self.send_log(embed)

    @commands.Cog.listener()
    async def on_guild_channel_delete(self, channel):
        embed = discord.Embed(title="🗑️ ลบช่อง", color=discord.Color.red(), timestamp=datetime.now())
        embed.description = f"ช่องที่ถูกลบ: **{channel.name}**\nประเภท: {channel.type}"
        
        async for entry in channel.guild.audit_logs(limit=1, action=discord.AuditLogAction.channel_delete):
            embed.add_field(name="โดย", value=f"{entry.user.mention} ({entry.user.name})")
            break
            
        await self.send_log(embed)

    @commands.Cog.listener()
    async def on_guild_role_create(self, role):
        embed = discord.Embed(title="🎭 สร้างบทบาทใหม่", color=discord.Color.green(), timestamp=datetime.now())
        embed.description = f"บทบาท: {role.mention}"
        
        async for entry in role.guild.audit_logs(limit=1, action=discord.AuditLogAction.role_create):
            embed.add_field(name="โดย", value=f"{entry.user.mention} ({entry.user.name})")
            break
            
        await self.send_log(embed)

    @commands.Cog.listener()
    async def on_guild_role_delete(self, role):
        embed = discord.Embed(title="🗑️ ลบบทบาท", color=discord.Color.red(), timestamp=datetime.now())
        embed.description = f"บทบาทที่ถูกลบ: **{role.name}**"
        
        async for entry in role.guild.audit_logs(limit=1, action=discord.AuditLogAction.role_delete):
            embed.add_field(name="โดย", value=f"{entry.user.mention} ({entry.user.name})")
            break
            
        await self.send_log(embed)

    @commands.Cog.listener()
    async def on_member_join(self, member):
        embed = discord.Embed(title="📥 สมาชิกใหม่เข้าร่วม", color=discord.Color.green(), timestamp=datetime.now())
        embed.set_author(name=member.name, icon_url=member.display_avatar.url)
        embed.description = f"{member.mention} เข้าร่วมเซิร์ฟเวอร์"
        embed.add_field(name="สร้างบัญชีเมื่อ", value=f"{member.created_at.strftime('%d/%m/%Y')}\n({discord.utils.format_dt(member.created_at, 'R')})")
        embed.set_footer(text=f"ID: {member.id}")
        
        # Invite tracking
        inviter_text = "ไม่พบข้อมูลผู้เชิญ"
        if member.guild.id in self.invites:
            try:
                current_invites = await member.guild.invites()
                for invite in current_invites:
                    if invite.code in self.invites[member.guild.id]:
                        if invite.uses > self.invites[member.guild.id][invite.code]:
                            inviter_text = f"ชวนโดย: {invite.inviter.mention} (`{invite.inviter.name}`)\nลิงก์: {invite.code}"
                            # Update cache
                            self.invites[member.guild.id][invite.code] = invite.uses
                            break
            except:
                pass
        
        embed.add_field(name="การชวน", value=inviter_text, inline=False)
        await self.send_log(embed, member.guild)

    @commands.Cog.listener()
    async def on_member_remove(self, member):
        embed = discord.Embed(title="📤 สมาชิกออกจากเซิร์ฟเวอร์", color=discord.Color.red(), timestamp=datetime.now())
        embed.set_author(name=member.name, icon_url=member.display_avatar.url)
        embed.description = f"{member.mention} ออกจากเซิร์ฟเวอร์"
        embed.set_footer(text=f"ID: {member.id}")
        
        # Check if it was a kick
        async for entry in member.guild.audit_logs(limit=1, action=discord.AuditLogAction.kick):
            if entry.target.id == member.id:
                embed.title = "👢 สมาชิกถูกเตะ"
                embed.add_field(name="โดย", value=entry.user.mention)
                embed.add_field(name="เหตุผล", value=entry.reason or "ไม่ระบุ")
                break
                
        await self.send_log(embed)

    @commands.Cog.listener()
    async def on_member_ban(self, guild, user):
        embed = discord.Embed(title="🔨 สมาชิกถูกแบน", color=discord.Color.dark_red(), timestamp=datetime.now())
        embed.set_author(name=user.name, icon_url=user.display_avatar.url)
        embed.description = f"**{user.name}** ถูกแบนจากเซิร์ฟเวอร์"
        
        async for entry in guild.audit_logs(limit=1, action=discord.AuditLogAction.ban):
            if entry.target.id == user.id:
                embed.add_field(name="โดย", value=entry.user.mention)
                embed.add_field(name="เหตุผล", value=entry.reason or "ไม่ระบุ")
                break
        
        embed.set_footer(text=f"ID: {user.id}")
        await self.send_log(embed, guild)

    @commands.Cog.listener()
    async def on_member_unban(self, guild, user):
        embed = discord.Embed(title="🔓 ยกเลิกการแบน", color=discord.Color.green(), timestamp=datetime.now())
        embed.set_author(name=user.name, icon_url=user.display_avatar.url)
        embed.description = f"ยกเลิกการแบนให้ **{user.name}**"
        
        async for entry in guild.audit_logs(limit=1, action=discord.AuditLogAction.unban):
            if entry.target.id == user.id:
                embed.add_field(name="โดย", value=entry.user.mention)
                break
                
        await self.send_log(embed, guild)


    @commands.Cog.listener()
    async def on_invite_create(self, invite):
        embed = discord.Embed(title="📩 สร้างลิงก์เชิญ", color=discord.Color.blue(), timestamp=datetime.now())
        embed.description = f"ลิงก์: `{invite.url}` ในช่อง {invite.channel.mention}"
        embed.add_field(name="โดย", value=invite.inviter.mention if invite.inviter else "ระบบ")
        embed.add_field(name="หมดอายุ", value="ไม่มี" if invite.max_age == 0 else f"{invite.max_age // 60} นาที")
        embed.set_footer(text=f"Code: {invite.code}")
        
        # Update cache
        if invite.guild.id not in self.invites:
            self.invites[invite.guild.id] = {}
        self.invites[invite.guild.id][invite.code] = invite.uses
        
        await self.send_log(embed, invite.guild)


    @commands.Cog.listener()
    async def on_invite_delete(self, invite):
        embed = discord.Embed(title="🗑️ ลบลิงก์เชิญ", color=discord.Color.red(), timestamp=datetime.now())
        embed.description = f"ลิงก์: `{invite.url}` ในช่อง {invite.channel.mention} ถูกลบหรือหมดอายุ"
        await self.send_log(embed, invite.guild)

    @commands.Cog.listener()
    async def on_guild_emojis_update(self, guild, before, after):
        embed = discord.Embed(title="🎨 อัปเดตอีโมจิ", color=discord.Color.purple(), timestamp=datetime.now())
        
        if len(before) < len(after):
            new_emoji = next(e for e in after if e not in before)
            embed.description = f"เพิ่มอีโมจิใหม่: {new_emoji} (`{new_emoji.name}`)\nID: `{new_emoji.id}`"
            embed.color = discord.Color.green()
        elif len(before) > len(after):
            deleted_emoji = next(e for e in before if e not in after)
            embed.description = f"ลบอีโมจิ: **{deleted_emoji.name}**\nID: `{deleted_emoji.id}`"
            embed.color = discord.Color.red()
        else:
            embed.description = "มีการแก้ไขชื่ออีโมจิ"
            
        await self.send_log(embed, guild)

    @commands.Cog.listener()
    async def on_guild_stickers_update(self, guild, before, after):
        embed = discord.Embed(title="🖼️ อัปเดตสติกเกอร์", color=discord.Color.purple(), timestamp=datetime.now())
        if len(before) < len(after):
            new_s = next(s for s in after if s not in before)
            embed.description = f"เพิ่มสติกเกอร์ใหม่: **{new_s.name}**\nID: `{new_s.id}`"
            embed.set_image(url=new_s.url)
        elif len(before) > len(after):
            del_s = next(s for s in before if s not in after)
            embed.description = f"ลบสติกเกอร์: **{del_s.name}**\nID: `{del_s.id}`"
        await self.send_log(embed, guild)

    @commands.Cog.listener()
    async def on_webhooks_update(self, channel):
        embed = discord.Embed(title="🔗 อัปเดตเว็บฮุค (Webhooks)", color=discord.Color.blue(), timestamp=datetime.now())
        embed.description = f"มีการแก้ไข Webhooks ในช่อง {channel.mention}"
        await self.send_log(embed, channel.guild)

    @commands.Cog.listener()
    async def on_thread_update(self, before, after):
        if before.name == after.name and before.archived == after.archived:
            return
        embed = discord.Embed(title="🧵 อัปเดตเธรด", color=discord.Color.blue(), timestamp=datetime.now())
        embed.description = f"เธรด: {after.mention} ({after.name})"
        if before.name != after.name:
            embed.add_field(name="เปลี่ยนชื่อ", value=f"จาก `{before.name}` เป็น `{after.name}`")
        if before.archived != after.archived:
            embed.add_field(name="สถานะ", value="จัดเก็บ (Archived)" if after.archived else "เปิดใช้งานใหม่ (Unarchived)")
        await self.send_log(embed, after.guild)

    @commands.Cog.listener()
    async def on_stage_instance_create(self, stage_instance):
        embed = discord.Embed(title="🎭 เริ่มกิจกรรมเวที (Stage)", color=discord.Color.green(), timestamp=datetime.now())
        embed.description = f"หัวข้อ: **{stage_instance.topic}**\nช่อง: {stage_instance.channel.mention}"
        await self.send_log(embed, stage_instance.guild)

    @commands.Cog.listener()
    async def on_stage_instance_delete(self, stage_instance):
        embed = discord.Embed(title="🎭 สิ้นสุดกิจกรรมเวที", color=discord.Color.red(), timestamp=datetime.now())
        embed.description = f"หัวข้อ: **{stage_instance.topic}**"
        await self.send_log(embed, stage_instance.guild)

    @commands.Cog.listener()
    async def on_stage_instance_update(self, before, after):
        if before.topic == after.topic: return
        embed = discord.Embed(title="🎭 อัปเดตกิจกรรมเวที", color=discord.Color.blue(), timestamp=datetime.now())
        embed.add_field(name="หัวข้อเดิม", value=before.topic)
        embed.add_field(name="หัวข้อใหม่", value=after.topic)
        await self.send_log(embed, after.guild)

    @commands.Cog.listener()
    async def on_guild_integrations_update(self, guild):
        embed = discord.Embed(title="🔌 อัปเดตการเชื่อมต่อ (Integrations)", color=discord.Color.blue(), timestamp=datetime.now())
        embed.description = "มีการเปลี่ยนแปลงการเชื่อมต่อของเซิร์ฟเวอร์ (Integratons/Applications)"
        await self.send_log(embed, guild)

    @commands.Cog.listener()
    async def on_automod_rule_create(self, rule):
        embed = discord.Embed(title="🛡️ สร้างกฎ AutoMod ใหม่", color=discord.Color.green(), timestamp=datetime.now())
        embed.description = f"ชื่อกฎ: **{rule.name}**\nID: `{rule.id}`"
        await self.send_log(embed, rule.guild)

    @commands.Cog.listener()
    async def on_automod_rule_delete(self, rule):
        embed = discord.Embed(title="🗑️ ลบกฎ AutoMod", color=discord.Color.red(), timestamp=datetime.now())
        embed.description = f"ชื่อกฎ: **{rule.name}**\nID: `{rule.id}`"
        await self.send_log(embed, rule.guild)

    @commands.Cog.listener()
    async def on_automod_action_execution(self, execution):
        embed = discord.Embed(title="🛡️ AutoMod ทำงาน", color=discord.Color.dark_orange(), timestamp=datetime.now())
        embed.description = f"ผู้ใช้: {execution.member.mention}\nการกระทำ: **{execution.action.type}**\nเหตุผล: `{execution.rule_name or 'ไม่ระบุ'}`"
        if execution.content:
            embed.add_field(name="เนื้อหาที่โดนจับ", value=execution.content[:1024], inline=False)
        embed.set_footer(text=f"User ID: {execution.user_id}")
        await self.send_log(embed, execution.guild)

async def setup(bot):
    await bot.add_cog(ServerLogger(bot))
