import discord
from discord.ext import commands
from discord import app_commands
import logging
import asyncio
from typing import Optional

logger = logging.getLogger('discord_bot')

class RoleSyncAndManage(commands.Cog):
    def __init__(self, bot):
        self.bot = bot
        logger.info("RoleSyncAndManage cog initialized")

    @app_commands.command(name="sync_roles", description="ซิงค์ยศจากเซิร์ฟเวอร์อื่นโดยดูจากชื่อยศที่เหมือนกัน")
    @app_commands.describe(source_guild_id="ID ของเซิร์ฟเวอร์ต้นทางที่ต้องการซิงค์ยศมา")
    @app_commands.default_permissions(administrator=True)
    async def sync_roles(self, interaction: discord.Interaction, source_guild_id: str):
        """ซิงค์ยศจากเซิร์ฟเวอร์อื่นโดยดูจากชื่อยศที่เหมือนกัน"""
        await interaction.response.defer()
        
        try:
            source_guild = self.bot.get_guild(int(source_guild_id))
            if not source_guild:
                await interaction.followup.send("❌ ไม่พบเซิร์ฟเวอร์ต้นทาง (บอทต้องอยู่ในเซิร์ฟเวอร์นั้นด้วย)")
                return

            current_guild = interaction.guild
            sync_count = 0
            member_count = 0

            # สร้าง dictionary ของยศในเซิร์ฟเวอร์ปัจจุบัน {ชื่อยศ: วัตถุยศ}
            current_roles_by_name = {role.name: role for role in current_guild.roles if not role.is_default() and not role.managed}

            for member in current_guild.members:
                if member.bot:
                    continue

                source_member = source_guild.get_member(member.id)
                if not source_member:
                    continue

                roles_to_add = []
                for source_role in source_member.roles:
                    if source_role.is_default() or source_role.managed:
                        continue
                    
                    # ถ้าชื่อชื่อยศตรงกันในเซิร์ฟเวอร์ปัจจุบัน
                    if source_role.name in current_roles_by_name:
                        target_role = current_roles_by_name[source_role.name]
                        if target_role not in member.roles and target_role < current_guild.me.top_role:
                            roles_to_add.append(target_role)

                if roles_to_add:
                    try:
                        await member.add_roles(*roles_to_add, reason=f"Role sync from guild {source_guild.name}")
                        sync_count += len(roles_to_add)
                        member_count += 1
                        # ป้องกัน rate limit ทุกๆ 5 คน
                        if member_count % 5 == 0:
                            await asyncio.sleep(1)
                    except Exception as e:
                        logger.error(f"Error syncing roles for {member.name}: {e}")

            await interaction.followup.send(
                f"✅ ซิงค์ยศเสร็จสิ้น!\n"
                f"- สมาชิกที่ได้รับการซิงค์: `{member_count}` คน\n"
                f"- จำนวนยศที่มอบให้ทั้งหมด: `{sync_count}` ครั้ง"
            )

        except ValueError:
            await interaction.followup.send("❌ ID เซิร์ฟเวอร์ไม่ถูกต้อง")
        except Exception as e:
            logger.error(f"Error in sync_roles: {e}")
            await interaction.followup.send(f"❌ เกิดข้อผิดพลาด: {str(e)}")

    @app_commands.command(name="จัดการสิทธิ์ยศ", description="ตั้งค่าสิทธิ์ของยศในหมวดหมู่หรือทั้งเซิร์ฟเวอร์")
    @app_commands.describe(
        role_id="ID ของยศที่ต้องการจัดการ",
        category_id="ID ของหมวดหมู่ (ถ้าไม่ใส่จะแก้ทุกช่องในเซิร์ฟเวอร์)",
        action="สิ่งที่ต้องการให้ยศนี้ทำได้",
    )
    @app_commands.choices(action=[
        app_commands.Choice(name="🔓 อ่านและส่ง (Read & Send)", value="read_send"),
        app_commands.Choice(name="📜 อ่านอย่างเดียว (Read Only)", value="read_only"),
        app_commands.Choice(name="🚫 ปิดการมองเห็น (Hide)", value="hide"),
        app_commands.Choice(name="🔄 รีเซ็ตสิทธิ์ (Reset/Clear)", value="reset")
    ])
    @app_commands.default_permissions(administrator=True)
    async def manage_permissions(
        self, 
        interaction: discord.Interaction, 
        role_id: str, 
        category_id: Optional[str] = None,
        action: str = "read_send"
    ):
        """ตั้งค่าสิทธิ์ของยศในหมวดหมู่หรือทั้งเซิร์ฟเวอร์"""
        await interaction.response.defer()

        try:
            guild = interaction.guild
            role = guild.get_role(int(role_id))
            
            if not role:
                await interaction.followup.send("❌ ไม่พบยศที่ระบุ โปรดตรวจสอบ ID อีกครั้ง")
                return

            # Check if bot can manage this role (informational)
            if role >= guild.me.top_role and not interaction.user.id == guild.owner_id:
                logger.warning(f"Managing role {role.name} which is higher than or equal to bot's top role.")

            channels_to_update = []
            category = None
            
            if category_id:
                try:
                    category = guild.get_channel(int(category_id))
                    if not isinstance(category, discord.CategoryChannel):
                        await interaction.followup.send("❌ ID ที่ระบุไม่ใช่หมวดหมู่ (Category)")
                        return
                    channels_to_update = list(category.channels)
                    channels_to_update.append(category)
                except:
                    await interaction.followup.send("❌ ไม่พบหมวดหมู่ที่ระบุ")
                    return
            else:
                channels_to_update = list(guild.channels)

            if not channels_to_update:
                await interaction.followup.send("❌ ไม่พบช่องทางที่ต้องอัปเดต")
                return

            # Prepare permissions overwrite
            overwrites = None
            if action == "read_send":
                overwrites = discord.PermissionOverwrite(
                    view_channel=True,
                    send_messages=True,
                    read_message_history=True,
                    connect=True,
                    speak=True,
                    use_format_messages=True,
                    add_reactions=True
                )
            elif action == "read_only":
                overwrites = discord.PermissionOverwrite(
                    view_channel=True,
                    send_messages=False,
                    read_message_history=True,
                    connect=True,
                    speak=False
                )
            elif action == "hide":
                overwrites = discord.PermissionOverwrite(
                    view_channel=False,
                    connect=False
                )
            elif action == "reset":
                overwrites = None

            updated_count = 0
            failed_count = 0
            
            status_embed = discord.Embed(
                title="⚙️ กำลังดำเนินการ...",
                description=f"กำลังอัปเดตสิทธิ์สำหรับ {role.mention}\nจำนวนทั้งหมด: {len(channels_to_update)} ช่อง",
                color=discord.Color.yellow()
            )
            status_msg = await interaction.followup.send(embed=status_embed)

            for channel in channels_to_update:
                try:
                    await channel.set_permissions(role, overwrite=overwrites, reason=f"Bulk permission update by {interaction.user.name}")
                    updated_count += 1
                except discord.Forbidden:
                    failed_count += 1
                except Exception as e:
                    failed_count += 1
                    logger.error(f"Error updating {channel.name}: {e}")
                
                # Progress update every 10 channels
                if (updated_count + failed_count) % 10 == 0:
                    try:
                        status_embed.description = f"🔄 ดำเนินการแล้ว: {updated_count + failed_count}/{len(channels_to_update)} ช่อง"
                        await status_msg.edit(embed=status_embed)
                    except: pass
                    await asyncio.sleep(0.5)

            # Final result
            action_map = {
                "read_send": "🔓 อ่านและส่ง",
                "read_only": "📜 อ่านอย่างเดียว",
                "hide": "🚫 ปิดการมองเห็น",
                "reset": "🔄 รีเซ็ตสิทธิ์"
            }
            
            result_embed = discord.Embed(
                title="✅ ดำเนินการเสร็จสิ้น",
                color=discord.Color.green(),
                timestamp=discord.utils.utcnow()
            )
            result_embed.add_field(name="🛡️ ยศ", value=role.mention, inline=True)
            result_embed.add_field(name="🎯 การกระทำ", value=action_map.get(action), inline=True)
            result_embed.add_field(name="📍 พื้นที่", value=f"หมวดหมู่: **{category.name}**" if category else "**ทั้งเซิร์ฟเวอร์**", inline=False)
            result_embed.add_field(name="📊 สรุปผล", value=f"✅ สำเร็จ: `{updated_count}` ช่อง\n❌ ล้มเหลว: `{failed_count}` ช่อง", inline=False)
            result_embed.set_footer(text=f"จัดการโดย {interaction.user.name}")

            await status_msg.edit(embed=result_embed)

        except ValueError:
            await interaction.followup.send("❌ ID ไม่ถูกต้อง (ต้องเป็นตัวเลข)")
        except Exception as e:
            logger.error(f"Error in manage_permissions: {e}")
            await interaction.followup.send(f"❌ เกิดข้อผิดพลาดร้ายแรง: {str(e)}")

async def setup(bot):
    await bot.add_cog(RoleSyncAndManage(bot))
