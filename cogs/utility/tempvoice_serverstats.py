import json
import logging
import os
import re
from typing import Optional

import discord
from discord import app_commands
from discord.ext import commands, tasks

logger = logging.getLogger("discord_bot")

CONFIG_PATH = "data/tempvoice_serverstats_config.json"


def _default_config():
    return {
        "tempvoice": {},
        "serverstats": {},
    }


def _load_config():
    os.makedirs("data", exist_ok=True)
    if not os.path.exists(CONFIG_PATH):
        return _default_config()
    try:
        with open(CONFIG_PATH, "r", encoding="utf-8") as f:
            data = json.load(f)
            if "tempvoice" not in data:
                data["tempvoice"] = {}
            if "serverstats" not in data:
                data["serverstats"] = {}
            return data
    except Exception:
        return _default_config()


def _save_config(config):
    os.makedirs("data", exist_ok=True)
    with open(CONFIG_PATH, "w", encoding="utf-8") as f:
        json.dump(config, f, ensure_ascii=False, indent=2)


def _format_counter_name(template: str, count: int) -> str:
    if "{count}" in template:
        return template.replace("{count}", str(count))
    return f"{template} {count}"


def _format_room_name(template: str, member: discord.Member, room_no: int) -> str:
    name = template
    name = name.replace("{user}", member.name)
    name = name.replace("{display}", member.display_name)
    name = name.replace("{num}", str(room_no))
    return name[:100]


