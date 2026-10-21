import os
import logging
import asyncio
import aiosqlite
import base64
from io import BytesIO
from aiohttp import web
from aiogram import Bot, Dispatcher, types, F
from aiogram.filters import Command
from aiogram.webhook.aiohttp_server import SimpleRequestHandler
from langchain_groq import ChatGroq
from groq import AsyncGroq
from dotenv import load_dotenv

load_dotenv()
logging.basicConfig(level=logging.INFO)

BOT_TOKEN = os.getenv("BOT_TOKEN")
GROQ_API_KEY = os.getenv("GROQ_API_KEY")
WEBHOOK_HOST = os.getenv("RENDER_EXTERNAL_URL", "https://your-app.onrender.com")
WEBHOOK_PATH = "/webhook"
WEBHOOK_URL = f"{WEBHOOK_HOST}{WEBHOOK_PATH}"

# --- قاعدة البيانات ---
DB_PATH = "agent.db"

async def init_db():
    async with aiosqlite.connect(DB_PATH) as db:
        await db.execute("""
            CREATE TABLE IF NOT EXISTS chat_history (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                user_id INTEGER NOT NULL,
                role TEXT NOT NULL,
                content TEXT NOT NULL,
                created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
            )
        """)
        await db.commit()

async def save_message(user_id, role, content):
    async with aiosqlite.connect(DB_PATH) as db:
        await db.execute(
            "INSERT INTO chat_history (user_id, role, content) VALUES (?, ?, ?)",
            (user_id, role, content)
        )
        await db.commit()

async def get_history(user_id, limit=6):
    async with aiosqlite.connect(DB_PATH) as db:
        db.row_factory = aiosqlite.Row
        async with db.execute(
            "SELECT role, content FROM chat_history WHERE user_id = ? ORDER BY id DESC LIMIT ?",
            (user_id, limit)
        ) as cursor:
            rows = await cursor.fetchall()
            return [{"role": row["role"], "content": row["content"]} for row in reversed(rows)]

# --- إعداد الذكاء الاصطناعي ---
llm = ChatGroq(
    temperature=0.5, 
    groq_api_key=GROQ_API_KEY, 
    model_name="openai/gpt-oss-20b"
)

# موديل الرؤية
vision_llm = ChatGroq(
    temperature=0.3,
    groq_api_key=GROQ_API_KEY,
    model_name="meta-llama/llama-4-scout-17b-16e-instruct"
)

# عميل Groq (للصوت)
client = AsyncGroq(api_key=GROQ_API_KEY)

system_prompt = """أنت وكيل ذكاء اصطناعي شخصي، اسمك "سوبر". أنت ودود، تستخدم الإيموجي (😊، 🤔، 📝).
قواعد:
1. إذا كان الطلب غامضاً جداً، اسأل "ملخص أم شرح كامل؟".
2. لا تكرر السؤال إذا اختار المستخدم.
3. إذا كان الطلب واضحاً، ابدأ فوراً.
4. لا تصحح أخطاء الإملاء.
5. قدم الخطوات الطويلة على شكل نقاط وانتظر الموافقة.
6. لا تستخدم الجداول (|) أو رموز Markdown مثل ** أو ##. استخدم (1، 2، 3) أو (-).
7. لا تستخدم وسوم HTML.
8. استخدم لغة عربية سليمة."""

bot = Bot(token=BOT_TOKEN)
dp = Dispatcher()

@dp.message(Command("start"))
async def cmd_start(message: types.Message):
    await message.answer("أهلاً بك! أنا وكيلك الذكي الشخصي. اسألني أي شي، أو أرسل لي صورة أو رسالة صوتية! 🤖✨")

