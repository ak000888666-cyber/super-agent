import os
import logging
import asyncio
import aiosqlite
import base64
import io
from io import BytesIO
from aiohttp import web
from aiogram import Bot, Dispatcher, types, F
from aiogram.filters import Command
from aiogram.webhook.aiohttp_server import SimpleRequestHandler
from langchain_groq import ChatGroq
from groq import AsyncGroq
from pypdf import PdfReader
from dotenv import load_dotenv
import aiohttp as aiohttp_client
import urllib.parse

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
        await db.execute("""
            CREATE TABLE IF NOT EXISTS summaries (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                user_id INTEGER NOT NULL UNIQUE,
                summary TEXT NOT NULL
            )
        """)
        await db.commit()

async def save_message(user_id, role, content):
    async with aiosqlite.connect(DB_PATH) as db:
        await db.execute("INSERT INTO chat_history (user_id, role, content) VALUES (?, ?, ?)", (user_id, role, content))
        await db.commit()

async def get_history(user_id, limit=6):
    async with aiosqlite.connect(DB_PATH) as db:
        db.row_factory = aiosqlite.Row
        async with db.execute("SELECT role, content FROM chat_history WHERE user_id = ? ORDER BY id DESC LIMIT ?", (user_id, limit)) as cursor:
            rows = await cursor.fetchall()
            return [{"role": row["role"], "content": row["content"]} for row in reversed(rows)]

async def get_summary(user_id):
    async with aiosqlite.connect(DB_PATH) as db:
        db.row_factory = aiosqlite.Row
        async with db.execute("SELECT summary FROM summaries WHERE user_id = ?", (user_id,)) as cursor:
            row = await cursor.fetchone()
            return row["summary"] if row else "لا يوجد ملخص سابق."

async def save_summary(user_id, summary):
    async with aiosqlite.connect(DB_PATH) as db:
        await db.execute("INSERT OR REPLACE INTO summaries (user_id, summary) VALUES (?, ?)", (user_id, summary))
        await db.commit()

# --- إعداد الذكاء الاصطناعي ---
llm = ChatGroq(temperature=0.5, groq_api_key=GROQ_API_KEY, model_name="openai/gpt-oss-20b")

# موديل الرؤية (صيغة حديثة)
vision_llm = ChatGroq(temperature=0.3, groq_api_key=GROQ_API_KEY, model_name="meta-llama/llama-4-scout-17b-16e-instruct")

client = AsyncGroq(api_key=GROQ_API_KEY)

# تعليمات الشخصية: عامية سعودية ودودة
system_prompt = """أنت وكيل ذكاء اصطناعي شخصي، اسمك "سوبر". 
تتكلم بالعامية السعودية/الخليجية البسيطة والودية، وتستخدم الإيموجي (😊، 🤔، 📝، 💡).
- إذا كان الطلب غامضاً، اسأل: "تبغى ملخص سريع ولا شرح كامل؟".
- لا تكرر السؤال إذا اختار المستخدم.
- إذا كان الطلب واضحاً، ابدأ فوراً.
- لا تصحح أخطاء الإملاء، افهم القصد.
- قدم الخطوات الطويلة على شكل نقاط (1، 2، 3) وانتظر الموافقة.
- لا تستخدم الجداول (|) أو رموز Markdown (مثل ** أو ##). استخدم النقاط العادية.
- لا تستخدم وسوم HTML.
- استخدم اللهجة السعودية الخفيفة (مثل: "وش تبي"، "تمام"، "أبشر")."""

bot = Bot(token=BOT_TOKEN)
dp = Dispatcher()

@dp.message(Command("start"))
async def cmd_start(message: types.Message):
    await message.answer("هلا والله! أنا وكيلك الخارق. أقدر أقرأ PDF، أطلع صور، وأحلل الصور والصوت. وش تبيني أسوي لك اليوم؟ 🤖✨")

# --- توليد الصور ---
async def generate_image(prompt_text):
    encoded_prompt = urllib.parse.quote(prompt_text)
    url = f"https://image.pollinations.ai/prompt/{encoded_prompt}?width=1024&height=1024&nologo=true"
    async with aiohttp_client.ClientSession() as session:
        async with session.get(url) as resp:
            if resp.status == 200:
                return await resp.read()
    return None