class TempVoiceServerStats(commands.Cog):
    def __init__(self, bot: commands.Bot):
        self.bot = bot
        self.config = _load_config()
        self.temp_rooms: dict[int, dict[int, int]] = {}
        self.stats_updater.start()

    def cog_unload(self):
        self.stats_updater.cancel()

    def _is_admin(self, interaction: discord.Interaction) -> bool:
        return bool(interaction.guild and interaction.user.guild_permissions.administrator)

    def _get_tv_cfg(self, guild_id: int) -> dict:
        return self.config["tempvoice"].get(str(guild_id), {})

    def _get_ss_cfg(self, guild_id: int) -> dict:
        return self.config["serverstats"].get(str(guild_id), {})

    async def _ensure_serverstats_update(self, guild: discord.Guild):
        cfg = self._get_ss_cfg(guild.id)
        if not cfg:
            return

        humans = sum(1 for m in guild.members if not m.bot)
        bots = sum(1 for m in guild.members if m.bot)

        humans_channel_id = cfg.get("humans_channel_id")
        bots_channel_id = cfg.get("bots_channel_id")
        humans_template = cfg.get("humans_template", "👥 ผู้ใช้: {count}")
        bots_template = cfg.get("bots_template", "🤖 บอท: {count}")

        if humans_channel_id:
            channel = guild.get_channel(humans_channel_id)
            if isinstance(channel, discord.VoiceChannel):
                desired = _format_counter_name(humans_template, humans)
                if channel.name != desired:
                    try:
                        await channel.edit(name=desired)
                    except Exception as e:
                        logger.warning(f"Failed to update humans stats channel: {e}")

        if bots_channel_id:
            channel = guild.get_channel(bots_channel_id)
            if isinstance(channel, discord.VoiceChannel):
                desired = _format_counter_name(bots_template, bots)
                if channel.name != desired:
                    try:
                        await channel.edit(name=desired)
                    except Exception as e:
                        logger.warning(f"Failed to update bots stats channel: {e}")

    @tasks.loop(minutes=2)
    async def stats_updater(self):
        await self.bot.wait_until_ready()
        for guild in self.bot.guilds:
            await self._ensure_serverstats_update(guild)

    @commands.Cog.listener()
    async def on_member_join(self, member: discord.Member):
        await self._ensure_serverstats_update(member.guild)

    @commands.Cog.listener()
    async def on_member_remove(self, member: discord.Member):
        await self._ensure_serverstats_update(member.guild)

    @commands.Cog.listener()
    async def on_voice_state_update(self, member: discord.Member, before: discord.VoiceState, after: discord.VoiceState):
        guild = member.guild
        cfg = self._get_tv_cfg(guild.id)
        if not cfg:
            return

        lobby_id = cfg.get("lobby_channel_id")
        category_id = cfg.get("category_id")
        template = cfg.get("room_template", "🔊 {display} #{num}")

        if after.channel and after.channel.id == lobby_id:
            category = guild.get_channel(category_id)
            if not isinstance(category, discord.CategoryChannel):
                return

            room_no = int(cfg.get("room_counter", 0)) + 1
            cfg["room_counter"] = room_no
            self.config["tempvoice"][str(guild.id)] = cfg
            _save_config(self.config)

            room_name = _format_room_name(template, member, room_no)
            try:
                vc = await guild.create_voice_channel(name=room_name, category=category)
                await member.move_to(vc)
                self.temp_rooms.setdefault(guild.id, {})[vc.id] = member.id
            except Exception as e:
                logger.error(f"TempVoice create/move failed: {e}")

        if before.channel:
            owned = self.temp_rooms.get(guild.id, {})
            if before.channel.id in owned and len(before.channel.members) == 0:
                try:
                    await before.channel.delete(reason="TempVoice empty")
                except Exception:
                    pass
                owned.pop(before.channel.id, None)

    @app_commands.command(name="ตั้งค่า_serverstats", description="ตั้งค่าช่องนับจำนวนผู้ใช้และบอทอัตโนมัติ")
    @app_commands.describe(
        โหมด="โหมดการตั้งค่า",
        ช่องผู้ใช้="เลือกช่องผู้ใช้ (ใช้เมื่อโหมด=ใช้ช่องที่มีอยู่)",
        ช่องบอท="เลือกช่องบอท (ใช้เมื่อโหมด=ใช้ช่องที่มีอยู่)"
    )
    @app_commands.choices(
        โหมด=[
            app_commands.Choice(name="ให้บอทสร้างช่องให้", value="auto_create"),
            app_commands.Choice(name="ใช้ช่องที่มีอยู่", value="use_existing"),
        ]
    )
    async def setup_serverstats(
        self,
        interaction: discord.Interaction,
        โหมด: str,
        ช่องผู้ใช้: Optional[discord.VoiceChannel] = None,
        ช่องบอท: Optional[discord.VoiceChannel] = None,
    ):
        if not self._is_admin(interaction):
            return await interaction.response.send_message("❌ ต้องมีสิทธิ์ Administrator", ephemeral=True)
        if not interaction.guild:
            return await interaction.response.send_message("❌ ใช้ได้เฉพาะในเซิร์ฟเวอร์", ephemeral=True)

        guild = interaction.guild
        humans = sum(1 for m in guild.members if not m.bot)
        bots = sum(1 for m in guild.members if m.bot)

        humans_template = "👥 ผู้ใช้: {count}"
        bots_template = "🤖 บอท: {count}"

        if โหมด == "auto_create":
            category = discord.utils.get(guild.categories, name="📊 Server Stats")
            if not category:
                category = await guild.create_category("📊 Server Stats")

            humans_ch = await guild.create_voice_channel(
                name=_format_counter_name(humans_template, humans),
                category=category
            )
            bots_ch = await guild.create_voice_channel(
                name=_format_counter_name(bots_template, bots),
                category=category
            )
        else:
            if not ช่องผู้ใช้ or not ช่องบอท:
                return await interaction.response.send_message("❌ โหมดนี้ต้องระบุ `ช่องผู้ใช้` และ `ช่องบอท`", ephemeral=True)
            humans_ch = ช่องผู้ใช้
            bots_ch = ช่องบอท

        self.config["serverstats"][str(guild.id)] = {
            "humans_channel_id": humans_ch.id,
            "bots_channel_id": bots_ch.id,
            "humans_template": humans_template,
            "bots_template": bots_template,
        }
        _save_config(self.config)
        await self._ensure_serverstats_update(guild)
        await interaction.response.send_message("✅ ตั้งค่า ServerStats สำเร็จแล้ว", ephemeral=True)

    @app_commands.command(name="ตั้งชื่อ_serverstats", description="แก้ข้อความหน้าตัวเลขของช่องนับผู้ใช้/บอท")
    @app_commands.describe(
        ชนิด="เลือกว่าจะแก้ช่องผู้ใช้หรือช่องบอท",
        ข้อความหน้าเลข="เช่น 👥 ผู้ใช้: หรือ 🤖 บอท: (ใส่ {count} ได้)"
    )
    @app_commands.choices(
        ชนิด=[
            app_commands.Choice(name="ผู้ใช้", value="humans"),
            app_commands.Choice(name="บอท", value="bots"),
        ]
    )
    async def set_serverstats_prefix(self, interaction: discord.Interaction, ชนิด: str, ข้อความหน้าเลข: str):
        if not self._is_admin(interaction):
            return await interaction.response.send_message("❌ ต้องมีสิทธิ์ Administrator", ephemeral=True)
        if not interaction.guild:
            return await interaction.response.send_message("❌ ใช้ได้เฉพาะในเซิร์ฟเวอร์", ephemeral=True)

        cfg = self._get_ss_cfg(interaction.guild.id)
        if not cfg:
            return await interaction.response.send_message("❌ ยังไม่ได้ตั้งค่า ServerStats", ephemeral=True)

        template = ข้อความหน้าเลข.strip()
        if "{count}" not in template:
            template = f"{template} {{count}}"

        if ชนิด == "humans":
            cfg["humans_template"] = template
        else:
            cfg["bots_template"] = template
        self.config["serverstats"][str(interaction.guild.id)] = cfg
        _save_config(self.config)
        await self._ensure_serverstats_update(interaction.guild)
        await interaction.response.send_message("✅ อัปเดตชื่อ ServerStats แล้ว", ephemeral=True)

    @app_commands.command(name="ตั้งค่า_tempvoice", description="ตั้งค่าระบบ TempVoice")
    @app_commands.describe(
        โหมด="โหมดการตั้งค่า",
        หมวดหมู่="หมวดที่ต้องการใช้/สร้างห้องชั่วคราวในนี้",
        ห้องล๊อบบี้="ห้องที่คนเข้าแล้วให้บอทสร้างห้องใหม่ให้",
        รูปแบบชื่อห้อง="เช่น 🔊 {display} #{num} หรือ 🏠 ห้องของ {user}"
    )
    @app_commands.choices(
        โหมด=[
            app_commands.Choice(name="ให้บอทสร้างหมวดและล๊อบบี้", value="auto_create"),
            app_commands.Choice(name="ใช้ช่องที่มีอยู่", value="use_existing"),
        ]
    )
    async def setup_tempvoice(
        self,
        interaction: discord.Interaction,
        โหมด: str,
        หมวดหมู่: Optional[discord.CategoryChannel] = None,
        ห้องล๊อบบี้: Optional[discord.VoiceChannel] = None,
        รูปแบบชื่อห้อง: str = "🔊 {display} #{num}",
    ):
        if not self._is_admin(interaction):
            return await interaction.response.send_message("❌ ต้องมีสิทธิ์ Administrator", ephemeral=True)
        if not interaction.guild:
            return await interaction.response.send_message("❌ ใช้ได้เฉพาะในเซิร์ฟเวอร์", ephemeral=True)

        guild = interaction.guild
        if โหมด == "auto_create":
            category = await guild.create_category("🎧 TempVoice")
            lobby = await guild.create_voice_channel("➕ สร้างห้องเสียง", category=category)
        else:
            if not หมวดหมู่ or not ห้องล๊อบบี้:
                return await interaction.response.send_message("❌ โหมดนี้ต้องระบุ `หมวดหมู่` และ `ห้องล๊อบบี้`", ephemeral=True)
            category = หมวดหมู่
            lobby = ห้องล๊อบบี้

        self.config["tempvoice"][str(guild.id)] = {
            "category_id": category.id,
            "lobby_channel_id": lobby.id,
            "room_template": รูปแบบชื่อห้อง,
            "room_counter": 0,
        }
        _save_config(self.config)
        await interaction.response.send_message(
            f"✅ ตั้งค่า TempVoice สำเร็จ\nล๊อบบี้: {lobby.mention}\nหมวด: `{category.name}`",
            ephemeral=True
        )

    @app_commands.command(name="ตั้งชื่อ_tempvoice", description="แก้รูปแบบชื่อห้อง TempVoice ที่บอทสร้าง")
    @app_commands.describe(รูปแบบชื่อห้อง="รองรับ {user} {display} {num}")
    async def set_tempvoice_template(self, interaction: discord.Interaction, รูปแบบชื่อห้อง: str):
        if not self._is_admin(interaction):
            return await interaction.response.send_message("❌ ต้องมีสิทธิ์ Administrator", ephemeral=True)
        if not interaction.guild:
            return await interaction.response.send_message("❌ ใช้ได้เฉพาะในเซิร์ฟเวอร์", ephemeral=True)

        cfg = self._get_tv_cfg(interaction.guild.id)
        if not cfg:
            return await interaction.response.send_message("❌ ยังไม่ได้ตั้งค่า TempVoice", ephemeral=True)

        cfg["room_template"] = รูปแบบชื่อห้อง
        self.config["tempvoice"][str(interaction.guild.id)] = cfg
        _save_config(self.config)
        await interaction.response.send_message("✅ อัปเดตรูปแบบชื่อห้อง TempVoice แล้ว", ephemeral=True)

    @app_commands.command(name="เปลี่ยนชื่อห้อง_tempvoice", description="ผู้สร้างห้องสามารถเปลี่ยนชื่อห้องชั่วคราวของตัวเองได้")
    @app_commands.describe(ชื่อใหม่="ชื่อห้องใหม่")
    async def rename_tempvoice_room(self, interaction: discord.Interaction, ชื่อใหม่: str):
        if not interaction.guild or not isinstance(interaction.user, discord.Member):
            return await interaction.response.send_message("❌ ใช้ได้เฉพาะในเซิร์ฟเวอร์", ephemeral=True)

        vc = interaction.user.voice.channel if interaction.user.voice else None
        if not vc:
            return await interaction.response.send_message("❌ คุณต้องอยู่ในห้องเสียงก่อน", ephemeral=True)

        owner_map = self.temp_rooms.get(interaction.guild.id, {})
        owner_id = owner_map.get(vc.id)
        if owner_id != interaction.user.id and not interaction.user.guild_permissions.administrator:
            return await interaction.response.send_message("❌ คุณไม่ใช่เจ้าของห้องนี้", ephemeral=True)

        try:
            await vc.edit(name=ชื่อใหม่[:100])
            await interaction.response.send_message("✅ เปลี่ยนชื่อห้องแล้ว", ephemeral=True)
        except Exception as e:
            await interaction.response.send_message(f"❌ เปลี่ยนชื่อไม่สำเร็จ: {e}", ephemeral=True)


async def setup(bot):
    guild_id = os.getenv("DISCORD_GUILD_ID")
    if guild_id and guild_id.strip().isdigit():
        await bot.add_cog(TempVoiceServerStats(bot), guild=discord.Object(id=int(guild_id)))
        return

    if os.path.isdir("data"):
        for name in os.listdir("data"):
            m = re.match(r"^(\d{15,21})_", name)
            if m:
                await bot.add_cog(TempVoiceServerStats(bot), guild=discord.Object(id=int(m.group(1))))
                return

    await bot.add_cog(TempVoiceServerStats(bot))
