import discord
from discord import app_commands
from discord.ext import commands
import aiohttp
import io
import base64
import logging
import os
import asyncio

logger = logging.getLogger('discord_bot')

def _guild_scope_decorator():
    force_global = os.getenv("FORCE_GLOBAL_AI_COMMANDS", "0").strip().lower() in {"1", "true", "yes", "on"}
    use_guild_scope = (not force_global) and (
        os.getenv("USE_GUILD_SCOPED_COMMANDS", "1").strip().lower() in {"1", "true", "yes", "on"}
    )
    if use_guild_scope:
        guild_id = os.getenv("DISCORD_GUILD_ID")
        if guild_id and guild_id.strip().isdigit():
            return app_commands.guilds(discord.Object(id=int(guild_id)))
    return lambda x: x

class AIMedia(commands.Cog):
    """🎨 AI Media Generator (Stable Diffusion API Integration)"""

    def __init__(self, bot):
        self.bot = bot
        # URL ของ Stable Diffusion WebUI (Automatic1111 / Forge)
        self.sd_url = os.getenv("SD_API_URL", "http://127.0.0.1:7860")

    async def check_sd_api(self) -> bool:
        """ตรวจสอบว่า Stable Diffusion API เปิดใช้งานและเข้าถึงได้หรือไม่"""
        try:
            async with aiohttp.ClientSession() as session:
                async with session.get(f"{self.sd_url}/sdapi/v1/progress", timeout=2) as resp:
                    return resp.status == 200
        except Exception:
            return False

    @_guild_scope_decorator()
    @app_commands.command(name="สร้างภาพ", description="🎨 สร้างภาพด้วย AI (รันหน้าเครื่องผ่าน Stable Diffusion)")
    @app_commands.describe(
        prompt="สิ่งที่ต้องการให้วาด (พริ้มเป็นภาษาอังกฤษจะได้ผลดีที่สุด)",
        negative_prompt="สิ่งที่ไม่ต้องการให้มีในภาพ",
        steps="ความละเอียดของขั้นตอน (แนะนำ 20-30)",
        width="ความกว้างของภาพ (เช่น 512, 768, 1024)",
        height="ความสูงของภาพ (เช่น 512, 768, 1024)"
    )
    async def create_image(
        self, 
        interaction: discord.Interaction, 
        prompt: str, 
        negative_prompt: str = "nsfw, lowres, bad anatomy, bad hands, text, error, missing fingers, extra digit, fewer digits, cropped, worst quality, low quality, normal quality, jpeg artifacts, signature, watermark, username, blurry",
        steps: int = 20,
        width: int = 512,
        height: int = 512
    ):
        await interaction.response.defer(thinking=True)
        
        # 1. เช็คพอร์ตว่าเปิดไว้ไหม
        is_online = await self.check_sd_api()
        if not is_online:
            import urllib.parse
            progress_msg = await interaction.followup.send("☁️ ไม่พบ Local SD ในเครื่อง... ระบบกำลังสลับไปใช้วาดภาพผ่าน Cloud API แทนให้ฟรีครับ! 🚀")
            safe_prompt = urllib.parse.quote(prompt)
            url = f"https://image.pollinations.ai/prompt/{safe_prompt}?width={width}&height={height}&nologo=true&seed=0"
            
            try:
                async with aiohttp.ClientSession() as session:
                    async with session.get(url, timeout=60) as resp:
                        if resp.status == 200:
                            image_bytes = await resp.read()
                            file = discord.File(fp=io.BytesIO(image_bytes), filename="cloud_ai_image.png")
                            
                            embed = discord.Embed(title="🎨 นี่คือภาพจาก AI ของคุณ!", color=discord.Color.brand_green())
                            embed.add_field(name="🎯 Prompt", value=f"```\n{prompt}\n```", inline=False)
                            embed.set_footer(text=f"⚡ วาดผ่านระบบ Cloud | ขนาด: {width}x{height}")
                            
                            await progress_msg.edit(content=None, embed=embed, attachments=[file])
                        else:
                            await progress_msg.edit(content="❌ Cloud API ล้มเหลว โปรดลองใหม่ภายหลัง")
            except Exception as e:
                await progress_msg.edit(content=f"❌ เกิดข้อผิดพลาดในการโหลด Cloud Image: {e}")
            return

        payload = {
            "prompt": prompt,
            "negative_prompt": negative_prompt,
            "steps": min(max(steps, 10), 100), # จำกัด 10-100
            "width": width,
            "height": height,
            "cfg_scale": 7,
            "sampler_name": "Euler a"
        }

        progress_msg = await interaction.followup.send("⏳ กำลังสั่งการ์ดจอให้วาดภาพ... (อาจใช้เวลาหลายวินาที)")
        
        try:
            async with aiohttp.ClientSession() as session:
                async with session.post(f"{self.sd_url}/sdapi/v1/txt2img", json=payload, timeout=aiohttp.ClientTimeout(total=300)) as resp:
                    if resp.status == 200:
                        r = await resp.json()
                        
                        # ระบบ SD จะคืนภาพกลับมาเป็น Base64 String
                        image_data = r['images'][0]
                        # ลบ Header data:image/png;base64, (ถ้ามี)
                        image_b64 = image_data.split(",", 1)[1] if "," in image_data else image_data
                        image_bytes = base64.b64decode(image_b64)
                        
                        file = discord.File(fp=io.BytesIO(image_bytes), filename="ai_generated.png")
                        
                        embed = discord.Embed(title="🎨 นี่คือภาพที่คุณสั่งให้วาด:", color=discord.Color.brand_green())
                        embed.add_field(name="🎯 Prompt", value=f"```\n{prompt}\n```", inline=False)
                        if negative_prompt:
                            embed.add_field(name="🚫 Negative", value=f"```\n{negative_prompt}\n```", inline=False)
                        embed.set_footer(text=f"⚡ Steps: {steps} | ขนาด: {width}x{height}")
                        
                        await progress_msg.edit(content=None, embed=embed, attachments=[file])
                    else:
                        err_text = await resp.text()
                        logger.error(f"SD API Error: {err_text}")
                        await progress_msg.edit(content=f"❌ การสร้างภาพล้มเหลว (Code {resp.status}) บางอย่างผิดพลาดที่ตัว SD")
        except asyncio.TimeoutError:
            await progress_msg.edit(content="⏳ การสร้างภาพใช้เวลานานเกินไป! (Timeout)")
        except Exception as e:
            logger.error(f"Error calling SD API: {e}")
            await progress_msg.edit(content=f"❌ เกิดข้อผิดพลาดในระบบ: `{e}`")

    @_guild_scope_decorator()
    @app_commands.command(name="สร้างวิดีโอ", description="🎬 สร้างวิดีโอด้วย AI (จำใจต้องลงปลั๊กอิน AnimateDiff ก่อน)")
    @app_commands.describe(
        prompt="สิ่งที่ต้องการให้วาดและเคลื่อนไหว (ภาษาอังกฤษ)",
        frames="ความยาวเฟรม (มาตรฐานคือ 16 เฟรม)",
        width="ความกว้าง",
        height="ความสูง"
    )
    async def create_video(
        self,
        interaction: discord.Interaction,
        prompt: str,
        frames: int = 16,
        width: int = 512,
        height: int = 512
    ):
        await interaction.response.defer(thinking=True)
        
        is_online = await self.check_sd_api()
        if not is_online:
            return await interaction.followup.send("❌ ไม่สามารถเชื่อมต่อกับ SD WebUI ได้!")

        # AnimateDiff payload argument สำหรับ A1111 / Forge
        payload = {
            "prompt": prompt,
            "negative_prompt": "nsfw, text, watermark, bad quality, glitch",
            "steps": 20,
            "width": width,
            "height": height,
            "cfg_scale": 7,
            "alwayson_scripts": {
                "AnimateDiff": {
                    "args": [
                        {
                            "enable": True,
                            "video_length": min(max(frames, 8), 32), # 8 ถึง 32 เฟรม
                            "fps": 8,
                            "loop_number": 0,
                            "closed_loop": "R-P",
                            "format": ["GIF", "MP4"],
                            "model": "mm_sd_v15_v2.safetensors"
                        }
                    ]
                }
            }
        }

        progress_msg = await interaction.followup.send("⏳ กำลังเริ่มสร้างวิดีโอ อนิเมชั่น... (อาจใช้เวลา 2-5 นาทีขึ้นอยู่กับการ์ดจอ)")

        try:
            async with aiohttp.ClientSession() as session:
                # ตั้ง timeout ยาวมาก เพราะทำวีดีโอใช้เวลานาน
                async with session.post(f"{self.sd_url}/sdapi/v1/txt2img", json=payload, timeout=aiohttp.ClientTimeout(total=900)) as resp:
                    if resp.status == 200:
                        # ปกติ API ของ AnimateDiff มักจะไม่ตอบกลับเป็นวิดีโอ base64 โดยตรงเหมือนรูปภาพ 
                        # แต่วิดีโอจะถูกเซฟไปที่โฟลเดอร์ outputs/txt2img-images/AnimateDiff ภายในเครื่อง SD ตัวนั้น
                        await progress_msg.edit(content=f"✅ **วิดีโอสร้างเสร็จแล้ว!**\nเนื่องจากข้อจำกัดของ API วิดีโอจะไม่ได้ถูกส่งเข้า Discord โดยตรง\n📁 **โปรดตรวจสอบที่โฟลเดอร์ WebUI ของคุณ:** `outputs/txt2img-images/AnimateDiff/`")
                    else:
                        err_text = await resp.text()
                        logger.error(f"SD AnimateDiff Error: {err_text}")
                        await progress_msg.edit(content=f"❌ การสร้างวิดีโอล้มเหลว บางทีคุณอาจจะยังไม่ได้ลงปลั๊กอิน AnimateDiff ในหน้าเว็บ WebUI\n(Code: {resp.status})")
        except asyncio.TimeoutError:
            await progress_msg.edit(content="⏳ การสร้างวิดีโอใช้เวลานานเกินกำหนด! (Timeout)")
        except Exception as e:
            logger.error(f"Error calling AnimateDiff API: {e}")
            await progress_msg.edit(content=f"❌ เกิดข้อผิดพลาดในระบบ: `{e}`")

async def setup(bot):
    await bot.add_cog(AIMedia(bot))