# --- PDF ---
@dp.message(F.document)
async def handle_document(message: types.Message):
    user_id = message.from_user.id
    doc = message.document
    if not doc.file_name.lower().endswith('.pdf'):
        await message.answer("عطني ملف PDF بس، الله يعافيك.")
        return
    
    await message.answer("طيب، جاري أقرأ الملف وألخصه لك...")
    try:
        file_info = await bot.get_file(doc.file_id)
        downloaded_file = await bot.download_file(file_info.file_path)
        
        reader = PdfReader(io.BytesIO(downloaded_file.read()))
        text = ""
        for page in reader.pages:
            text += page.extract_text() or ""
        
        if not text.strip():
            await message.answer("الملف ما فيه نص واضح، جرب ملف ثاني.")
            return
            
        prompt = f"لخص هذا النص في نقاط واضحة ومختصرة بالعامية:\n\n{text[:4000]}"
        response = await llm.ainvoke([{"role": "user", "content": prompt}])
        
        await message.answer(f"📄 ملخص الملف:\n\n{response.content}")
    except Exception as e:
        logging.error(f"PDF Error: {e}")
        await message.answer("أوه، صار خطأ في قراءة الملف.")

# --- النصوص ---
@dp.message(F.text)
async def handle_text(message: types.Message):
    user_id = message.from_user.id
    user_text = message.text
    await message.answer("ثواني أفكر... 🧠")
    try:
        if any(word in user_text for word in ["ارسم", "صمم", "generate", "image"]):
            await message.answer("طيب، جاري أرسم لك... 🎨")
            image_bytes = await generate_image(user_text)
            if image_bytes:
                await message.answer_photo(types.BufferedInputFile(image_bytes, filename="image.jpg"), caption="🎨 خذ الصورة، عساها تعجبك!")
            else:
                await message.answer("عجزت أرسم، جرب وصف ثاني.")
            return

        history = await get_history(user_id)
        summary = await get_summary(user_id)
        
        messages = [{"role": "system", "content": system_prompt}]
        if summary != "لا يوجد ملخص سابق.":
            messages.append({"role": "system", "content": f"ملخص المحادثات السابقة: {summary}"})
        messages.extend(history)
        messages.append({"role": "user", "content": user_text})
        
        response = await llm.ainvoke(messages)
        reply = response.content
        
        await save_message(user_id, "user", user_text)
        await save_message(user_id, "assistant", reply)
        
        await message.answer(reply)
        
        async with aiosqlite.connect(DB_PATH) as db:
            async with db.execute("SELECT COUNT(*) FROM chat_history WHERE user_id = ?", (user_id,)) as cursor:
                count = (await cursor.fetchone())[0]
                if count % 10 == 0:
                    sum_prompt = f"لخص المحادثة التالية في جملتين بالعامية:\n{user_text}\n{reply}"
                    sum_res = await llm.ainvoke([{"role": "user", "content": sum_prompt}])
                    await save_summary(user_id, sum_res.content)
                    
    except Exception as e:
        logging.error(f"Error: {e}")
        await message.answer("أوه، صار خطأ بسيط. جرب مرة ثانية.")

# --- الصور ---
@dp.message(F.photo)
async def handle_photo(message: types.Message):
    user_id = message.from_user.id
    await message.answer("جاري أتفرج على الصورة... 🖼️")
    try:
        photo = message.photo[-1]
        file_info = await bot.get_file(photo.file_id)
        downloaded_file = await bot.download_file(file_info.file_path)
        
        # تجهيز الصورة كـ Base64
        image_data = base64.b64encode(downloaded_file.read()).decode("utf-8")
        
        # إرسال الطلب للموديل بالصيغة الصحيحة
        response = await vision_llm.ainvoke([
            {
                "role": "user", 
                "content": [
                    {"type": "text", "text": "حلل لي هذي الصورة واشرح محتواها بالعامية."},
                    {"type": "image_url", "image_url": {"url": f"data:image/jpeg;base64,{image_data}"}}
                ]
            }
        ])
        await message.answer(response.content)
    except Exception as e:
        logging.error(f"Vision Error: {e}")
        await message.answer("عجزت أحلل الصورة، جرب صورة ثانية أو تأكد إنها مو كبيرة.")

# --- الصوت ---
@dp.message(F.voice)
async def handle_voice(message: types.Message):
    user_id = message.from_user.id
    await message.answer("جاري أسمع الرسالة الصوتية... 🎤")
    try:
        file = await bot.get_file(message.voice.file_id)
        buffer = BytesIO()
        await bot.download_file(file.file_path, destination=buffer)
        buffer.name = "voice.ogg"
        buffer.seek(0)
        
        transcription = await client.audio.transcriptions.create(model="whisper-large-v3", file=buffer, language="ar")
        text = transcription.text
        await message.answer(f"📝 النص: {text}\n\nثواني أفكر...")
        
        response = await llm.ainvoke([{"role": "user", "content": text}])
        await message.answer(response.content)
    except Exception as e:
        logging.error(f"Voice Error: {e}")
        await message.answer("عجزت أفهم الصوت، جرب مرة ثانية.")

# --- إعداد السيرفر ---
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
