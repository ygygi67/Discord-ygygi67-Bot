import asyncio
from collections import deque
import logging
import os
import shutil
import tempfile
from typing import Final

import discord
from discord import app_commands
from discord.ext import commands

logger = logging.getLogger("discord_bot")


class FileConverter(commands.Cog):
    IMAGE_FORMATS: Final[set[str]] = {"png", "jpg", "jpeg", "webp", "gif", "bmp", "ico"}
    AUDIO_FORMATS: Final[set[str]] = {"mp3", "wav", "ogg", "m4a", "flac", "aac"}
    VIDEO_FORMATS: Final[set[str]] = {"mp4", "mkv", "webm", "mov", "avi", "gif"}
    TEXT_FORMATS: Final[set[str]] = {"txt", "md", "csv", "json", "xml", "html"}

    def __init__(self, bot: commands.Bot):
        self.bot = bot

    def _find_ffmpeg(self) -> str | None:
        ffmpeg_path = shutil.which("ffmpeg")
        if ffmpeg_path:
            return ffmpeg_path

        common_paths = [
            os.path.join(os.getcwd(), "ffmpeg", "bin", "ffmpeg.exe"),
            "C:/ffmpeg/bin/ffmpeg.exe",
            "C:/Program Files/ffmpeg/bin/ffmpeg.exe",
            "/usr/bin/ffmpeg",
            "/usr/local/bin/ffmpeg",
        ]
        for path in common_paths:
            if os.path.exists(path):
                return path
        return None

    def _is_media_format(self, ext: str) -> bool:
        return ext in (self.IMAGE_FORMATS | self.AUDIO_FORMATS | self.VIDEO_FORMATS)

    def _build_conversion_graph(self) -> dict[str, set[str]]:
        graph: dict[str, set[str]] = {}
        all_formats = self.IMAGE_FORMATS | self.AUDIO_FORMATS | self.VIDEO_FORMATS | self.TEXT_FORMATS
        for fmt in all_formats:
            graph[fmt] = set()

        for src in self.TEXT_FORMATS:
            graph[src].update(self.TEXT_FORMATS - {src})
        for src in (self.IMAGE_FORMATS | self.AUDIO_FORMATS | self.VIDEO_FORMATS):
            graph[src].update((self.IMAGE_FORMATS | self.AUDIO_FORMATS | self.VIDEO_FORMATS) - {src})

        return graph

    def _find_conversion_path(self, source: str, target: str) -> list[str]:
        graph = self._build_conversion_graph()
        if source not in graph or target not in graph:
            return []
        if source == target:
            return [source]

        queue = deque([source])
        parent: dict[str, str | None] = {source: None}

        while queue:
            node = queue.popleft()
            if node == target:
                break
            for nxt in graph.get(node, set()):
                if nxt not in parent:
                    parent[nxt] = node
                    queue.append(nxt)

        if target not in parent:
            return []

        path = []
        cur: str | None = target
        while cur is not None:
            path.append(cur)
            cur = parent.get(cur)
        path.reverse()
        return path

    def _build_ffmpeg_cmd(self, ffmpeg: str, input_path: str, output_path: str, source: str, target: str) -> list[str]:
        cmd = [ffmpeg, "-y"]

        if source in self.AUDIO_FORMATS and target in self.VIDEO_FORMATS:
            cmd += ["-f", "lavfi", "-i", "color=c=black:s=1280x720:r=30", "-i", input_path, "-shortest", "-c:v", "libx264", "-pix_fmt", "yuv420p"]
        elif source in self.IMAGE_FORMATS and target in self.VIDEO_FORMATS:
            cmd += ["-loop", "1", "-i", input_path, "-t", "8", "-r", "30", "-c:v", "libx264", "-pix_fmt", "yuv420p"]
        else:
            cmd += ["-i", input_path]

        if target == "mp3":
            cmd += ["-vn", "-ar", "44100", "-ac", "2", "-b:a", "192k"]
        elif target == "wav":
            cmd += ["-vn", "-ac", "2", "-ar", "44100"]
        elif target in {"m4a", "aac"}:
            cmd += ["-vn", "-b:a", "192k"]
        elif target == "gif":
            cmd += ["-vf", "fps=15,scale='min(960,iw)':-1:flags=lanczos"]
        elif target in {"jpg", "jpeg"}:
            cmd += ["-q:v", "2"]
        elif target == "webp":
            cmd += ["-quality", "85"]
        elif target == "ico":
            cmd += ["-vf", "scale=256:256:force_original_aspect_ratio=decrease"]

        cmd.append(output_path)
        return cmd

    async def _convert_with_ffmpeg(self, ffmpeg: str, input_path: str, output_path: str, source: str, target: str) -> tuple[bool, str]:
        cmd = self._build_ffmpeg_cmd(ffmpeg, input_path, output_path, source, target)
        process = await asyncio.create_subprocess_exec(
            *cmd,
            stdout=asyncio.subprocess.DEVNULL,
            stderr=asyncio.subprocess.PIPE,
        )
        _, stderr = await process.communicate()
        if process.returncode != 0:
            error_text = (stderr.decode("utf-8", errors="ignore") or "unknown error")[:400]
            return False, error_text
        return True, "ok"

    async def _convert_text_to_text(self, input_path: str, output_path: str) -> tuple[bool, str]:
        try:
            with open(input_path, "rb") as src:
                raw = src.read()
            text = raw.decode("utf-8", errors="ignore")
            with open(output_path, "w", encoding="utf-8", newline="") as dst:
                dst.write(text)
            return True, "ok"
        except Exception as e:
            return False, str(e)

    async def _convert_step(self, ffmpeg: str | None, input_path: str, output_path: str, source: str, target: str) -> tuple[bool, str]:
        if source in self.TEXT_FORMATS and target in self.TEXT_FORMATS:
            return await self._convert_text_to_text(input_path, output_path)
        if self._is_media_format(source) and self._is_media_format(target):
            if not ffmpeg:
                return False, "ไม่พบ ffmpeg ในเครื่องบอท"
            return await self._convert_with_ffmpeg(ffmpeg, input_path, output_path, source, target)
        return False, f"ไม่รองรับการแปลง `{source}` -> `{target}`"

    @app_commands.command(name="แปลงไฟล์", description="แปลงไฟล์เป็นรูปแบบอื่นแบบครบเครื่อง")
    @app_commands.describe(file="ไฟล์ที่ต้องการแปลง", target_format="นามสกุลปลายทางที่ต้องการ")
    @app_commands.choices(
        target_format=[
            app_commands.Choice(name="PNG", value="png"),
            app_commands.Choice(name="JPG", value="jpg"),
            app_commands.Choice(name="WEBP", value="webp"),
            app_commands.Choice(name="GIF", value="gif"),
            app_commands.Choice(name="BMP", value="bmp"),
            app_commands.Choice(name="ICO", value="ico"),
            app_commands.Choice(name="MP3", value="mp3"),
            app_commands.Choice(name="WAV", value="wav"),
            app_commands.Choice(name="OGG", value="ogg"),
            app_commands.Choice(name="M4A", value="m4a"),
            app_commands.Choice(name="FLAC", value="flac"),
            app_commands.Choice(name="AAC", value="aac"),
            app_commands.Choice(name="MP4", value="mp4"),
            app_commands.Choice(name="MKV", value="mkv"),
            app_commands.Choice(name="WEBM", value="webm"),
            app_commands.Choice(name="MOV", value="mov"),
            app_commands.Choice(name="AVI", value="avi"),
            app_commands.Choice(name="TXT", value="txt"),
            app_commands.Choice(name="MD", value="md"),
            app_commands.Choice(name="CSV", value="csv"),
            app_commands.Choice(name="JSON", value="json"),
            app_commands.Choice(name="XML", value="xml"),
            app_commands.Choice(name="HTML", value="html"),
        ]
    )
    async def convert_file(self, interaction: discord.Interaction, file: discord.Attachment, target_format: str):
        await interaction.response.defer(ephemeral=False)
        target = target_format.lower().strip(".")

        filename = file.filename or "input.bin"
        source_ext = filename.rsplit(".", 1)[-1].lower() if "." in filename else ""
        if not source_ext:
            return await interaction.edit_original_response(content="❌ ไฟล์ต้นทางไม่มีนามสกุล จึงระบุวิธีแปลงไม่ได้")
        if source_ext == target:
            return await interaction.edit_original_response(content="⚠️ นามสกุลต้นทางและปลายทางเหมือนกันอยู่แล้ว")

        await interaction.edit_original_response(content=f"⏳ กำลังรับไฟล์ `{filename}` ...")

        temp_dir = tempfile.mkdtemp(prefix="universal_convert_")
        input_path = os.path.join(temp_dir, f"input.{source_ext}")
        output_path = os.path.join(temp_dir, f"output.{target}")

        try:
            await file.save(input_path)
            input_size = os.path.getsize(input_path)
            if input_size == 0:
                return await interaction.edit_original_response(content="❌ ไฟล์ที่อัปโหลดว่างเปล่า")

            path = self._find_conversion_path(source_ext, target)
            if not path:
                return await interaction.edit_original_response(
                    content=(
                        "❌ ยังไม่รองรับเส้นทางแปลงไฟล์นี้\n"
                        f"ไฟล์ต้นทาง: `{source_ext}` | เป้าหมาย: `{target}`\n"
                        "รองรับตอนนี้: ระบบหาทางแปลงอัตโนมัติสำหรับข้อความและสื่อ (รูป/เสียง/วิดีโอ)"
                    )
                )

            ffmpeg = self._find_ffmpeg() if any(self._is_media_format(step) for step in path) else None
            current_input = input_path
            total_steps = len(path) - 1

            for idx in range(total_steps):
                src_fmt = path[idx]
                dst_fmt = path[idx + 1]
                is_last = idx == total_steps - 1
                step_output = output_path if is_last else os.path.join(temp_dir, f"step_{idx+1}.{dst_fmt}")

                await interaction.edit_original_response(
                    content=f"🔄 กำลังแปลง ({idx+1}/{total_steps}) `{src_fmt.upper()}` ➜ `{dst_fmt.upper()}` ..."
                )
                ok, detail = await self._convert_step(ffmpeg, current_input, step_output, src_fmt, dst_fmt)
                if not ok:
                    return await interaction.edit_original_response(content=f"❌ แปลงไฟล์ไม่สำเร็จ: `{detail}`")
                current_input = step_output

            if not os.path.exists(output_path) or os.path.getsize(output_path) == 0:
                return await interaction.edit_original_response(content="❌ แปลงไม่สำเร็จ (ไฟล์ปลายทางว่างหรือไม่ถูกสร้าง)")

            output_size = os.path.getsize(output_path)
            await interaction.edit_original_response(
                content=(
                    f"✅ แปลงเสร็จแล้ว `{source_ext.upper()}` ➜ `{target.upper()}`\n"
                    f"📦 ขนาดไฟล์: `{output_size / (1024 * 1024):.2f} MB`"
                )
            )
            await interaction.followup.send(file=discord.File(output_path, filename=f"{os.path.splitext(filename)[0]}.{target}"))
        except Exception as e:
            logger.error(f"convert_file error: {e}", exc_info=True)
            await interaction.edit_original_response(content=f"❌ เกิดข้อผิดพลาดระหว่างแปลงไฟล์: `{str(e)[:300]}`")
        finally:
            shutil.rmtree(temp_dir, ignore_errors=True)

    @app_commands.command(name="แปลงไฟล์_รองรับ", description="ดูหมวดรูปแบบไฟล์ที่ระบบแปลงรองรับ")
    async def convert_supported_formats(self, interaction: discord.Interaction):
        embed = discord.Embed(title="🛠️ Universal File Converter", color=discord.Color.blurple())
        embed.description = "รองรับการหาเส้นทางแปลงอัตโนมัติ (inspired by conversion-graph)"
        embed.add_field(name="🖼️ รูปภาพ", value="`png, jpg, jpeg, webp, gif, bmp, ico`", inline=False)
        embed.add_field(name="🎵 เสียง", value="`mp3, wav, ogg, m4a, flac, aac`", inline=False)
        embed.add_field(name="🎬 วิดีโอ", value="`mp4, mkv, webm, mov, avi, gif`", inline=False)
        embed.add_field(name="📄 ข้อความ", value="`txt, md, csv, json, xml, html`", inline=False)
        embed.set_footer(text="ใช้คำสั่ง /แปลงไฟล์ แล้วแนบไฟล์เพื่อเริ่มใช้งาน")
        await interaction.response.send_message(embed=embed, ephemeral=False)


async def setup(bot: commands.Bot):
    await bot.add_cog(FileConverter(bot))