# --- معالجة النصوص ---
@dp.message(F.text)
async def handle_text(message: types.Message):
    user_id = message.from_user.id
    user_text = message.text
    await message.answer("🧠 جاري التفكير...")
    try:
        history = await get_history(user_id)
        messages = [{"role": "system", "content": system_prompt}]
        messages.extend(history)
        messages.append({"role": "user", "content": user_text})
        response = await llm.ainvoke(messages)
        reply = response.content
        await save_message(user_id, "user", user_text)
        await save_message(user_id, "assistant", reply)
        await message.answer(reply)
    except Exception as e:
        logging.error(f"Error: {e}")
        await message.answer("⚠️ عذراً، حدث خطأ بسيط. جرب مرة ثانية! 💪")

# --- معالجة الصور ---
@dp.message(F.photo)
async def handle_photo(message: types.Message):
    user_id = message.from_user.id
    await message.answer("🖼️ جاري تحليل الصورة...")
    try:
        photo = message.photo[-1]
        file_info = await bot.get_file(photo.file_id)
        downloaded_file = await bot.download_file(file_info.file_path)
        image_data = base64.b64encode(downloaded_file.read()).decode("utf-8")
        
        response = await vision_llm.ainvoke([
            {"role": "user", "content": [
                {"type": "text", "text": "حلل هذه الصورة واشرح محتواها باللغة العربية. إذا كانت تحتوي على نص، اقرأه واشرحه."},
                {"type": "image_url", "image_url": {"url": f"data:image/jpeg;base64,{image_data}"}}
            ]}
        ])
        
        reply = response.content
        await save_message(user_id, "user", "[صورة]")
        await save_message(user_id, "assistant", reply)
        await message.answer(reply)
    except Exception as e:
        logging.error(f"Vision Error: {e}")
        await message.answer("⚠️ عذراً، لم أستطع تحليل الصورة. تأكد من وضوحها وحاول مرة ثانية. 💪")

# --- معالجة الصوت ---
@dp.message(F.voice)
async def handle_voice(message: types.Message):
    user_id = message.from_user.id
    await message.answer("🎤 جاري تحويل الصوت إلى نص...")
    try:
        file = await bot.get_file(message.voice.file_id)
        buffer = BytesIO()
        await bot.download_file(file.file_path, destination=buffer)
        buffer.name = "voice.ogg"
        buffer.seek(0)
        
        transcription = await client.audio.transcriptions.create(
            model="whisper-large-v3",
            file=buffer,
            language="ar"
        )
        
        text = transcription.text
        await message.answer(f"📝 النص: {text}\n\n🧠 جاري التفكير...")
        
        history = await get_history(user_id)
        messages = [{"role": "system", "content": system_prompt}]
        messages.extend(history)
        messages.append({"role": "user", "content": text})
        
        response = await llm.ainvoke(messages)
        reply = response.content
        
        await save_message(user_id, "user", f"[صوت] {text}")
        await save_message(user_id, "assistant", reply)
        await message.answer(reply)
        
    except Exception as e:
        logging.error(f"Voice Error: {e}")
        await message.answer("⚠️ عذراً، لم أستطع فهم الصوت. تأكد من وضوح التسجيل وحاول مرة ثانية. 💪")

# --- إعداد السيرفر والويب هوك ---
async def on_startup(app):
    await init_db()
    await bot.set_webhook(WEBHOOK_URL)
    logging.info(f"✅ Webhook set to {WEBHOOK_URL}")

async def health_check(request):
    return web.Response(text="OK")

async def main():
    app = web.Application()
    webhook_requests_handler = SimpleRequestHandler(dispatcher=dp, bot=bot)
    webhook_requests_handler.register(app, path=WEBHOOK_PATH)
    app.router.add_get("/", health_check)
    app.on_startup.append(on_startup)
    
    port = int(os.environ.get("PORT", 8080))
    runner = web.AppRunner(app)
    await runner.setup()
    site = web.TCPSite(runner, "0.0.0.0", port)
    await site.start()
    
    print(f"🚀 الوكيل شغال على المنفذ {port}")
    await asyncio.Event().wait()

if __name__ == "__main__":
    asyncio.run(main())
