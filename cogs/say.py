import discord
from discord import app_commands
from discord.ext import commands
import logging
import time
from collections import defaultdict
import os
import asyncio
import random  # Add this import for random number generation
from datetime import datetime

# Configure logging
def setup_logging():
    if not os.path.exists('logs'):
        os.makedirs('logs')
    logging.basicConfig(
        level=logging.INFO,
        format='%(asctime)s - %(name)s - %(levelname)s - %(message)s',
        handlers=[
            logging.FileHandler('logs/say.log'),
            logging.StreamHandler()
        ]
    )
    return logging.getLogger('say_cog')

logger = setup_logging()

class Say(commands.Cog):
    def __init__(self, bot: commands.Bot):
        self.bot = bot
        self.cooldowns = defaultdict(lambda: defaultdict(float))
        self.say_cooldown_time = 300  # 5 minutes cooldown for say command
        self.spam_cooldown_time = 7200  # 2 hours cooldown for spam command
        self.random_number_cooldown_time = 900  # 15 minutes cooldown for random number
        self.story_cooldown_time = 1800  # 30 minutes cooldown for story generation

    @app_commands.command(name="พูด", description="ให้บอทพูดข้อความที่คุณต้องการ")
    @app_commands.describe(message="ข้อความที่ต้องการให้บอทพูด")
    async def say(self, interaction: discord.Interaction, message: str):
        try:
            # Check permissions
            if not interaction.user.guild_permissions.manage_messages:
                await interaction.response.send_message("❌ คุณไม่มีสิทธิ์ใช้คำสั่งนี้", ephemeral=True)
                return

            # Check cooldown
            current_time = time.time()
            if current_time - self.cooldowns[interaction.guild.id][interaction.user.id] < self.say_cooldown_time:
                remaining = int(self.say_cooldown_time - (current_time - self.cooldowns[interaction.guild.id][interaction.user.id]))
                await interaction.response.send_message(f"⏳ กรุณารอ {remaining} วินาทีก่อนใช้คำสั่งนี้อีกครั้ง", ephemeral=True)
                return

            # Update cooldown
            self.cooldowns[interaction.guild.id][interaction.user.id] = current_time

            # Log the command usage
            logger.info(f"Say command used by {interaction.user} in {interaction.guild}: {message}")

            # Send the message
            await interaction.response.send_message(message)

        except Exception as e:
            logger.error(f"Error in say command: {e}")
            await interaction.response.send_message("❌ เกิดข้อผิดพลาดในการส่งข้อความ", ephemeral=True)
    
    @app_commands.command(name="สแปม", description="ส่งข้อความซ้ำหลายครั้ง")
    @app_commands.describe(times="จำนวนครั้งที่ต้องการส่งข้อความ", message="ข้อความที่ต้องการส่ง")
    async def spam(self, interaction: discord.Interaction, times: int, message: str):
        try:
            # Check permissions
            if not interaction.user.guild_permissions.administrator:
                return await interaction.response.send_message("❌ คุณต้องมีสิทธิ์ Administrator เพื่อใช้คำสั่งนี้", ephemeral=True)

            # Check cooldown
            current_time = time.time()
            if current_time - self.cooldowns[interaction.guild.id][interaction.user.id] < self.spam_cooldown_time:
                remaining = int(self.spam_cooldown_time - (current_time - self.cooldowns[interaction.guild.id][interaction.user.id]))
                minutes = remaining // 60
                seconds = remaining % 60
                await interaction.response.send_message(f"⏳ กรุณารออีก {minutes} นาที {seconds} วินาทีก่อนใช้คำสั่งนี้อีกครั้ง", ephemeral=True)
                return

            if times > 1000:  # จำกัดไม่ให้รัวเกิน 1000 ครั้ง
                await interaction.response.send_message("อย่าสแปมเกินไปนะ! (สูงสุด 1000 ครั้ง)", ephemeral=True)
                return
                
            await interaction.response.defer(ephemeral=True)
            
            try:
                progress_message = await interaction.followup.send("⏳ กำลังส่งข้อความ...", ephemeral=True)
                
                for i in range(times):
                    await interaction.channel.send(message)
                    if (i + 1) % 10 == 0:  # Update progress every 10 messages
                        await progress_message.edit(content=f"⏳ กำลังส่งข้อความ... ({i + 1}/{times})")
                    await asyncio.sleep(0.01)  # Add a small delay to avoid rate limits
                    
                # Update cooldown after successful execution
                self.cooldowns[interaction.guild.id][interaction.user.id] = current_time
                
                await progress_message.edit(content="✅ ส่งข้อความเรียบร้อยแล้ว")
            except discord.Forbidden:
                await interaction.followup.send("❌ ไม่มีสิทธิ์ในการส่งข้อความในช่องนี้", ephemeral=True)
            except Exception as e:
                await interaction.followup.send(f"❌ เกิดข้อผิดพลาด: {str(e)}", ephemeral=True)
        except Exception as e:
            logger.error(f"Error in spam command: {e}")
            await interaction.response.send_message("❌ เกิดข้อผิดพลาดในการส่งข้อความ", ephemeral=True)

    @app_commands.command(name="สุ่มเลข", description="สุ่มเลข 6 หลัก")
    @app_commands.describe(times="จำนวนครั้งที่ต้องการสุ่ม")
    async def random_number(self, interaction: discord.Interaction, times: int = 1):
        try:
            # Check cooldown
            current_time = time.time()
            if current_time - self.cooldowns[interaction.guild.id][interaction.user.id] < self.random_number_cooldown_time:
                remaining = int(self.random_number_cooldown_time - (current_time - self.cooldowns[interaction.guild.id][interaction.user.id]))
                minutes = remaining // 60
                seconds = remaining % 60
                await interaction.response.send_message(f"⏳ กรุณารออีก {minutes} นาที {seconds} วินาทีก่อนใช้คำสั่งนี้อีกครั้ง", ephemeral=True)
                return

            if times > 100:  # จำกัดไม่ให้สุ่มเกิน 100 ครั้ง
                await interaction.response.send_message("อย่าสุ่มเกินไปนะ! (สูงสุด 100 ครั้ง)", ephemeral=True)
                return
                
            await interaction.response.defer(ephemeral=True)
            
            try:
                numbers = []
                for _ in range(times):
                    # Generate a random 6-digit number
                    number = random.randint(000000, 999999)
                    numbers.append(str(number))
                
                # Join all numbers with newlines
                result = "\n".join(numbers)
                await interaction.followup.send(f"🎲 เลขที่สุ่มได้:\n```\n{result}\n```", ephemeral=True)
                
                # Update cooldown after successful execution
                self.cooldowns[interaction.guild.id][interaction.user.id] = current_time
                
            except Exception as e:
                await interaction.followup.send(f"❌ เกิดข้อผิดพลาด: {str(e)}", ephemeral=True)
        except Exception as e:
            logger.error(f"Error in random_number command: {e}")
            await interaction.response.send_message("❌ เกิดข้อผิดพลาดในการสุ่มเลข", ephemeral=True)

    @app_commands.command(name="เรื่องราว", description="สร้างเรื่องราวแฟนตาซีสุ่ม")
    @app_commands.describe(
        genre="ประเภทของเรื่องราว (แฟนตาซี/ผจญภัย/รักโรแมนติก/สยองขวัญ)",
        length="ความยาวของเรื่องราว (สั้น/กลาง/ยาว)",
        is_quiz="ต้องการให้เป็นคำถามแบบเลือกตอบหรือไม่"
    )
    async def random_story(self, interaction: discord.Interaction, genre: str = "แฟนตาซี", length: str = "กลาง", is_quiz: bool = False):
        try:
            # Check cooldown
            current_time = time.time()
            if current_time - self.cooldowns[interaction.guild.id][interaction.user.id] < self.story_cooldown_time:
                remaining = int(self.story_cooldown_time - (current_time - self.cooldowns[interaction.guild.id][interaction.user.id]))
                minutes = remaining // 60
                seconds = remaining % 60
                await interaction.response.send_message(f"⏳ กรุณารออีก {minutes} นาที {seconds} วินาทีก่อนใช้คำสั่งนี้อีกครั้ง", ephemeral=True)
                return

            # Lists of story elements
            characters = {
                "แฟนตาซี": [
                    "นักผจญภัย", "พ่อมด", "นักรบ", "นักบวช", "พ่อค้า", "โจร", "ราชา", "ราชินี",
                    "มังกร", "ยักษ์", "นางฟ้า", "ปีศาจ", "นักล่า", "หมอผี", "นักร้อง", "นักเต้น",
                    "นักปราชญ์", "นักรบมังกร", "นักล่าสมบัติ", "นักเวทมนตร์", "นักรบเงา", "นักรบแห่งแสง",
                    "นักรบแห่งความมืด", "นักรบแห่งสายฟ้า", "นักรบแห่งสายน้ำ", "นักรบแห่งสายลม"
                ],
                "ผจญภัย": [
                    "นักสำรวจ", "นักโบราณคดี", "นักล่าสมบัติ", "นักเดินทาง", "นักผจญภัย", "นักล่ามังกร",
                    "นักล่าโจรสลัด", "นักล่าสัตว์ประหลาด", "นักล่าตำนาน", "นักล่าความลับ", "นักล่าความจริง",
                    "นักล่าความฝัน", "นักล่าความหวัง", "นักล่าความฝัน", "นักล่าความหวัง"
                ],
                "รักโรแมนติก": [
                    "เจ้าชาย", "เจ้าหญิง", "นักรบ", "หมอ", "ครู", "ศิลปิน", "นักดนตรี", "นักเขียน",
                    "นักเต้น", "นักร้อง", "นักแสดง", "ช่างภาพ", "นักออกแบบ", "นักธุรกิจ", "นักวิทยาศาสตร์"
                ],
                "สยองขวัญ": [
                    "นักสืบ", "หมอ", "นักข่าว", "นักเขียน", "นักศึกษา", "ตำรวจ", "นักบวช", "หมอผี",
                    "นักล่าปีศาจ", "นักล่าผี", "นักล่าความจริง", "นักล่าความลับ", "นักล่าความฝัน"
                ]
            }
            
            locations = {
                "แฟนตาซี": [
                    "ป่าลึก", "ถ้ำมังกร", "ปราสาทลอยฟ้า", "เมืองใต้ดิน", "เกาะลึกลับ", "ทะเลทราย",
                    "ภูเขาน้ำแข็ง", "ป่าดึกดำบรรพ์", "วัดโบราณ", "วังลับ", "ตลาดมืด", "หอคอยเวทมนตร์",
                    "ดินแดนแห่งความฝัน", "ดินแดนแห่งความมืด", "ดินแดนแห่งแสงสว่าง", "ดินแดนแห่งสายฟ้า"
                ],
                "ผจญภัย": [
                    "ป่าดึกดำบรรพ์", "ทะเลทราย", "เกาะลึกลับ", "ถ้ำโบราณ", "ปราสาทร้าง", "เมืองสาบสูญ",
                    "ดินแดนที่ถูกลืม", "เกาะสมบัติ", "ถ้ำมังกร", "ป่าต้องมนตร์", "ทะเลสาบลึกลับ"
                ],
                "รักโรแมนติก": [
                    "คาเฟ่", "สวนสาธารณะ", "ชายหาด", "ภูเขา", "ทะเลสาบ", "ปราสาท", "เมืองเก่า",
                    "ตลาดนัด", "ร้านหนังสือ", "โรงละคร", "สวนดอกไม้", "หอคอย", "วัง", "บ้านพักตากอากาศ"
                ],
                "สยองขวัญ": [
                    "บ้านร้าง", "โรงพยาบาลเก่า", "โรงเรียนร้าง", "โรงแรมผีสิง", "ป่าช้า", "ถ้ำมืด",
                    "บ้านผีสิง", "โรงงานร้าง", "เมืองร้าง", "เกาะผีสิง", "ปราสาทผีสิง"
                ]
            }
            
            events = {
                "แฟนตาซี": [
                    "ค้นพบสมบัติล้ำค่า", "ต่อสู้กับมังกร", "ไขปริศนาโบราณ", "ช่วยเหลือชาวบ้าน",
                    "ตามล่าผู้ร้าย", "เรียนรู้เวทมนตร์", "ค้นหาความจริง", "แก้แค้นให้ครอบครัว",
                    "พิสูจน์ความบริสุทธิ์", "ตามหาความรัก", "ปกป้องราชอาณาจักร", "ไขความลับของจักรวาล"
                ],
                "ผจญภัย": [
                    "ค้นพบสมบัติ", "ไขปริศนาโบราณ", "ตามล่าผู้ร้าย", "ช่วยเหลือชาวบ้าน",
                    "พิสูจน์ความบริสุทธิ์", "ตามหาความจริง", "แก้แค้นให้ครอบครัว", "ปกป้องโลก"
                ],
                "รักโรแมนติก": [
                    "พบรักแรก", "ตามหาความรัก", "พิสูจน์ความรัก", "ปกป้องความรัก", "ตามหาความจริง",
                    "แก้ไขความเข้าใจผิด", "ตามหาความหวัง", "พิสูจน์ความจริงใจ"
                ],
                "สยองขวัญ": [
                    "ไขปริศนาความตาย", "ตามล่าผี", "พิสูจน์ความจริง", "ตามหาความลับ",
                    "แก้ไขคำสาป", "ตามหาความจริง", "พิสูจน์ความบริสุทธิ์", "ปกป้องความจริง"
                ]
            }
            
            endings = {
                "แฟนตาซี": [
                    "และพวกเขาก็ใช้ชีวิตอย่างมีความสุขตลอดไป", "แต่เรื่องราวยังไม่จบเพียงเท่านี้",
                    "และนี่คือจุดเริ่มต้นของตำนานใหม่", "ทำให้พวกเขาได้เรียนรู้บทเรียนที่มีค่า"
                ],
                "ผจญภัย": [
                    "และนี่คือจุดเริ่มต้นของการผจญภัยครั้งใหม่", "ทำให้พวกเขาได้พบกับความจริงที่ซ่อนอยู่",
                    "และพวกเขาก็ได้เรียนรู้ว่าความกล้าหาญอยู่ที่ใจ", "ทำให้พวกเขาได้พบกับมิตรภาพที่แท้จริง"
                ],
                "รักโรแมนติก": [
                    "และพวกเขาก็ได้พบกับความรักที่แท้จริง", "ทำให้พวกเขาได้เรียนรู้ความหมายของความรัก",
                    "และนี่คือจุดเริ่มต้นของความรักที่แท้จริง", "ทำให้พวกเขาได้พบกับความสุขที่แท้จริง"
                ],
                "สยองขวัญ": [
                    "และความลับที่ซ่อนอยู่ก็ถูกเปิดเผย", "ทำให้พวกเขาได้เรียนรู้ความจริงที่โหดร้าย",
                    "และนี่คือจุดจบของความลึกลับ", "ทำให้พวกเขาได้พบกับความจริงที่ซ่อนอยู่"
                ]
            }

            # Validate genre and length
            if genre not in characters:
                genre = "แฟนตาซี"
            if length not in ["สั้น", "กลาง", "ยาว"]:
                length = "กลาง"

            # Generate random story elements
            character = random.choice(characters[genre])
            location = random.choice(locations[genre])
            event = random.choice(events[genre])
            ending = random.choice(endings[genre])

            # Create embed for better display
            embed = discord.Embed(
                title=f"📖 เรื่องราว{genre}",
                color=discord.Color.random()
            )

            if is_quiz:
                # Generate multiple choice options
                all_characters = [c for chars in characters.values() for c in chars]
                all_locations = [l for locs in locations.values() for l in locs]
                all_events = [e for evts in events.values() for e in evts]
                all_endings = [e for ends in endings.values() for e in ends]

                # Remove the correct answers from the pools
                all_characters.remove(character)
                all_locations.remove(location)
                all_events.remove(event)
                all_endings.remove(ending)

                # Generate wrong options
                wrong_characters = random.sample(all_characters, 3)
                wrong_locations = random.sample(all_locations, 3)
                wrong_events = random.sample(all_events, 3)
                wrong_endings = random.sample(all_endings, 3)

                # Create multiple choice options
                character_options = [character] + wrong_characters
                location_options = [location] + wrong_locations
                event_options = [event] + wrong_events
                ending_options = [ending] + wrong_endings

                # Shuffle options
                random.shuffle(character_options)
                random.shuffle(location_options)
                random.shuffle(event_options)
                random.shuffle(ending_options)

                # Create story content with multiple choice
                story_content = "**คำถาม:** เลือกคำตอบที่ถูกต้องสำหรับแต่ละข้อ\n\n"
                story_content += "**1. ตัวละครในเรื่องคือใคร?**\n"
                for i, opt in enumerate(character_options, 1):
                    story_content += f"{i}. {opt}\n"
                story_content += "\n**2. เรื่องราวเกิดขึ้นที่ไหน?**\n"
                for i, opt in enumerate(location_options, 1):
                    story_content += f"{i}. {opt}\n"
                story_content += "\n**3. เกิดอะไรขึ้นในเรื่อง?**\n"
                for i, opt in enumerate(event_options, 1):
                    story_content += f"{i}. {opt}\n"
                story_content += "\n**4. เรื่องราวจบลงอย่างไร?**\n"
                for i, opt in enumerate(ending_options, 1):
                    story_content += f"{i}. {opt}\n"

                # Store correct answers in footer
                correct_answers = {
                    "ตัวละคร": character_options.index(character) + 1,
                    "สถานที่": location_options.index(location) + 1,
                    "เหตุการณ์": event_options.index(event) + 1,
                    "บทสรุป": ending_options.index(ending) + 1
                }
                embed.set_footer(text=f"เฉลย: {', '.join(f'{k}: {v}' for k, v in correct_answers.items())}")
            else:
                # Original story format
                story_content = f"**ตัวละคร:** {character}\n"
                story_content += f"**สถานที่:** {location}\n"
                story_content += f"**เหตุการณ์:** {event}\n"
                story_content += f"**บทสรุป:** {ending}"

                # Add length indicator
                length_indicators = {
                    "สั้น": "📝",
                    "กลาง": "📄",
                    "ยาว": "📚"
                }
                story_content += f"\n\n**ความยาว:** {length_indicators[length]} {length}"

                embed.description = story_content

                # Add random emojis as footer if not quiz mode
                if not is_quiz:
                    genre_emojis = {
                        "แฟนตาซี": ["✨", "🌟", "💫", "⭐", "🔮", "🗡️", "🛡️", "👑", "🐉", "🌙", "☀️", "🌠"],
                        "ผจญภัย": ["🗺️", "🧭", "⚔️", "🛡️", "🗡️", "🏹", "🎯", "🎪", "🏰", "🌋", "🏔️", "🌊"],
                        "รักโรแมนติก": ["💖", "💝", "💕", "💓", "💗", "💘", "💞", "💟", "💌", "💋", "💍", "💎"],
                        "สยองขวัญ": ["👻", "💀", "🕯️", "🔮", "⚰️", "🕯️", "🔪", "🩸", "🕷️", "🦇", "🌙", "🌑"]
                    }
                    footer_emojis = " ".join(random.sample(genre_emojis[genre], 3))
                    embed.set_footer(text=f"เรื่องราว{genre} | {footer_emojis}")

                # Add a random color border based on genre
                genre_colors = {
                    "แฟนตาซี": discord.Color.purple(),
                    "ผจญภัย": discord.Color.blue(),
                    "รักโรแมนติก": discord.Color.pink(),
                    "สยองขวัญ": discord.Color.dark_red()
                }
                embed.color = genre_colors[genre]

                # Add timestamp
                embed.timestamp = datetime.now()

            await interaction.response.send_message(embed=embed)
        except Exception as e:
            logger.error(f"Error in random_story command: {e}")
            await interaction.response.send_message("❌ เกิดข้อผิดพลาดในการสร้างเรื่องราว", ephemeral=True)

async def setup(bot: commands.Bot):
    cog = Say(bot)
    await bot.add_cog(cog) 